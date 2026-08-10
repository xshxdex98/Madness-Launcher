"""The page shown for one configured game: play, tune, and mod it."""

from __future__ import annotations

import html
import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import launch
from ..config import Config, InstallConfig
from ..detect import _find_case_insensitive, identify_as
from ..inifile import IniFile
from ..games.base import GameDef, build_args
from . import theme
from .mods_panel import ModsPanel
from .overview_page import OverviewPage
from .widgets import Badge, Card, Divider, GroupHeading, StatusDot, scrollable

# Combo entry that opens a file dialog rather than selecting a target.
BROWSE_TARGET = "__browse__"


class GamePage(QWidget):
    """Everything for a single game. Rebuilt when the install path changes."""

    install_changed = Signal()

    def __init__(self, game: GameDef, config: Config):
        super().__init__()
        self.game = game
        self.config = config
        self.install: InstallConfig = config.install_or_new(game.id)
        self._option_widgets: dict[str, QWidget] = {}
        self._option_warnings: dict[str, QLabel] = {}
        self._ini: IniFile | None = None
        self._load_ini()

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 24)
        root.setSpacing(18)

        root.addWidget(self._build_header())

        self.tabs = QTabWidget()

        self.overview = OverviewPage(self.game, self.install.background_video)
        self.overview.video_changed.connect(self._on_video_changed)
        self.tabs.addTab(self.overview, "Overview")

        self.tabs.addTab(scrollable(self._build_play_tab()), "Play")
        self.tabs.addTab(scrollable(self._build_options_tab()), "Options")

        self.mods_panel = ModsPanel(self.game, Path(self.install.path))
        self.mods_panel.mods_changed.connect(self._persist_mods)
        mods_host = QWidget()
        mods_layout = QVBoxLayout(mods_host)
        mods_layout.setContentsMargins(0, 8, 0, 0)
        mods_layout.addWidget(self.mods_panel)
        self.tabs.addTab(mods_host, "Mods")

        root.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # The game's accent is scoped to this page. Applying it to the whole
        # application instead repolished every widget on each sidebar click.
        self.setStyleSheet(theme.accent_rules(self.game.accent))

        self.refresh()

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        text_col = QVBoxLayout()
        text_col.setSpacing(5)

        title = QLabel(self.game.title)
        title.setObjectName("PageTitle")
        text_col.addWidget(title)

        meta = QLabel(
            f"{self.game.year}  ·  {self.game.developer}  ·  {self.game.subtitle}"
        )
        meta.setObjectName("PageSubtitle")
        text_col.addWidget(meta)

        status_row = QHBoxLayout()
        status_row.setSpacing(7)
        self.status_dot = StatusDot("idle")
        status_row.addWidget(self.status_dot, 0, Qt.AlignVCenter)
        self.status_label = QLabel()
        self.status_label.setObjectName("Muted")
        status_row.addWidget(self.status_label, 0, Qt.AlignVCenter)
        status_row.addStretch(1)
        text_col.addLayout(status_row)

        layout.addLayout(text_col, 1)

        self.play_button = QPushButton("PLAY")
        self.play_button.setObjectName("PlayButton")
        self.play_button.setCursor(Qt.PointingHandCursor)
        self.play_button.clicked.connect(self._on_play)
        layout.addWidget(self.play_button, 0, Qt.AlignVCenter)

        return host

    # ------------------------------------------------------------------
    # Play tab
    # ------------------------------------------------------------------

    def _build_play_tab(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 8, 8, 8)
        layout.setSpacing(14)

        # -- a recommended build that has been removed from this copy
        self.residue_card = QFrame()
        self.residue_card.setObjectName("WarnCard")
        residue_layout = QVBoxLayout(self.residue_card)
        residue_layout.setContentsMargins(16, 14, 16, 14)
        residue_layout.setSpacing(10)

        self.residue_text = QLabel()
        self.residue_text.setWordWrap(True)
        residue_layout.addWidget(self.residue_text)

        residue_actions = QHBoxLayout()
        self.locate_button = QPushButton()
        self.locate_button.clicked.connect(self._locate_missing_target)
        residue_actions.addWidget(self.locate_button)
        residue_actions.addStretch(1)
        residue_layout.addLayout(residue_actions)

        self.residue_card.hide()
        layout.addWidget(self.residue_card)

        # -- config pointing at a folder the game no longer lives in
        self.paths_card = QFrame()
        self.paths_card.setObjectName("WarnCard")
        paths_layout = QVBoxLayout(self.paths_card)
        paths_layout.setContentsMargins(16, 14, 16, 14)
        paths_layout.setSpacing(10)

        self.paths_text = QLabel()
        self.paths_text.setWordWrap(True)
        self.paths_text.setTextFormat(Qt.RichText)
        paths_layout.addWidget(self.paths_text)

        paths_actions = QHBoxLayout()
        self.repair_button = QPushButton("Repair paths")
        self.repair_button.clicked.connect(self._repair_paths)
        paths_actions.addWidget(self.repair_button)
        paths_actions.addStretch(1)
        paths_layout.addLayout(paths_actions)

        self.paths_card.hide()
        layout.addWidget(self.paths_card)

        # -- install location
        loc = Card("Game folder", "Where the launcher will start the game from.")
        path_row = QHBoxLayout()
        path_row.setSpacing(9)
        self.path_field = QLineEdit(self.install.path)
        self.path_field.setObjectName("PathField")
        self.path_field.setReadOnly(True)
        path_row.addWidget(self.path_field, 1)

        change = QPushButton("Change…")
        change.clicked.connect(self._on_change_folder)
        path_row.addWidget(change)

        open_btn = QPushButton("Open")
        open_btn.setObjectName("Ghost")
        open_btn.clicked.connect(self._on_open_folder)
        path_row.addWidget(open_btn)
        loc.body.addLayout(path_row)

        self.detect_label = QLabel()
        self.detect_label.setWordWrap(True)
        self.detect_label.setObjectName("Faint")
        loc.body.addWidget(self.detect_label)
        layout.addWidget(loc)

        # -- executable
        exe_card = Card(
            "Executable", "Which build of the game the Play button starts."
        )
        self.target_combo = QComboBox()
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        exe_card.body.addWidget(self.target_combo)

        self.target_desc = QLabel()
        self.target_desc.setObjectName("Faint")
        self.target_desc.setWordWrap(True)
        exe_card.body.addWidget(self.target_desc)

        self.compat_note = QLabel()
        self.compat_note.setObjectName("Faint")
        self.compat_note.setWordWrap(True)
        self.compat_note.hide()
        exe_card.body.addWidget(self.compat_note)
        layout.addWidget(exe_card)

        # -- extra args + resulting command
        cmd_card = Card(
            "Command line",
            "Options from the Options tab are combined with anything you add here.",
        )
        self.extra_field = QLineEdit(self.install.extra_args)
        self.extra_field.setPlaceholderText("Additional arguments, e.g. -powerups")
        self.extra_field.textChanged.connect(self._on_extra_changed)
        cmd_card.body.addWidget(self.extra_field)

        self.command_preview = QLabel()
        self.command_preview.setObjectName("Mono")
        self.command_preview.setWordWrap(True)
        self.command_preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cmd_card.body.addWidget(self.command_preview)

        self.args_file_note = QLabel()
        self.args_file_note.setObjectName("Faint")
        self.args_file_note.setWordWrap(True)
        self.args_file_note.hide()
        cmd_card.body.addWidget(self.args_file_note)
        layout.addWidget(cmd_card)

        layout.addStretch(1)
        return host

    # ------------------------------------------------------------------
    # Options tab
    # ------------------------------------------------------------------

    def _build_options_tab(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 8, 8, 8)
        layout.setSpacing(14)

        # Warns when the selected executable ignores most of these options.
        self.options_banner = QLabel()
        self.options_banner.setWordWrap(True)
        self.options_banner.setStyleSheet(
            f"color: {theme.WARN}; background: {theme._mix(theme.WARN, theme.BG, 0.86)};"
            f" border: 1px solid {theme._mix(theme.WARN, theme.BG, 0.65)};"
            " border-radius: 8px; padding: 11px 14px;"
        )
        self.options_banner.hide()
        layout.addWidget(self.options_banner)

        # Some games genuinely have nothing to configure — Motocross Madness
        # keeps no settings file at all. Say so, rather than showing a blank tab
        # that looks like something failed to load.
        if not self.game.options:
            empty = Card("Nothing to configure here")
            message = QLabel(
                self.game.notes
                or f"{self.game.title} does not keep a settings file that the "
                   "launcher can edit."
            )
            message.setObjectName("Faint")
            message.setWordWrap(True)
            empty.body.addWidget(message)
            layout.addWidget(empty)
            layout.addStretch(1)
            return host

        for group in self.game.option_groups():
            card = Card(group)
            specs = [o for o in self.game.options if o.group == group]
            for i, spec in enumerate(specs):
                if i:
                    card.body.addWidget(Divider())
                card.body.addWidget(self._build_option_row(spec))
            layout.addWidget(card)

        reset = QPushButton("Reset all options to defaults")
        reset.setObjectName("Ghost")
        reset.clicked.connect(self._on_reset_options)
        layout.addWidget(reset, 0, Qt.AlignLeft)

        layout.addStretch(1)
        return host

    # ------------------------------------------------------------------
    # INI-backed options
    # ------------------------------------------------------------------

    def _ini_path(self) -> Path | None:
        if not self.game.options_file or not self.install.path:
            return None
        found = _find_case_insensitive(Path(self.install.path), self.game.options_file)
        return found

    def _load_ini(self) -> None:
        """Read the game's config file, if it has one and it is present."""
        self._ini = None
        path = self._ini_path()
        if path is None:
            return
        try:
            self._ini = IniFile.load(path)
        except OSError:
            self._ini = None

    def _option_value(self, spec):
        """Current value of an option, from wherever that option lives."""
        if not spec.is_ini:
            return self.install.options.get(spec.key, spec.default)
        if self._ini is None:
            return spec.default
        key = spec.file_key()
        if spec.kind == "bool":
            raw = self._ini.get(spec.ini_section, key)
            if raw is None:
                return spec.default
            return raw.strip() not in ("0", "", "false", "False")

        # Not every setting is a number. Monster Truck Madness 2 stores its
        # audio configuration as words — SpeakerCfg=STEREO, UseModMusic=YEP —
        # so a spec whose default is a string is read back as one.
        if isinstance(spec.default, str):
            raw = self._ini.get(spec.ini_section, key)
            return spec.default if raw is None else raw.strip()

        if spec.decimals:
            return self._ini.get_float(spec.ini_section, key, float(spec.default))
        return self._ini.get_int(spec.ini_section, key, int(spec.default))

    def _write_ini_option(self, spec, value) -> None:
        if self._ini is None:
            return
        try:
            self._ini.set(spec.ini_section, spec.file_key(), value)
            self._ini.save()
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Could not save setting",
                f"{self.game.options_file} could not be written:\n\n{exc}\n\n"
                "If the game is running, close it and try again.",
            )

    def _build_option_row(self, spec) -> QWidget:
        value = self._option_value(spec)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(spec.label)
        text_col.addWidget(name)
        hint_parts = [spec.help] if spec.help else []
        hint_parts.append(
            f"{spec.ini_section} · {spec.file_key()}"
            if spec.is_ini
            else f"-{spec.key}"
        )
        hint = QLabel("  ·  ".join(hint_parts))
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        text_col.addWidget(hint)

        # Filled in by _update_option_warnings when the engine's argument file
        # forces this flag on.
        forced = QLabel()
        forced.setWordWrap(True)
        forced.setStyleSheet(f"color: {theme.WARN};")
        forced.hide()
        text_col.addWidget(forced)
        self._option_warnings[spec.key] = forced

        layout.addLayout(text_col, 1)

        if spec.kind == "bool":
            control = QCheckBox()
            control.setChecked(bool(value))
            control.toggled.connect(
                lambda checked, k=spec.key: self._set_option(k, checked)
            )
        elif spec.kind == "choice":
            control = QComboBox()
            for label, val in spec.choices:
                control.addItem(label, val)
            idx = control.findData(value)
            control.setCurrentIndex(idx if idx >= 0 else 0)
            control.setMinimumWidth(190)
            control.currentIndexChanged.connect(
                lambda _i, k=spec.key, c=control: self._set_option(k, c.currentData())
            )
        else:
            control = QSpinBox()
            control.setRange(spec.minimum, spec.maximum)
            control.setValue(int(value))
            control.setMinimumWidth(90)
            control.valueChanged.connect(
                lambda v, k=spec.key: self._set_option(k, v)
            )

        self._option_widgets[spec.key] = control
        layout.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        return row

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-run detection and update everything that depends on it."""
        root = Path(self.install.path) if self.install.path else None
        result = identify_as(root, self.game) if root else None
        if result is not None and self.install.custom_exe:
            # Only counts as a launch target if it is actually still there.
            if (result.root / self.install.custom_exe).is_file():
                result.custom_exe = self.install.custom_exe

        self.path_field.setText(self.install.path or "Not set")

        if result is None:
            self.status_dot.set_state("bad")
            self.status_label.setText("Game folder not found")
            self.detect_label.setText(
                "The saved folder no longer contains Midtown Madness. "
                "Choose the folder again."
                if self.install.path
                else "No folder selected yet."
            )
            self.detect_label.setStyleSheet(f"color: {theme.BAD};")
            self.play_button.setEnabled(False)
        else:
            found = ", ".join(t.label for t in result.found_targets) or "none"
            if result.ok:
                # Complete, but amber rather than green when the build this
                # game is best played on has been removed from the copy.
                gone = result.absent_with_residue
                self.status_dot.set_state("warn" if gone else "good")
                self.detect_label.setStyleSheet(f"color: {theme.FAINT};")
                self.detect_label.setText(f"Detected: {found}.")
            elif result.playable:
                self.status_dot.set_state("warn")
                self.detect_label.setStyleSheet(f"color: {theme.WARN};")
                self.detect_label.setText(
                    f"Detected: {found}. Missing data files: "
                    f"{', '.join(result.missing_data)}. The game may not start."
                )
            else:
                self.status_dot.set_state("bad")
                self.detect_label.setStyleSheet(f"color: {theme.BAD};")
                self.detect_label.setText(
                    "No runnable executable found in that folder."
                )
            self.status_label.setText(result.summary())
            self.play_button.setEnabled(result.playable)

        self._update_residue_card(result)
        self._update_paths_card()
        self._reload_targets(result)
        self._update_command_preview()
        self._update_args_file_note()
        self._update_option_warnings()
        self._update_options_banner()
        self._update_compat_note()

    def _update_compat_note(self) -> None:
        """Explain Windows compatibility settings applied to this executable."""
        if not self.install.path:
            self.compat_note.hide()
            return
        try:
            plan = launch.build_plan(
                self.game, Path(self.install.path), self.install.target,
                self.install.options, "", self.install.custom_exe,
            )
        except launch.LaunchError:
            self.compat_note.hide()
            return

        layers = launch.compatibility_layers(plan.executable)
        if not layers:
            self.compat_note.hide()
            return

        parts = [f"Windows compatibility settings: {', '.join(layers)}."]
        if "RUNASADMIN" in layers:
            parts.append(
                "Because it is set to run as administrator, Windows will ask "
                "for permission each time. Clear that checkbox in the "
                "executable's Properties to stop the prompt."
            )
        self.compat_note.setText(" ".join(parts))
        self.compat_note.setStyleSheet(
            f"color: {theme.WARN};" if "RUNASADMIN" in layers else ""
        )
        self.compat_note.show()

    def _reload_targets(self, result) -> None:
        self.target_combo.blockSignals(True)
        self.target_combo.clear()

        available = result.found_targets if result else []
        for target in self.game.exe_targets:
            present = any(t.id == target.id for t in available)
            label = target.label if present else f"{target.label}  (not found)"
            self.target_combo.addItem(label, target.id)
            if not present:
                idx = self.target_combo.count() - 1
                self.target_combo.model().item(idx).setEnabled(False)

        # A repack may ship the executable under a name we do not know, so the
        # user's own choice sits alongside the known ones.
        if self.install.custom_exe:
            self.target_combo.addItem(
                f"{self.install.custom_exe}  (chosen)", launch.CUSTOM_TARGET
            )
        self.target_combo.addItem("Choose another executable…", BROWSE_TARGET)

        wanted = self.install.target
        if not wanted or self.target_combo.findData(wanted) < 0:
            wanted = available[0].id if available else self.game.default_target().id
        idx = self.target_combo.findData(wanted)
        if idx >= 0 and wanted not in (launch.CUSTOM_TARGET, BROWSE_TARGET):
            # Never leave a missing executable selected.
            if not any(t.id == wanted for t in available) and available:
                idx = self.target_combo.findData(available[0].id)
        self.target_combo.setCurrentIndex(max(idx, 0))
        self.target_combo.blockSignals(False)

        self.install.target = self.target_combo.currentData() or ""
        self._update_target_desc()

    def _update_target_desc(self) -> None:
        if self.install.target == launch.CUSTOM_TARGET:
            self.target_desc.setText(
                f"Launching {self.install.custom_exe}, chosen by hand. The "
                "launcher cannot tell which options this build supports; any it "
                "does not recognise are ignored."
            )
            return
        target = self.game.target(self.install.target)
        self.target_desc.setText(target.description if target else "")

    def _update_command_preview(self) -> None:
        args = build_args(self.game, self.install.options, self.extra_field.text())
        if self.install.target == launch.CUSTOM_TARGET:
            name = self.install.custom_exe or "?"
        else:
            target = self.game.target(self.install.target) or self.game.default_target()
            name = target.filename
        rendered = " ".join(args) if args else "(no arguments — engine defaults)"
        self.command_preview.setText(f"{name} {rendered}")

    def _update_args_file_note(self) -> None:
        if not self.install.path:
            self.args_file_note.hide()
            return
        contents = launch.read_args_file(self.game, Path(self.install.path))
        if not contents:
            self.args_file_note.hide()
            return

        forced = launch.forced_on_flags(self.game, Path(self.install.path))
        text = (
            f"{self.game.args_file} in the game folder is read first, then "
            "these arguments — so the settings here win where they overlap.\n"
            f"{contents}"
        )
        if forced:
            text += (
                "\n\nExcept these, which have no 'off' switch in the engine and "
                "so stay on no matter what is set here: "
                + ", ".join(f"-{k}" for k in forced)
            )
        self.args_file_note.setText(text)
        self.args_file_note.setStyleSheet(
            f"color: {theme.WARN if forced else theme.FAINT};"
        )
        self.args_file_note.show()

    def _update_residue_card(self, result) -> None:
        """Explain a recommended build that has been deleted from this copy."""
        self._missing_target = None
        if result is None or not result.absent_with_residue:
            self.residue_card.hide()
            return

        target = result.absent_with_residue[0]
        self._missing_target = target
        evidence = ", ".join(result.residue_evidence(target))
        fallback = result.found_targets[0].label if result.found_targets else None

        text = (
            f"<b>{target.filename} is not in this folder</b>, but {evidence} "
            f"{'are' if evidence.count(',') else 'is'} still here — so this copy "
            f"had {target.label} and it was removed."
        )
        if fallback:
            text += (
                f"<br><br>Falling back to <b>{fallback}</b>. Most options on the "
                "Options tab will not apply to that build."
            )
        else:
            text += "<br><br>There is no other executable here to fall back on."
        self.residue_text.setTextFormat(Qt.RichText)
        self.residue_text.setText(text)
        self.locate_button.setText(f"Locate {target.filename}…")
        self.residue_card.show()

    def _locate_missing_target(self) -> None:
        target = getattr(self, "_missing_target", None)
        if target is None:
            return
        root = Path(self.install.path)
        chosen, _ = QFileDialog.getOpenFileName(
            self, f"Locate {target.filename}", "", f"{target.filename};;Executables (*.exe)"
        )
        if not chosen:
            return

        picked = Path(chosen)
        destination = root / target.filename
        try:
            already_inside = picked.resolve().parent == root.resolve()
        except OSError:
            already_inside = False

        if not already_inside:
            # It has to sit beside the game data: Windows resolves an exe's
            # DLLs (SDL3 here) next to the executable, not in the working dir.
            if QMessageBox.question(
                self,
                "Copy into the game folder?",
                f"{picked.name} is outside this game folder.\n\n"
                f"{target.label} loads its libraries from beside the executable, "
                "so it has to be copied in to work.\n\n"
                f"Copy it to {destination}?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            ) != QMessageBox.Yes:
                return
            try:
                shutil.copy2(picked, destination)
            except OSError as exc:
                QMessageBox.warning(self, "Could not copy", str(exc))
                return

        self.install.target = target.id
        self._save()
        self.refresh()
        self.install_changed.emit()
        window = self.window()
        if hasattr(window, "flash_status"):
            window.flash_status(f"{target.filename} is now in place")

    def _stale_paths(self) -> list:
        """Path settings pointing somewhere that no longer exists."""
        if self._ini is None or not self.install.path:
            return []
        stale = []
        for setting in self.game.path_settings:
            current = (self._ini.get(setting.section, setting.key) or "").strip()
            # Blank is not broken. Monster Truck Madness clears CDROMPath itself
            # on a hard-disk install, and "repairing" that to a real folder would
            # be inventing a setting the game deliberately left empty.
            if not current:
                continue
            if not Path(current).exists():
                stale.append((setting, current))
        return stale

    def _update_paths_card(self) -> None:
        stale = self._stale_paths()
        if not stale:
            self.paths_card.hide()
            return

        rows = "<br>".join(
            f"&nbsp;&nbsp;<b>{s.label or s.key}</b> → {html.escape(value)}"
            for s, value in stale
        )
        self.paths_text.setText(
            f"<b>{self.game.options_file} points at a folder that is not "
            f"there.</b> This copy of the game has been moved since it was "
            f"installed, and these settings still name the old location:"
            f"<br><br>{rows}<br><br>"
            "The game reads its own files through these, so it will fail to "
            "load — Monster Truck Madness reports “Unable to open cockpit "
            "file”. Repairing points them at this folder."
        )
        self.paths_card.show()

    def _repair_paths(self) -> None:
        stale = self._stale_paths()
        if not stale or self._ini is None:
            return
        root = Path(self.install.path)
        try:
            for setting, _ in stale:
                self._ini.set(setting.section, setting.key, setting.expected(root))
            self._ini.save()
        except OSError as exc:
            QMessageBox.warning(self, "Could not repair", str(exc))
            return
        self._load_ini()
        self.refresh()
        window = self.window()
        if hasattr(window, "flash_status"):
            window.flash_status(
                f"Repaired {len(stale)} path(s) in {self.game.options_file}"
            )

    def _update_options_banner(self) -> None:
        # A config file the options depend on, which is not there.
        if self.game.options_file and self._ini is None and self.install.path:
            self.options_banner.setText(
                self.game.options_file_hint
                or f"{self.game.options_file} was not found in this folder."
            )
            self.options_banner.show()
            return

        if self.install.target == launch.CUSTOM_TARGET:
            # An unknown build: we cannot say which options it honours, and
            # guessing would be worse than the note already on the Play tab.
            self.options_banner.hide()
            return
        target = self.game.target(self.install.target)
        if target and not target.options_apply and target.options_caveat:
            self.options_banner.setText(
                f"Launching with {target.label}. {target.options_caveat}"
            )
            self.options_banner.show()
        else:
            self.options_banner.hide()

    def _update_option_warnings(self) -> None:
        forced = set(
            launch.forced_on_flags(self.game, Path(self.install.path))
            if self.install.path
            else []
        )
        for key, label in self._option_warnings.items():
            spec = self.game.option(key)
            if key in forced:
                label.setText(
                    f"Forced on by {self.game.args_file}; this flag cannot be "
                    "switched off from the command line."
                )
                label.show()
                continue

            # A value the game does not support — often written by the game
            # itself, or left behind by another tool.
            if spec is not None and spec.valid_values:
                current = self._option_value(spec)
                if current not in spec.valid_values:
                    label.setText(
                        f"Currently set to {current}, which is not supported. "
                        + (spec.invalid_help or "")
                    )
                    label.show()
                    continue
            label.hide()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        self.config.installs[self.game.id] = self.install
        try:
            self.config.save()
        except OSError as exc:
            QMessageBox.warning(
                self, "Could not save settings", f"{exc}"
            )

    def _set_option(self, key: str, value) -> None:
        spec = self.game.option(key)
        if spec is not None and spec.is_ini:
            self._write_ini_option(spec, value)
            return
        self.install.options[key] = value
        self._update_command_preview()
        self._save()

    def _on_extra_changed(self, text: str) -> None:
        self.install.extra_args = text
        self._update_command_preview()
        self._save()

    def _on_target_changed(self, _index: int) -> None:
        data = self.target_combo.currentData()
        if not data:
            return
        if data == BROWSE_TARGET:
            self._choose_custom_exe()
            return
        self.install.target = data
        self._update_target_desc()
        self._update_command_preview()
        self._update_options_banner()
        self._save()

    def _choose_custom_exe(self) -> None:
        """Let the user nominate an executable a repack renamed."""
        root = Path(self.install.path)
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Select the game executable", str(root), "Executables (*.exe)"
        )
        if not chosen:
            self.refresh()  # Put the combo back on the previous selection.
            return

        picked = Path(chosen)
        try:
            relative = picked.resolve().relative_to(root.resolve())
        except ValueError:
            QMessageBox.warning(
                self,
                "Outside the game folder",
                f"{picked.name} is not inside {root}.\n\n"
                "The executable has to live in the game folder, since that is "
                "the working directory it will be started from.",
            )
            self.refresh()
            return

        self.install.custom_exe = str(relative)
        self.install.target = launch.CUSTOM_TARGET
        self._save()
        self.refresh()
        self.install_changed.emit()

    def _on_video_changed(self, path: str) -> None:
        self.install.background_video = path
        self._save()

    def _on_tab_changed(self, index: int) -> None:
        # Only decode video while the Overview is actually being looked at.
        self.overview.set_active(self.tabs.widget(index) is self.overview)
        if self.tabs.tabText(index) == "Mods":
            self.mods_panel.ensure_loaded()

    def release(self) -> None:
        """Called before this page is destroyed, to shut the video down."""
        self.overview.release()

    def _persist_mods(self) -> None:
        self.install.enabled_mods = self.mods_panel.enabled_slugs()
        self._save()

    def _on_reset_options(self) -> None:
        if QMessageBox.question(
            self,
            "Reset options",
            "Return every option on this tab to its default?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        self.install.options.clear()
        for spec in self.game.options:
            widget = self._option_widgets.get(spec.key)
            if widget is None:
                continue
            if spec.is_ini:
                self._write_ini_option(spec, spec.default)
            widget.blockSignals(True)
            if spec.kind == "bool":
                widget.setChecked(bool(spec.default))
            elif spec.kind == "choice":
                idx = widget.findData(spec.default)
                widget.setCurrentIndex(max(idx, 0))
            else:
                widget.setValue(int(spec.default))
            widget.blockSignals(False)
        self._update_command_preview()
        self._save()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_change_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, f"Select the {self.game.title} folder", self.install.path or ""
        )
        if not chosen:
            return
        result = identify_as(Path(chosen), self.game)
        if result is None:
            QMessageBox.warning(
                self,
                "Not recognised",
                f"That folder does not look like {self.game.title}.\n\n"
                "Expected to find one of: "
                f"{', '.join(self.game.signature_files)}",
            )
            return
        self.install.path = str(result.root)
        self._save()
        self._load_ini()
        self.mods_panel.manager.game_root = result.root
        self.mods_panel.reload()
        self.refresh()
        self.install_changed.emit()

    def _on_open_folder(self) -> None:
        if self.install.path and Path(self.install.path).is_dir():
            os.startfile(self.install.path)  # noqa: S606 - Windows shell open

    def start(self) -> bool:
        """Start the game as if Play had been pressed. Used by the library."""
        if not self.play_button.isEnabled():
            return False
        self._on_play()
        return True

    def _start_record_watch(self):
        """Begin watching this session for lap records, if the game has any.

        The watcher is handed to the window rather than kept here: the game
        page can be rebuilt or navigated away from while the game is still
        running, and a watcher that dies with the page would lose the session
        it was watching.
        """
        from ..records.session import RecordWatcher

        if not RecordWatcher.supported(self.game.id):
            return None
        window = self.window()
        if not hasattr(window, "adopt_record_watcher"):
            return None
        watcher = RecordWatcher(
            self.game.id,
            Path(self.install.path),
            process=None,
            username=self.config.settings.username,
            mods=list(self.install.enabled_mods),
        )
        window.adopt_record_watcher(watcher)
        return watcher

    def _on_play(self) -> None:
        try:
            plan = launch.build_plan(
                self.game,
                Path(self.install.path),
                self.install.target,
                self.install.options,
                self.extra_field.text(),
                self.install.custom_exe,
            )
            # Taken before the process starts, so anything that improves
            # afterwards was driven under the launcher's own eyes.
            watcher = self._start_record_watch()
            process = launch.launch(plan)
            if self.game.needs_single_core:
                launch.pin_to_single_core(process)
        except launch.LaunchError as exc:
            QMessageBox.critical(self, "Could not launch", str(exc))
            return

        if watcher is not None:
            watcher.process = process
            watcher.start()

        window = self.window()
        if self.config.settings.close_on_launch:
            window.close()
        elif hasattr(window, "flash_status"):
            window.flash_status(f"Launched {plan.display_command()}")
