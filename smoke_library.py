"""Checks for the default wordmark and the library home screen."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Keep every branding/config write inside a throwaway folder: these tests must
# never touch the user's own logo, artwork or saved game paths.
SANDBOX = Path(tempfile.mkdtemp(prefix="madness-library-"))
os.environ["MADNESS_LAUNCHER_HOME"] = str(SANDBOX)

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from madness_launcher import branding, paths  # noqa: E402
from madness_launcher.config import Config  # noqa: E402
from madness_launcher.games.registry import GAMES  # noqa: E402
from madness_launcher.ui import theme, wordmark  # noqa: E402
from madness_launcher.ui.library_page import CARD_WIDTH, LibraryPage  # noqa: E402
from madness_launcher.ui.main_window import (  # noqa: E402
    CHAT_KEY,
    LIBRARY_KEY,
    LOGO_MAX,
    SETTINGS_KEY,
    SIDEBAR_WIDTH,
    MainWindow,
)

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


app = QApplication.instance() or QApplication(sys.argv)
app.setStyleSheet(theme.stylesheet())

print("root:", paths.app_root())
check(
    "sandboxed away from the real data folder",
    SANDBOX in paths.app_root().parents or paths.app_root() == SANDBOX,
    str(paths.app_root()),
)

print("\ndefault wordmark")
logo = wordmark.default_logo()
check("wordmark is written to disk", logo.is_file())
pixmap = QPixmap(str(logo))
check("wordmark decodes as an image", not pixmap.isNull())
check(
    "wordmark has sensible dimensions",
    pixmap.width() >= wordmark.WIDTH and pixmap.height() >= wordmark.HEIGHT,
    f"{pixmap.width()}x{pixmap.height()}",
)
image = pixmap.toImage()
opaque = sum(
    1
    for y in range(0, image.height(), 3)
    for x in range(0, image.width(), 3)
    if QColor(image.pixelColor(x, y)).alpha() > 40
)
check("wordmark actually has ink on it", opaque > 200, f"{opaque} samples")
check("wordmark is not the user's logo", branding.stored_logo() is None)

print("\nlogo falls back and restores")
config = Config.load()
window = MainWindow(config)
check("sidebar shows a logo with no user image", window.logo.has_logo())

source = SANDBOX / "custom.png"
custom = QPixmap(64, 64)
custom.fill(QColor("#3366FF"))
custom.save(str(source), "PNG")
branding.install_logo(source)
window._refresh_logo()
check("a user logo takes over", branding.stored_logo() is not None)
check("sidebar still shows a logo", window.logo.has_logo())

branding.clear_logo()
window._refresh_logo()
check("removing the user logo restores the wordmark", window.logo.has_logo())
check("user logo really is gone", branding.stored_logo() is None)

print("\nlogo scales with the window")
# A big square image, the shape most likely to overflow its slot: it is
# limited by height rather than width, so it is the one that used to be
# painted at full size inside a frame the layout had squeezed to a sliver.
square = SANDBOX / "square.png"
big = QPixmap(512, 512)
big.fill(QColor("#3366FF"))
big.save(str(square), "PNG")
branding.install_logo(square)
window._refresh_logo()
# Shown, because Qt holds back the resize event on a hidden window and the
# sidebar sizes itself from that event.
window.show()

sizes = {}
for w, h in ((940, 620), (1120, 740), (1920, 1080)):
    window.resize(w, h)
    app.processEvents()
    sizes[(w, h)] = (window.sidebar.width(), window.logo.height())
    print(f"  ({w}x{h}: sidebar {sizes[(w, h)][0]}, logo {sizes[(w, h)][1]})")

small, mid, large = sizes.values()
check("logo grows with the window", small[1] < mid[1] < large[1])
check("sidebar widens on a large window", small[0] == mid[0] < large[0])
check(
    "sidebar never narrows past the width its labels are elided for",
    all(width >= SIDEBAR_WIDTH for width, _ in sizes.values()),
    str(sizes),
)
check(
    "logo is bounded on a huge window",
    large[1] <= LOGO_MAX,
    f"{large[1]} > {LOGO_MAX}",
)

# The actual defect: the frame kept the height the layout gave it while the
# image was painted at whatever size it liked, and spilled over the edges.
for (w, h), (_, logo_height) in sizes.items():
    window.resize(w, h)
    app.processEvents()
    drawn = window.logo._content_size(window.logo.width())[1]
    check(
        f"image fits inside its frame at {w}x{h}",
        drawn + 2 * window.logo.PAD <= window.logo.height(),
        f"{drawn}px image in a {window.logo.height()}px frame",
    )

# Squeezed to nothing on purpose: the paint path must cope rather than
# drawing over the navigation below it.
window.logo.fit(200, 0)
check("a starved slot still holds its floor", window.logo.height() >= window.logo.MIN_HEIGHT)
window.logo.setFixedHeight(12)
window.logo.grab()  # would raise or overdraw if the fit were unguarded
check("painting a slot smaller than its floor is safe", True)
window.logo.setMinimumHeight(0)
window.logo.setMaximumHeight(16777215)

tiny = SANDBOX / "tiny.png"
small_pix = QPixmap(48, 16)
small_pix.fill(QColor("#FF8800"))
small_pix.save(str(tiny), "PNG")
branding.install_logo(tiny)
window._refresh_logo()
window.resize(1920, 1080)
app.processEvents()
check(
    "a small image is not blown up past its own resolution",
    window.logo._content_size(window.logo.width())[1] <= 16,
    str(window.logo._content_size(window.logo.width())),
)

branding.clear_logo()
window._refresh_logo()
window.resize(1120, 740)
app.processEvents()

print("\nlibrary is the front door")
check("opens on the library", window.stack.currentWidget() is window._library_page())
check("library entry is checked", window.library_entry.isChecked())
library = window._library_page()
check(
    "one card per supported game",
    len(library._cards) == len(GAMES),
    f"{len(library._cards)} vs {len(GAMES)}",
)
check(
    "cards cover every game id",
    {c.game.id for c in library._cards} == {g.id for g in GAMES},
)

print("\ncard state")
library.refresh()
for card in library._cards:
    configured = config.is_configured(card.game.id)
    label = card.action.text()
    expected = {"Play", "Set up"} if configured else {"Set up"}
    check(
        f"{card.game.id}: action reads sensibly ({label})",
        label in expected,
        f"configured={configured}",
    )
check(
    "unconfigured games read as not set up",
    all(
        c.status.text() == "Not set up"
        for c in library._cards
        if not config.is_configured(c.game.id)
    ),
)
check("summary line is filled in", bool(library.summary.text().strip()))

print("\nartwork")
card = library._cards[0]
check("no artwork by default", not card.art.has_custom())
before = card.art.grab().toImage()
check("generated art paints something", before.width() > 0)

art_source = SANDBOX / "hero.png"
hero = QPixmap(400, 200)
hero.fill(QColor("#B02020"))
hero.save(str(art_source), "PNG")
branding.install_hero(art_source, card.game.id)
card.reload_art()
check("installed artwork is picked up", card.art.has_custom())
check(
    "artwork is stored per game",
    branding.stored_hero(card.game.id) is not None
    and branding.stored_hero(library._cards[1].game.id) is None,
)
branding.clear_hero(card.game.id)
card.reload_art()
check("artwork can be removed", not card.art.has_custom())

print("\nreflow")
# Resized on its own rather than inside the window: a child of a layout cannot
# be given an arbitrary width, so the in-place resize would be ignored.
probe = LibraryPage(config)
probe.show()  # Qt withholds resize events from hidden widgets.
probe.resize(CARD_WIDTH * 3 + 200, 700)
app.processEvents()
wide = probe._columns
probe.resize(CARD_WIDTH + 90, 700)
app.processEvents()
narrow = probe._columns
check("wide window uses more columns", wide > narrow, f"{wide} vs {narrow}")
check("wide window fits three across", wide >= 3, str(wide))
check("narrow window falls back to one", narrow == 1, str(narrow))
check(
    "every card is still placed after reflow",
    probe.grid.count() == len(probe._cards),
    f"{probe.grid.count()}",
)
probe.close()
probe.deleteLater()

print("\nsidebar marks and layout")
from PySide6.QtGui import QFontMetrics  # noqa: E402

from madness_launcher.ui.main_window import (  # noqa: E402
    ENTRY_TEXT_WIDTH,
    SIDEBAR_ICON,
    SIDEBAR_WIDTH,
)

for game in GAMES:
    entry = window._entries[game.id]
    check(f"{game.id}: sidebar entry has a mark", not entry.icon().isNull())
    check(
        f"{game.id}: mark is the size the layout expects",
        entry.iconSize() == QSize(SIDEBAR_ICON, SIDEBAR_ICON),
        str(entry.iconSize()),
    )
    check(
        f"{game.id}: full title is kept in the tooltip",
        game.title in entry.toolTip(),
        entry.toolTip(),
    )

# The status dot sits beside the label now, so a label wider than its budget
# would collide with it again. Asserted as "the text is the elided form" rather
# than by measuring pixels: the offscreen platform ships no fonts, so every
# glyph measures as a fallback box and raw widths mean nothing here.
metrics = QFontMetrics(window._entry_font())
wrong = [
    g.id
    for g in GAMES
    if window._entries[g.id].text()
    != " " + metrics.elidedText(g.title, Qt.ElideRight, ENTRY_TEXT_WIDTH)
]
check("every sidebar label is elided to the budget", not wrong, str(wrong))
check(
    "eliding actually bites when a title is too long",
    metrics.elidedText("x" * 200, Qt.ElideRight, ENTRY_TEXT_WIDTH) != "x" * 200,
)
check(
    "the budget fits inside the sidebar",
    ENTRY_TEXT_WIDTH + SIDEBAR_ICON + 28 + 22 + 6 + 22 <= SIDEBAR_WIDTH,
)
for key in (LIBRARY_KEY, CHAT_KEY, SETTINGS_KEY):
    check(f"{key}: nav row has a glyph", not window._entries[key].icon().isNull())

print("\ncard badges")
library.refresh()
badged = [c.game.id for c in library._cards if c.art._badge is not None]
check(
    "configured games get their icon on the card",
    len(badged) >= sum(1 for g in GAMES if config.is_configured(g.id)),
    str(badged),
)
for card in library._cards:
    check(f"{card.game.id}: card art still paints", not card.art.grab().isNull())

print("\nnavigation")
target = GAMES[-1].id
window._show(target)
check("clicking through to a game works", window.stack.currentWidget() is not library)
window._show(LIBRARY_KEY)
check("and back to the library", window.stack.currentWidget() is library)

print("\nswitching stays cheap")
import time  # noqa: E402

start = time.perf_counter()
for _ in range(6):
    window._show(LIBRARY_KEY)
    window._show(GAMES[0].id)
elapsed = (time.perf_counter() - start) / 12 * 1000
check(
    "page switch stays well under the old 1.7s stall",
    elapsed < 250,
    f"{elapsed:.1f}ms per switch",
)
print(f"  ({elapsed:.1f}ms per switch)")

window.close()

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all library checks passed")
