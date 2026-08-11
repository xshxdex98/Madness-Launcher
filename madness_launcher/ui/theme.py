"""Visual language for the launcher.

One palette, one accent that changes per game. Surfaces are separated by
lightness and a hairline border rather than shadows, which keeps the window
flat and readable at any DPI.

The palette itself lives in palette.py as a value. This module holds whichever
one is currently on screen, unpacked into module-level names because that is
how the rest of the interface reads it — `theme.BG` in an f-string, a hundred
times over. Rebinding those names in `apply()` keeps every one of those reads
working while still allowing the colours to change at runtime; the only rule
is that a colour must be read inside a function, never captured at import.
"""

from __future__ import annotations

from .palette import Palette  # noqa: F401  (re-exported for convenience)
from .palette import DEFAULT, darken, lighten, mix

_active: Palette = DEFAULT

BG = DEFAULT.bg
SURFACE = DEFAULT.surface
ELEVATED = DEFAULT.elevated
HOVER = DEFAULT.hover
BORDER = DEFAULT.border
BORDER_STRONG = DEFAULT.border_strong
TEXT = DEFAULT.text
MUTED = DEFAULT.muted
FAINT = DEFAULT.faint
GOOD = DEFAULT.good
WARN = DEFAULT.warn
BAD = DEFAULT.bad

# The accent the palette was saved with. A game page overrides it with its own
# on the way past, so this is what everything outside a game page uses.
ACCENT = DEFAULT.accent
# Text drawn on top of the accent, picked for contrast against it.
ON_ACCENT = DEFAULT.on_accent

# The colours the launcher ships with, for a Reset button to return to.
DEFAULT_ACCENT = DEFAULT.accent

# Body text stays on the system UI font for legibility at small sizes.
FONT = "Segoe UI"
# Display face for headings. Replaced with the game's own Gill Sans when a
# configured install ships it — see ui/fonts.py.
DISPLAY_FONT = "Segoe UI"


def set_display_font(family: str) -> None:
    global DISPLAY_FONT
    DISPLAY_FONT = family


def current() -> Palette:
    """The palette on screen right now."""
    return _active


def apply(p: Palette) -> None:
    """Make a palette the current one.

    Only rebinds the names. Restyling the application, and repainting the
    glyphs and the wordmark that bake colours in, is the caller's job — those
    are expensive and the caller knows whether anything is on screen yet.
    """
    global _active, BG, SURFACE, ELEVATED, HOVER, BORDER, BORDER_STRONG
    global TEXT, MUTED, FAINT, GOOD, WARN, BAD, ACCENT, ON_ACCENT
    _active = p
    BG = p.bg
    SURFACE = p.surface
    ELEVATED = p.elevated
    HOVER = p.hover
    BORDER = p.border
    BORDER_STRONG = p.border_strong
    TEXT = p.text
    MUTED = p.muted
    FAINT = p.faint
    GOOD = p.good
    WARN = p.warn
    BAD = p.bad
    ACCENT = p.accent
    ON_ACCENT = p.on_accent


def restyle(root, p: Palette | None = None) -> None:
    """Put a palette on screen, by styling `root` and everything under it.

    The glyphs have to be repainted before the stylesheet is rebuilt, because
    the stylesheet points at them by path: the tick is drawn to contrast with
    the accent and the arrows in the muted text colour, so a cached set is
    stale the moment either moves.

    Pass the QApplication once at startup, while the tree is still small.
    After that pass the main window, and mind the difference — it is worth
    about a second. Setting a stylesheet on the application does global work
    on every widget that exists, and measured on a launcher with all six game
    pages built that came to 1.4s against 207ms for the same sheet on the
    window. It is not the sheet: the four-line `*` block on its own costs
    three quarters of a second the application way.

    Styling the window instead reaches everything that is on screen, and
    every dialog too, since all of them are parented into it — a dialog
    inherits its parent's sheet. The application-level sheet set at startup
    stays underneath as the floor for anything that is not.
    """
    from . import icons

    if p is not None:
        apply(p)
    icons.invalidate()
    set_icons(icons.ensure_icons())
    root.setStyleSheet(stylesheet())


def _mix(hex_color: str, other: str, amount: float) -> str:
    """Blend two #rrggbb colours; amount 0 keeps the first, 1 gives the second."""
    return mix(hex_color, other, amount)


def on_accent(accent: str) -> str:
    """Text to draw on top of a given accent, whichever of the two reads."""
    return DEFAULT.with_accent(accent).on_accent


# Paths to the painted glyphs, installed by ui.icons at startup. Empty until
# then, in which case the affected sub-controls fall back to Qt's own drawing.
_ICONS: dict[str, str] = {}


def set_icons(icons: dict[str, str]) -> None:
    global _ICONS
    _ICONS = dict(icons)


