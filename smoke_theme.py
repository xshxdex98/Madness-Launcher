"""Checks for the palette, the theme customiser and per-game themes."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Every config and branding write goes to a throwaway folder: these checks
# must never touch the user's own theme, logo or saved game paths.
SANDBOX = Path(tempfile.mkdtemp(prefix="madness-theme-"))
os.environ["MADNESS_LAUNCHER_HOME"] = str(SANDBOX)

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from madness_launcher import paths  # noqa: E402
from madness_launcher.config import Config, Settings  # noqa: E402
from madness_launcher.games.registry import GAMES  # noqa: E402
from madness_launcher.ui import icons, palette, theme  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


app = QApplication.instance() or QApplication(sys.argv)
theme.set_icons(icons.ensure_icons())
app.setStyleSheet(theme.stylesheet())

from madness_launcher.ui.main_window import (  # noqa: E402
    CHAT_KEY,
    LIBRARY_KEY,
    NEWS_KEY,
    RECORDS_KEY,
    SETTINGS_KEY,
    MainWindow,
)

check(
    "sandboxed away from the real data folder",
    SANDBOX in paths.app_root().parents or paths.app_root() == SANDBOX,
    str(paths.app_root()),
)

# ----------------------------------------------------------------------
print("\ncolour arithmetic")
check("a full hex parses", palette.normalise("#aabbcc") == "#AABBCC")
check("shorthand expands", palette.normalise("#abc") == "#AABBCC")
check("junk falls back", palette.normalise("nope", "#123456") == "#123456")
check("an empty string falls back", palette.normalise("", "#123456") == "#123456")
check("mixing nothing keeps the first", palette.mix("#000000", "#FFFFFF", 0) == "#000000")
check("mixing fully gives the second", palette.mix("#000000", "#FFFFFF", 1) == "#FFFFFF")
check("mixing halfway is halfway", palette.mix("#000000", "#FFFFFF", 0.5) == "#808080")
check("white is the brightest there is", round(palette.luminance("#FFFFFF"), 3) == 1.0)
check("black is the darkest", palette.luminance("#000000") == 0.0)
check("black on white is the widest contrast", round(palette.contrast("#000", "#FFF"), 1) == 21.0)
check("contrast with itself is 1", round(palette.contrast("#3366FF", "#3366FF"), 3) == 1.0)

# ----------------------------------------------------------------------
print("\nthe shipped palette is exactly what it was")
SHIPPED = {
    "bg": "#0B0F16", "surface": "#121824", "elevated": "#18202E",
    "hover": "#1F2937", "border": "#222C3C", "border_strong": "#2F3D51",
    "text": "#E7ECF3", "muted": "#8795AB", "faint": "#5A6982",
    "good": "#4CAF7D", "warn": "#D9A441", "bad": "#D9584B",
    "accent": "#E0912F",
}
drift = {
    k: (v, getattr(palette.DEFAULT, k))
    for k, v in SHIPPED.items()
    if getattr(palette.DEFAULT, k) != v
}
check("no colour drifted when it became data", not drift, str(drift))
check(
    "the accent still gets the near-black it was hardcoded with",
    palette.DEFAULT.on_accent == "#14161A",
    palette.DEFAULT.on_accent,
)
check(
    "a dark accent gets light text instead",
    palette.DEFAULT.with_accent("#202060").on_accent == palette.ON_ACCENT_LIGHT,
)

# ----------------------------------------------------------------------
print("\nderiving from the three seeds")
d = palette.DEFAULT
check(
    "the stock seeds reproduce the stock palette exactly",
    palette.derive(d.bg, d.text, d.accent) == d,
    "averaged mix amounts would flatten its blue tint",
)
light = palette.derive("#F4F6F9", "#161A20", "#C2661B")
check("a light background stays light", palette.luminance(light.bg) > 0.8)
check(
    "its raised surfaces go darker, not lighter",
    palette.luminance(light.elevated) < palette.luminance(light.bg),
)
check("its muted text is readable", not palette.readability(light), str(palette.readability(light)))
check("green still means verified", light.good == d.good)
check("every shipped preset is readable", all(not palette.readability(p) for p in palette.PRESETS.values()))
check(
    "an unreadable palette is called out",
    len(palette.readability(palette.derive("#101010", "#151515", "#111111"))) >= 3,
)

# ----------------------------------------------------------------------
print("\na broken config does not stop the launcher")
p = palette.Palette.from_dict(
    {"bg": "not a colour", "surface": 12, "nosuchfield": "#FFFFFF", "text": "#abc"}
)
check("a malformed colour falls back", p.bg == d.bg)
check("a non-string value is ignored", p.surface == d.surface)
check("an unknown field is ignored", not hasattr(p, "nosuchfield"))
check("a good value alongside bad ones survives", p.text == "#AABBCC")
check("something that is not a mapping at all", palette.Palette.from_dict("nope") == d)
check("nothing saved means the shipped palette", palette.Palette.from_dict({}) == d)
check(
    "only the differences are stored",
    palette.DEFAULT.with_accent("#FF0000").changes() == {"accent": "#FF0000"},
)
check("an unchanged palette stores nothing", d.changes() == {})

# ----------------------------------------------------------------------
print("\nconfig round-trip")
cfg = Config.load()
cfg.settings.theme = {"accent": "#FF0066"}
cfg.settings.game_themes[GAMES[0].id] = {"bg": "#120E1C"}
cfg.save()
again = Config.load()
check("the global theme reloads", again.settings.theme == {"accent": "#FF0066"})
check(
    "a game theme reloads",
    again.settings.game_themes.get(GAMES[0].id) == {"bg": "#120E1C"},
)
check(
    "a config with no theme at all still loads",
    Settings.from_dict({}).theme == {} and Settings.from_dict({}).game_themes == {},
)
bent = Settings.from_dict({"theme": "blue", "game_themes": 7})
check("a theme that is not a mapping is discarded", bent.theme == {})
check("nor does the wrong type for game_themes raise", bent.game_themes == {})
check(
    "a game whose theme is not a mapping is skipped",
    Settings.from_dict({"game_themes": {"mm1": "purple", "mm2": {"bg": "#111111"}}}).game_themes
    == {"mm2": {"bg": "#111111"}},
)
cfg.settings.theme = {}
cfg.settings.game_themes.clear()
cfg.save()

# ----------------------------------------------------------------------
print("\nthe customiser")
window = MainWindow(Config.load())
window.show()
app.processEvents()
GAME, OTHER = GAMES[0].id, GAMES[1].id

window._show(SETTINGS_KEY)
check("starts on the shipped palette", theme.current() == d)

green = palette.PRESETS["Racing green"]
window.theme_editor._use_preset(green)
app.processEvents()
check("a preset is applied at once", theme.current() == green)
check("and saved", palette.Palette.from_dict(window.config.settings.theme) == green)
check(
    "and reaches the stylesheet",
    green.bg in window.styleSheet(),
    "the themed sheet goes on the window — on the application it costs ~1.4s",
)
check("the tick is repainted for the new accent", theme.ON_ACCENT == green.on_accent)

before = theme.current()
window.theme_editor._seed_picked("accent", "#FF0066")
app.processEvents()
check("the accent moves on its own", theme.current().accent == "#FF0066")
check(
    "an accent change leaves the surfaces alone",
    (theme.current().bg, theme.current().surface) == (before.bg, before.surface),
)

window.theme_editor._field_picked("hover", "#123456")
window.theme_editor._seed_picked("bg", "#201020")
app.processEvents()
check("a hand-set colour survives a re-derive", theme.current().hover == "#123456")
check("everything else re-derived", theme.current().surface != before.surface)

# ----------------------------------------------------------------------
print("\nper-game themes")
window._load_theme_scope(GAME)
check("a game starts out inheriting", GAME not in window.config.settings.game_themes)
purple = palette.PRESETS["Deep purple"]
window.theme_editor._use_preset(purple)
app.processEvents()
check("giving it colours stops the inheriting", window.config.settings.game_themes.get(GAME) is not None)
check(
    "the global theme is untouched",
    palette.Palette.from_dict(window.config.settings.theme) != purple,
)

window._show(GAME)
app.processEvents()
check("opening the game wears its theme", theme.current() == purple)

# Picking a scope in the combo has to go through the window, which is the
# only thing that knows what a scope resolves to.
window._show(SETTINGS_KEY)
window.theme_editor.scope_box.setCurrentIndex(
    window.theme_editor.scope_box.findData(GAME)
)
app.processEvents()
check("choosing a scope previews it", theme.current() == purple)
check("and the editor is showing that scope", window.theme_editor.scope() == GAME)
window._show(LIBRARY_KEY)
app.processEvents()
window._show(SETTINGS_KEY)
app.processEvents()
check(
    "coming back to Settings still previews the chosen scope",
    theme.current() == purple,
    "the wells would be describing a palette the window is not wearing",
)
window.theme_editor.scope_box.setCurrentIndex(0)
app.processEvents()
window._show(LIBRARY_KEY)
app.processEvents()
check(
    "leaving it puts the global theme back",
    theme.current() == palette.Palette.from_dict(window.config.settings.theme),
)
window._show(OTHER)
app.processEvents()
check(
    "a game without one of its own uses the global theme",
    theme.current() == palette.Palette.from_dict(window.config.settings.theme),
)

# ----------------------------------------------------------------------
print("\nswitching cost")
window._show(LIBRARY_KEY)
start = time.perf_counter()
for _ in range(6):
    window._show(LIBRARY_KEY)
    window._show(OTHER)
plain = (time.perf_counter() - start) / 12 * 1000
start = time.perf_counter()
for _ in range(4):
    window._show(LIBRARY_KEY)
    window._show(GAME)
tinted = (time.perf_counter() - start) / 8 * 1000
print(f"  (no per-game theme {plain:.1f}ms/switch, with one {tinted:.1f}ms/switch)")
check(
    "a switch between untinted pages costs nothing extra",
    plain < 250,
    f"{plain:.1f}ms — the guard in _apply_theme_for is not holding",
)
check("a switch that does restyle is still quick", tinted < 1500, f"{tinted:.1f}ms")

# ----------------------------------------------------------------------
print("\nreset")
window._load_theme_scope(GAME)
window.theme_editor._reset()
app.processEvents()
check("a game goes back to inheriting", GAME not in window.config.settings.game_themes)
window._load_theme_scope("")
window.theme_editor._reset()
app.processEvents()
check("the global reset clears what was saved", window.config.settings.theme == {})
check("and puts the shipped palette back", theme.current() == d)

# ----------------------------------------------------------------------
print("\nnone of it hangs")
# Every page built, which is when the tree is big enough for a repolish to
# be felt. This is the state a launcher is in after a few minutes of use.
for key in [g.id for g in GAMES] + [LIBRARY_KEY, NEWS_KEY, RECORDS_KEY, CHAT_KEY]:
    window._show(key)
window._show(LIBRARY_KEY)
app.processEvents()
print(f"  ({len(window._pages)} pages, {len(app.allWidgets())} widgets)")


def worst(fn, runs=3):
    best = 1e9
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        best = min(best, (time.perf_counter() - start) * 1000)
        app.processEvents()
    return best


into_settings = worst(lambda: (window._show(LIBRARY_KEY), window._show(SETTINGS_KEY)))
print(f"  (opening Settings {into_settings:.1f}ms)")
check(
    "opening Settings does not restyle anything",
    into_settings < 120,
    f"{into_settings:.1f}ms — the guard in _set_palette is not holding",
)

flip = [palette.PRESETS["Carbon"], palette.PRESETS["Slate"]]


def swap():
    flip.reverse()
    window._set_palette(flip[0])


picked = worst(swap)
print(f"  (changing a colour {picked:.1f}ms)")
check(
    "changing a colour stays responsive",
    picked < 600,
    f"{picked:.1f}ms — styling the application instead of the window costs ~1.4s here",
)

print("\na page not on screen catches up when it is opened")


class Spy(QWidget):
    """Stands in for a page, and counts what is done to it.

    A real GamePage cannot be built here — with no game installed the window
    shows a SetupPage instead, which has no accent sheet to look at. What
    matters is the bookkeeping, and that is the same either way.
    """

    def __init__(self):
        super().__init__()
        self.restyled = 0
        self.refreshed = 0

    def restyle(self):
        self.restyled += 1

    def refresh(self):
        self.refreshed += 1


spy = Spy()
old = window._pages[GAME]
window.stack.removeWidget(old)
window._pages[GAME] = spy
window.stack.addWidget(spy)

window._show(LIBRARY_KEY)
app.processEvents()
before = (spy.restyled, spy.refreshed)
window._set_palette(palette.PRESETS["Deep purple"])
app.processEvents()
check(
    "a page nobody is looking at is marked, not redone",
    GAME in window._stale_pages and LIBRARY_KEY not in window._stale_pages,
    str(sorted(window._stale_pages)),
)
check(
    "and it is genuinely left alone at that moment",
    (spy.restyled, spy.refreshed) == before,
    "redoing every page here was 157ms on every colour picked",
)
window._show(GAME)
app.processEvents()
check("opening it clears the mark", GAME not in window._stale_pages)
check(
    "and puts it right",
    spy.restyled == before[0] + 1 and spy.refreshed == before[1] + 1,
    f"{(spy.restyled, spy.refreshed)} from {before}",
)
window._show(LIBRARY_KEY)
window._show(GAME)
app.processEvents()
check(
    "opening it again costs nothing further",
    spy.restyled == before[0] + 1,
    "a page that is already current should not be restyled on every visit",
)

window.stack.removeWidget(spy)
window._pages[GAME] = old
window.stack.addWidget(old)

print("\ndialogs follow the window's theme")
from PySide6.QtWidgets import QMessageBox  # noqa: E402

window._set_palette(palette.PRESETS["Daylight"])
app.processEvents()
box = QMessageBox(window)
box.setText("styled?")
box.show()
app.processEvents()
seen = box.palette().color(box.backgroundRole()).name().upper()
check(
    "a dialog parented to the window is themed with it",
    seen == palette.PRESETS["Daylight"].bg,
    f"{seen} is not {palette.PRESETS['Daylight'].bg} — the sheet is on the window, "
    "so anything parented outside it would be missed",
)
box.close()
window._set_palette(palette.DEFAULT)
app.processEvents()

print("\nthe checkbox tick is really redrawn, not served from a cache")
# The glyphs are rewritten to the same four paths every time, and the
# stylesheet points at them by path — so a cached image would leave the tick
# in the old colour with nothing to show for the repaint.
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QCheckBox  # noqa: E402

probe = QCheckBox("ticked", window)
probe.setChecked(True)
probe.resize(160, 24)
probe.show()


def tick_ink() -> str:
    """The colour of the tick, read off the rendered indicator.

    Cropped to the 17px indicator: anything wider picks up the label and the
    unpainted margin beside it, which are lighter than either ink and would
    decide the answer on their own.
    """
    image = probe.grab().toImage()
    accent = QColor(theme.ACCENT)
    counts = {palette.ON_ACCENT_DARK: 0, palette.ON_ACCENT_LIGHT: 0}
    for y in range(2, min(17, image.height())):
        for x in range(2, min(16, image.width())):
            pixel = QColor(image.pixel(x, y))
            near_accent = (
                abs(pixel.red() - accent.red())
                + abs(pixel.green() - accent.green())
                + abs(pixel.blue() - accent.blue())
            ) < 40
            if near_accent:
                continue  # the indicator's own fill
            for ink in counts:
                target = QColor(ink)
                if (
                    abs(pixel.red() - target.red())
                    + abs(pixel.green() - target.green())
                    + abs(pixel.blue() - target.blue())
                ) < 40:
                    counts[ink] += 1
    return max(counts, key=counts.get) if any(counts.values()) else ""


window._set_palette(palette.DEFAULT)
app.processEvents()
check(
    "on the stock orange the tick is dark",
    tick_ink() == palette.ON_ACCENT_DARK,
    tick_ink(),
)
window._set_palette(palette.DEFAULT.with_accent("#241C5A"))
app.processEvents()
check(
    "on a dark accent it comes back light",
    tick_ink() == palette.ON_ACCENT_LIGHT,
    f"{tick_ink()} — the tick PNG was not reloaded after being rewritten",
)
probe.deleteLater()
window._set_palette(palette.DEFAULT)
app.processEvents()

print("\nthe Settings page fits the smallest window")
window.resize(940, 620)
window._show(SETTINGS_KEY)
window.theme_editor.toggle.setChecked(True)
for _ in range(8):
    app.processEvents()
area = window._pages[SETTINGS_KEY]
check(
    "the theme card fits with every colour on show",
    window.theme_editor.minimumSizeHint().width() <= area.viewport().width(),
    f"{window.theme_editor.minimumSizeHint().width()} > {area.viewport().width()}",
)

window.close()

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all theme checks passed")
