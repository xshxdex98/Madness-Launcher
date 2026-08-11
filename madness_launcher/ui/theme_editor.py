"""Colour pickers for the launcher's own palette.

Two tiers, because "change the colours" means different things to different
people. Three wells — background, text, accent — derive the other ten through
palette.derive, which is enough for someone who wants the launcher to be
green. Under a fold, all thirteen individually, for someone who wants the
hover state a specific shade and does not want it argued with.

The two tiers agree because only one of them is the truth: the editor holds a
whole Palette, the guided wells rewrite the derived fields, the advanced wells
overwrite single fields, and what gets saved is always the full result.

Each scope — everywhere, or one game — is edited separately, and the editor
previews whichever is selected. There is no Apply button; a colour picker with
one is a colour picker you cannot judge the result of.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import palette as pal
from . import theme
from .widgets import Card

# Fields shown in the advanced grid, in the order they read best: the accent
# first because it is what most people came for, then surfaces from the
# background up, then text from the strongest down, then the status colours.
ADVANCED = (
    "accent",
    "bg",
    "surface",
    "elevated",
    "hover",
    "border",
    "border_strong",
    "text",
    "muted",
    "faint",
    "good",
    "warn",
    "bad",
)


class ColorWell(QPushButton):
    """A swatch that opens a colour picker and reports what came back."""

    picked = Signal(str)

    def __init__(self, field: str, value: str):
        super().__init__()
        self.field = field
        self._value = pal.normalise(value)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(96, 30)
        self.clicked.connect(self._choose)
        self.set_value(self._value)

    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        self._value = pal.normalise(value, self._value)
        self.setText(self._value)
        # The swatch is the button, so the hex has to be legible on top of
        # whatever colour it names.
        ink = "#14161A" if pal.luminance(self._value) > 0.35 else "#F4F7FB"
        edge = pal.mix(self._value, ink, 0.28)
        self.setStyleSheet(
            f"QPushButton {{ background: {self._value}; color: {ink};"
            f" border: 1px solid {edge}; border-radius: 6px;"
            " font-family: 'Cascadia Mono', Consolas, monospace;"
            " font-size: 11px; font-weight: 600; padding: 0; }}"
            f"QPushButton:hover {{ border: 2px solid {ink}; }}"
        )

    def _choose(self) -> None:
        label, _ = pal.LABELS.get(self.field, (self.field, ""))
        chosen = QColorDialog.getColor(
            QColor(self._value), self, f"{label} colour"
        )
        if not chosen.isValid():
            return
        value = chosen.name().upper()
        if value != self._value:
            self.set_value(value)
            self.picked.emit(value)


def _row(field: str, well: ColorWell, *, blurb: bool = True) -> QWidget:
    label, what = pal.LABELS.get(field, (field, ""))
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    row.addWidget(well)

    text = QVBoxLayout()
    text.setSpacing(1)
    name = QLabel(label)
    name.setObjectName("CardTitle")
    # Wrapped so the label's minimum width is its longest word rather than
    # its whole text. Thirteen of these in a two-column grid otherwise push
    # the Settings page wider than the smallest window, which does not scroll
    # sideways — the right-hand column would simply be missing.
    name.setWordWrap(True)
    text.addWidget(name)
    if blurb and what:
        hint = QLabel(what)
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        text.addWidget(hint)
    row.addLayout(text, 1)
    return host


class ThemeEditor(Card):
    """The Theme card in Settings.

    Owns no state that outlives it: `load` is handed a palette, and every
    change is announced. Whoever built it decides what that means.
    """

    # (scope, palette). Scope is "" for the global theme, else a game id.
    changed = Signal(str, object)
    # A game's theme has been dropped and should go back to inheriting.
    cleared = Signal(str)
    # A different scope was chosen; the owner resolves it and calls load().
    scope_changed = Signal(str)

    def __init__(self, scopes: list[tuple[str, str]]):
        super().__init__(
            "Theme",
            "Every colour in the launcher, and a different set for each game "
            "if you want one.",
        )
        self._scope = ""
        self._palette = pal.DEFAULT
        # Fields set by hand this session. Re-derived colours do not overwrite
        # them, so picking a background does not silently undo the work of
        # anyone who went through the advanced list first.
        self._pinned: set[str] = set()
        self._loading = False

        scope_row = QHBoxLayout()
        scope_row.setSpacing(10)
        scope_label = QLabel("Applies to")
        scope_label.setObjectName("Muted")
        scope_row.addWidget(scope_label)

        self.scope_box = QComboBox()
        for key, label in scopes:
            self.scope_box.addItem(label, key)
        self.scope_box.setMinimumWidth(220)
        self.scope_box.currentIndexChanged.connect(self._scope_changed)
        scope_row.addWidget(self.scope_box)
        scope_row.addStretch(1)
        self.body.addLayout(scope_row)

        self.inherit_note = QLabel()
        self.inherit_note.setObjectName("Faint")
        self.inherit_note.setWordWrap(True)
        self.body.addWidget(self.inherit_note)

        # A row of buttons, one per preset, wanted 1085px of a settings page
        # that has 674 at the smallest window size — and the page does not
        # scroll sideways, so the right-hand ones simply were not there. A
        # combo costs one click more and always fits.
        presets = QHBoxLayout()
        presets.setSpacing(10)
        preset_label = QLabel("Start from")
        preset_label.setObjectName("Muted")
        presets.addWidget(preset_label)

        self.preset_box = QComboBox()
        self.preset_box.setMinimumWidth(220)
        self.preset_box.addItem("Choose a preset…", None)
        for name, preset in pal.PRESETS.items():
            self.preset_box.addItem(name, preset)
        self.preset_box.currentIndexChanged.connect(self._preset_chosen)
        presets.addWidget(self.preset_box)
        presets.addStretch(1)
        self.body.addLayout(presets)

        self._wells: dict[str, ColorWell] = {}

        guided = QVBoxLayout()
        guided.setSpacing(10)
        for field in pal.SEEDS:
            well = ColorWell(field, getattr(self._palette, field))
            well.picked.connect(
                lambda value, f=field: self._seed_picked(f, value)
            )
            self._wells[field] = well
            guided.addWidget(_row(field, well))
        self.body.addLayout(guided)

        self.toggle = QPushButton("EVERY COLOUR")
        self.toggle.setObjectName("SectionToggle")
        self.toggle.setCheckable(True)
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.toggled.connect(self._toggle_advanced)
        self.body.addWidget(self.toggle)

        self.advanced = QWidget()
        grid = QGridLayout(self.advanced)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(9)
        for index, field in enumerate(ADVANCED):
            # The three seeds appear in both tiers, so each tier gets its own
            # well: a widget can only have one parent, and _sync keeps the
            # pair showing the same colour. Picking here sets one field
            # outright, where picking above re-derives.
            well = ColorWell(field, getattr(self._palette, field))
            well.picked.connect(
                lambda value, f=field: self._field_picked(f, value)
            )
            self._wells[f"adv:{field}"] = well
            grid.addWidget(_row(field, well, blurb=False), index // 2, index % 2)
        self.advanced.setVisible(False)
        self.body.addWidget(self.advanced)

        self.warning = QLabel()
        self.warning.setObjectName("Faint")
        self.warning.setWordWrap(True)
        self.warning.setVisible(False)
        self.body.addWidget(self.warning)

        actions = QHBoxLayout()
        actions.setSpacing(9)
        self.reset_button = QPushButton("Reset")
        self.reset_button.setObjectName("Danger")
        self.reset_button.clicked.connect(self._reset)
        actions.addWidget(self.reset_button)
        actions.addStretch(1)
        self.body.addLayout(actions)

    # -- state -------------------------------------------------------------

    def scope(self) -> str:
        return self.scope_box.currentData() or ""

    def load(self, scope: str, p: pal.Palette, inherited: bool) -> None:
        """Show a scope's palette without announcing it back."""
        self._loading = True
        try:
            index = self.scope_box.findData(scope)
            if index >= 0:
                self.scope_box.setCurrentIndex(index)
            self._scope = scope
            self._palette = p
            self._pinned = set()
            self._sync(inherited)
        finally:
            self._loading = False

    def _sync(self, inherited: bool) -> None:
        for field in pal.SEEDS:
            self._wells[field].set_value(getattr(self._palette, field))
        for field in ADVANCED:
            self._wells[f"adv:{field}"].set_value(getattr(self._palette, field))

        if not self._scope:
            self.inherit_note.setText(
                "The launcher's own colours, and the starting point for any "
                "game that has not been given its own."
            )
            self.reset_button.setText("Reset to the shipped colours")
        elif inherited:
            self.inherit_note.setText(
                "This game follows the theme above. Pick a colour and it stops."
            )
            self.reset_button.setText("Reset")
        else:
            self.inherit_note.setText(
                "This game has its own colours, used whenever it is open."
            )
            self.reset_button.setText("Go back to following the main theme")
        self.reset_button.setEnabled(bool(self._scope) or self._palette != pal.DEFAULT)

        complaints = pal.readability(self._palette)
        self.warning.setVisible(bool(complaints))
        if complaints:
            self.warning.setText(
                "Some of this will be hard to read — "
                + " ".join(complaints)
                + " It is applied anyway; Reset puts it back."
            )
            self.warning.setStyleSheet(f"color: {theme.WARN};")

    # -- edits -------------------------------------------------------------

    def _announce(self, p: pal.Palette, inherited: bool = False) -> None:
        self._palette = p
        self._sync(inherited)
        if not self._loading:
            self.changed.emit(self._scope, p)

    def _seed_picked(self, field: str, value: str) -> None:
        if field == "accent":
            # The accent stands alone; nothing else is derived from it.
            self._announce(self._palette.with_accent(value))
            return
        seeds = {f: getattr(self._palette, f) for f in pal.SEEDS}
        seeds[field] = value
        derived = pal.derive(seeds["bg"], seeds["text"], seeds["accent"])
        # Anything set by hand survives the re-derivation.
        kept = {f: getattr(self._palette, f) for f in self._pinned}
        self._announce(replace(derived, **kept) if kept else derived)

    def _field_picked(self, field: str, value: str) -> None:
        self._pinned.add(field)
        self._announce(replace(self._palette, **{field: value}))

    def _preset_chosen(self, index: int) -> None:
        preset = self.preset_box.itemData(index)
        if preset is None or self._loading:
            return
        self._use_preset(preset)
        # Snapped back to the prompt, because a preset is something you do
        # rather than somewhere you are: the moment a well is touched
        # afterwards the palette is no longer that preset, and leaving its
        # name showing would say otherwise.
        self._loading = True
        self.preset_box.setCurrentIndex(0)
        self._loading = False

    def _use_preset(self, p: pal.Palette) -> None:
        self._pinned = set()
        self._announce(p)

    def _toggle_advanced(self, on: bool) -> None:
        self.advanced.setVisible(on)
        self.toggle.setText("EVERY COLOUR" if not on else "EVERY COLOUR  —  HIDE")

    def _reset(self) -> None:
        self._pinned = set()
        if self._scope:
            self.cleared.emit(self._scope)
            return
        self._announce(pal.DEFAULT)

    def _scope_changed(self) -> None:
        if self._loading:
            return
        # Only the owner knows what a scope resolves to — whether this game
        # has colours of its own, and what it inherits if not.
        self.scope_changed.emit(self.scope())