def _image(name: str) -> str:
    """A stylesheet `image:` declaration, or nothing if the glyph is missing."""
    path = _ICONS.get(name)
    return f'image: url("{path}");' if path else ""


def accent_brush():
    """The accent as a QBrush, for painting a row of a widget directly.

    Item views are not reachable from the stylesheet per-row, so the one
    place that needs to tint a single line does it in code.
    """
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(ACCENT))


def accent_rules(accent: str) -> str:
    """Just the rules that depend on the accent colour.

    Applied to one game's page rather than to the whole application. Setting a
    stylesheet on QApplication repolishes every widget in the tree, which with a
    few hundred mod rows loaded costs well over a second — far too slow to do on
    every click in the sidebar. Scoping it to the page that actually uses the
    accent makes switching games instant.
    """
    ink = on_accent(accent)
    accent_hover = lighten(accent, 0.12)
    accent_press = darken(accent, 0.12)
    accent_soft = _mix(accent, BG, 0.78)
    check_img = _image("check")

    return f"""
QPushButton#Primary {{
    background: {accent};
    border: 1px solid {accent};
    color: {ink};
    font-weight: 700;
}}
QPushButton#Primary:hover {{
    background: {accent_hover};
    border-color: {accent_hover};
}}
QPushButton#Primary:pressed {{ background: {accent_press}; }}
QPushButton#Primary:disabled {{
    background: {ELEVATED};
    border-color: {BORDER};
    color: {FAINT};
}}

QPushButton#PlayButton {{
    font-family: "{DISPLAY_FONT}", "{FONT}", sans-serif;
    background: {accent};
    border: none;
    border-radius: 9px;
    color: {ink};
    font-size: 17px;
    font-weight: 700;
    padding: 12px 44px;
    letter-spacing: 2px;
}}
QPushButton#PlayButton:hover {{ background: {accent_hover}; }}
QPushButton#PlayButton:pressed {{ background: {accent_press}; }}
QPushButton#PlayButton:disabled {{ background: {ELEVATED}; color: {FAINT}; }}

QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {accent};
}}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {accent};
}}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{
    selection-background-color: {accent};
    selection-color: {ink};
}}
QComboBox QAbstractItemView {{ selection-background-color: {accent_soft}; }}

QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    {check_img}
}}

QPushButton#LinkButton:hover {{ color: {accent}; }}
"""


def stylesheet(accent: str = "") -> str:
    accent = accent or ACCENT
    ink = on_accent(accent)
    accent_hover = lighten(accent, 0.12)
    accent_press = darken(accent, 0.12)
    accent_soft = _mix(accent, BG, 0.78)
    display = DISPLAY_FONT
    check_img = _image("check")
    chevron_img = _image("chevron")
    up_img = _image("up")
    down_img = _image("down")

    return f"""
* {{
    font-family: "{FONT}", "Inter", sans-serif;
    font-size: 13px;
    color: {TEXT};
}}

QWidget#Root, QMainWindow {{
    background: {BG};
}}

/* ---------- Sidebar ---------- */

QWidget#Sidebar {{
    background: {SURFACE};
    border-right: 1px solid {BORDER};
}}

QFrame#LogoArea {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
}}

QFrame#LogoArea:hover {{
    background: {HOVER};
    border-color: {BORDER_STRONG};
}}

QFrame#LogoArea[empty="true"] {{
    border: 1px dashed {BORDER_STRONG};
    min-height: 62px;
}}

QFrame#LogoArea[empty="true"] QLabel {{
    color: {FAINT};
    font-size: 12px;
}}

QFrame#LogoArea:hover QLabel {{
    color: {MUTED};
}}

QLabel#BrandMark {{
    font-family: "{display}", "{FONT}", sans-serif;
    font-size: 21px;
    font-weight: 700;
    letter-spacing: 4px;
    color: {TEXT};
}}

QLabel#BrandSub {{
    font-size: 10px;
    letter-spacing: 2px;
    color: {FAINT};
    text-transform: uppercase;
}}

QLabel#OnlineCount {{
    font-size: 11.5px;
    color: {MUTED};
}}

QFrame#SidebarRule {{
    background: {BORDER};
    border: none;
}}

QLabel#AccountName {{
    font-size: 13px;
    font-weight: 700;
    color: {TEXT};
    padding: 2px 13px 0 13px;
}}

QLabel#AccountName[unset="true"] {{
    font-weight: 500;
    color: {FAINT};
}}

QLabel#SectionLabel {{
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.4px;
    color: {FAINT};
    padding: 0 4px;
}}

/* ---------- Game entries in the sidebar ---------- */

QPushButton#GameEntry {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 9px 11px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    color: {MUTED};
}}

QPushButton#GameEntry:hover {{
    background: {HOVER};
    color: {TEXT};
}}

QPushButton#GameEntry:checked {{
    background: {ELEVATED};
    border: 1px solid {BORDER_STRONG};
    color: {TEXT};
}}

QPushButton#GameEntry:disabled {{
    color: {FAINT};
    background: transparent;
}}

/* ---------- Headings ---------- */

QLabel#PageTitle {{
    font-family: "{display}", "{FONT}", sans-serif;
    font-size: 30px;
    font-weight: 700;
    letter-spacing: 0.2px;
}}

QLabel#PageSubtitle {{
    font-size: 13px;
    color: {MUTED};
}}

QLabel#OverviewTitle {{
    font-family: "{display}", "{FONT}", sans-serif;
    font-size: 40px;
    font-weight: 700;
    letter-spacing: 0.4px;
    color: {TEXT};
}}

QLabel#OverviewTagline {{
    font-size: 15px;
    color: {MUTED};
}}

QLabel#OverviewBody {{
    font-size: 13.5px;
    line-height: 165%;
    color: {_mix(TEXT, MUTED, 0.25)};
}}

QLabel#FactKey {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.4px;
    color: {FAINT};
}}

QLabel#FactValue {{
    font-family: "{display}", "{FONT}", sans-serif;
    font-size: 14px;
    font-weight: 600;
    color: {TEXT};
}}

QLabel#CardTitle {{
    font-size: 14px;
    font-weight: 600;
}}

QLabel#Muted {{
    color: {MUTED};
}}

/* Library cards. The accent is set per-card in library_page so that switching
   games never has to replace the application stylesheet. */
QFrame#GameCard {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

QFrame#GameCard:hover {{
    background: {ELEVATED};
}}

QWidget#GameCardInfo {{
    background: transparent;
}}

QPushButton#CardPlay {{
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 5px 16px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.6px;
    color: {TEXT};
    background: {ELEVATED};
}}

/* The fill and the label both come from the card's own accent, set in
   library_page — only the border is safe to state here. */
QPushButton#CardPlay[ready="true"] {{
    border-color: transparent;
}}

QPushButton#CardPlay:hover {{
    border-color: {BORDER_STRONG};
}}

QLabel#Faint {{
    color: {FAINT};
    font-size: 12px;
}}

QLabel#GroupHeading {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.2px;
    color: {FAINT};
}}

QLabel#Mono {{
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    color: {MUTED};
}}

QTabBar::scroller {{ width: 26px; }}

QTabBar QToolButton {{
    background: {ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {MUTED};
    margin: 2px;
}}

QTabBar QToolButton:hover {{ background: {HOVER}; color: {TEXT}; }}

QTreeWidget#RecordTable {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    font-size: 13px;
}}

QTreeWidget#RecordTable::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {BORDER};
}}

QHeaderView::section {{
    background: {ELEVATED};
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {BORDER_STRONG};
    padding: 7px 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
}}

/* ---------- News ---------- */

/* Announcement body copy. A point larger than the rest of the interface: this
   is the only place in the launcher with actual prose to read. */
QLabel#NewsBody {{
    color: {_mix(TEXT, MUTED, 0.25)};
    font-size: 13px;
}}

/* The boxes an image drops into. Given the surface colour up front so a card
   does not visibly change shape when a thumbnail finishes downloading. */
QLabel#NewsThumb, QLabel#NewsImage {{
    background: {ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}

/* ---------- Cards ---------- */

QFrame#Card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

QFrame#InsetCard {{
    background: {ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QFrame#WarnCard {{
    background: {_mix(WARN, BG, 0.88)};
    border: 1px solid {_mix(WARN, BG, 0.66)};
    border-radius: 10px;
}}

QFrame#WarnCard QLabel {{
    color: {WARN};
}}

QFrame#Divider {{
    background: {BORDER};
    max-height: 1px;
    border: none;
}}

/* ---------- Buttons ---------- */

QPushButton {{
    background: {ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 7px;
    padding: 7px 15px;
    font-weight: 500;
}}

QPushButton:hover {{
    background: {HOVER};
    border-color: {MUTED};
}}

QPushButton:pressed {{
    background: {SURFACE};
}}

QPushButton:disabled {{
    color: {FAINT};
    border-color: {BORDER};
    background: {SURFACE};
}}

QPushButton#Primary {{
    background: {accent};
    border: 1px solid {accent};
    color: {ink};
    font-weight: 700;
}}

QPushButton#Primary:hover {{
    background: {accent_hover};
    border-color: {accent_hover};
}}

QPushButton#Primary:pressed {{
    background: {accent_press};
}}

QPushButton#Primary:disabled {{
    background: {ELEVATED};
    border-color: {BORDER};
    color: {FAINT};
}}

QPushButton#PlayButton {{
    font-family: "{display}", "{FONT}", sans-serif;
    background: {accent};
    border: none;
    border-radius: 9px;
    color: {ink};
    font-size: 17px;
    font-weight: 700;
    padding: 12px 44px;
    letter-spacing: 2px;
}}

QPushButton#PlayButton:hover {{
    background: {accent_hover};
}}

QPushButton#PlayButton:pressed {{
    background: {accent_press};
}}

QPushButton#PlayButton:disabled {{
    background: {ELEVATED};
    color: {FAINT};
}}

QPushButton#Ghost {{
    background: transparent;
    border: 1px solid {BORDER_STRONG};
}}

QPushButton#Ghost:hover {{
    background: {HOVER};
}}

QPushButton#Danger:hover {{
    background: {_mix(BAD, BG, 0.72)};
    border-color: {BAD};
    color: {TEXT};
}}

QPushButton#SectionToggle {{
    font-family: "{display}", "{FONT}", sans-serif;
    background: transparent;
    border: none;
    border-bottom: 1px solid {BORDER};
    border-radius: 0;
    padding: 7px 2px;
    text-align: left;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.3px;
    color: {MUTED};
}}

QPushButton#SectionToggle:hover {{
    color: {TEXT};
    border-bottom-color: {BORDER_STRONG};
}}

QPushButton#SectionToggle:checked {{
    color: {TEXT};
}}

QPushButton#LinkButton {{
    background: transparent;
    border: none;
    padding: 2px 4px;
    color: {MUTED};
    text-align: left;
}}

QPushButton#LinkButton:hover {{
    color: {accent};
}}

/* ---------- Tabs ---------- */

QTabWidget::pane {{
    border: none;
    top: 6px;
}}

QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 2px;
    margin-right: 22px;
    color: {MUTED};
    font-size: 13px;
    font-weight: 600;
}}

QTabBar::tab:hover {{
    color: {TEXT};
}}

QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {accent};
}}

/* ---------- Inputs ---------- */

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{
    background: {BG};
    border: 1px solid {BORDER_STRONG};
    border-radius: 7px;
    padding: 7px 10px;
    selection-background-color: {accent};
    selection-color: {ink};
}}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {accent};
}}

QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {FAINT};
    background: {SURFACE};
}}

QLineEdit#PathField {{
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox::down-arrow {{
    {chevron_img}
    width: 11px;
    height: 7px;
    margin-right: 8px;
}}

QComboBox QAbstractItemView {{
    background: {ELEVATED};
    border: 1px solid {BORDER_STRONG};
    border-radius: 7px;
    padding: 4px;
    outline: none;
    selection-background-color: {accent_soft};
}}

QSpinBox::up-button, QSpinBox::down-button {{
    width: 16px;
    background: {ELEVATED};
    border: none;
}}

QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: {HOVER};
}}

QSpinBox::up-arrow {{
    {up_img}
    width: 9px;
    height: 6px;
}}

QSpinBox::down-arrow {{
    {down_img}
    width: 9px;
    height: 6px;
}}

/* ---------- Checkboxes ---------- */

QCheckBox {{
    spacing: 9px;
}}

QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 5px;
    background: {BG};
}}

QCheckBox::indicator:hover {{
    border-color: {MUTED};
}}

QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    {check_img}
}}

QCheckBox:disabled {{
    color: {FAINT};
}}

/* ---------- Scrollbars ---------- */

QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 4px;
    min-height: 32px;
}}

QScrollBar::handle:vertical:hover {{
    background: {FAINT};
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}

QScrollBar::handle:horizontal {{
    background: {BORDER_STRONG};
    border-radius: 4px;
    min-width: 32px;
}}

/* ---------- Chat ---------- */

QTextBrowser#Transcript {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 12px 14px;
    font-size: 13px;
    selection-background-color: {accent};
    selection-color: {ink};
}}

QListWidget#UserList {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
    outline: none;
}}

QListWidget#UserList::item {{
    padding: 5px 8px;
    border-radius: 6px;
    color: {TEXT};
}}

QListWidget#UserList::item:hover {{
    background: {HOVER};
}}

QLineEdit#ChatInput {{
    padding: 10px 13px;
    font-size: 13px;
}}

QSplitter#ChatSplitter::handle {{
    background: transparent;
}}

/* ---------- Dialogs / misc ---------- */

QDialog {{
    background: {BG};
}}

QMessageBox {{
    background: {BG};
}}

QToolTip {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 5px 8px;
}}

QStatusBar {{
    background: {SURFACE};
    border-top: 1px solid {BORDER};
    color: {MUTED};
}}

QStatusBar::item {{
    border: none;
}}
"""
