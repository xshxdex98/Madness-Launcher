"""The Mods tab: index, import, enable, order, remove."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..games.base import GameDef
from ..mods import Mod, ModError, ModManager
from . import theme
from .widgets import Badge, Card, scrollable


class ModRow(QFrame):
    """One mod in the list."""

    # Enabling or reordering changes only what the rows say, so the panel can
    # refresh them in place. Removing changes which rows exist, which needs a
    # rebuild — kept separate so a simple tick does not blow the list away and
    # lose the user's scroll position.
    state_changed = Signal()
    list_changed = Signal()

    def __init__(self, mod: Mod, manager: ModManager, owners: dict[str, str]):
        super().__init__()
        self.setObjectName("InsetCard")
        self.mod = mod
        self.manager = manager

        outer = QVBoxLayout(self)
        outer.setContentsMargins(13, 10, 13, 10)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)

        self.toggle = QCheckBox()
        self.toggle.setChecked(mod.enabled)
        self.toggle.setEnabled(mod.available or mod.enabled)
        self.toggle.toggled.connect(self._on_toggled)
        top.addWidget(self.toggle, 0, Qt.AlignVCenter)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        name = QLabel(mod.name)
        name.setObjectName("CardTitle")
        title_col.addWidget(name)

        bits = []
        if mod.version:
            bits.append(f"v{mod.version}")
        if mod.author:
            bits.append(f"by {mod.author}")
        count = len(mod.payload_files())
        bits.append(f"{count} file{'s' if count != 1 else ''}")
        if mod.linked:
            bits.append("indexed in place")
        detail = QLabel("  ·  ".join(bits))
        detail.setObjectName("Faint")
        title_col.addWidget(detail)
        top.addLayout(title_col, 1)

        self.badge = Badge()
        top.addWidget(self.badge, 0, Qt.AlignVCenter)

        spec = manager.game.mod_spec
        if spec.priority_prefix and spec.max_priority > 0:
            label = QLabel("Priority")
            label.setObjectName("Faint")
            top.addWidget(label, 0, Qt.AlignVCenter)

            self.priority = QSpinBox()
            self.priority.setRange(0, spec.max_priority)
            self.priority.setValue(mod.priority)
            self.priority.setFixedWidth(60)
            self.priority.setToolTip(spec.priority_help)
            self.priority.valueChanged.connect(self._on_priority)
            top.addWidget(self.priority, 0, Qt.AlignVCenter)

        remove = QPushButton("Remove")
        remove.setObjectName("Danger")
        remove.setToolTip(
            "Remove from the launcher's list. The mod's own files are left alone."
            if mod.linked
            else "Remove this mod from the library."
        )
        remove.clicked.connect(self._on_remove)
        top.addWidget(remove, 0, Qt.AlignVCenter)

        outer.addLayout(top)

        self.warning = QLabel()
        self.warning.setObjectName("Faint")
        self.warning.setWordWrap(True)
        self.warning.hide()
        outer.addWidget(self.warning)

        self.refresh_state(owners)

    def refresh_state(self, owners: dict[str, str]) -> None:
        self.warning.hide()
        self.warning.setStyleSheet("")
        blocked = self.toggle.blockSignals(True)
        self.toggle.setChecked(self.mod.enabled)
        self.toggle.blockSignals(blocked)
        self.toggle.setEnabled(self.mod.available or self.mod.enabled)

        if not self.mod.available and not self.mod.enabled:
            self.badge.setText("Missing")
            self.badge.set_tone("bad")
            self.warning.setText(
                f"Files are no longer at {self.mod.link_source or self.mod.payload_dir}."
            )
            self.warning.setStyleSheet(f"color: {theme.BAD};")
            self.warning.show()
            return

        enabled = self.mod.enabled
        self.badge.setText("Installed" if enabled else "Available")
        self.badge.set_tone("good" if enabled else "muted")

        if enabled:
            return

        clashes = {
            pf.dest_rel: owners[pf.dest_rel.lower()]
            for pf in self.manager.plan(self.mod)
            if pf.dest_rel.lower() in owners
        }
        if clashes:
            first = next(iter(clashes.items()))
            self.warning.setText(
                f"Overlaps {first[1]} on {first[0]}. Enabling takes over "
                f"{len(clashes)} file(s)."
            )
            self.warning.setStyleSheet(f"color: {theme.WARN};")
            self.warning.show()

    def _on_toggled(self, checked: bool) -> None:
        try:
            if checked:
                self.manager.enable(self.mod)
            else:
                self.manager.disable(self.mod)
        except (ModError, OSError) as exc:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(not checked)
            self.toggle.blockSignals(False)
            QMessageBox.warning(
                self,
                "Mod could not be changed",
                f"{self.mod.name}\n\n{exc}\n\n"
                "If the game is running, close it and try again.",
            )
        self.state_changed.emit()

    def _on_priority(self, value: int) -> None:
        try:
            self.manager.set_priority(self.mod, value)
        except (ModError, OSError) as exc:
            QMessageBox.warning(self, "Could not change priority", str(exc))
        self.state_changed.emit()

    def _on_remove(self) -> None:
        extra = (
            "\n\nThis mod is indexed where it sits in the game folder, so only "
            "the launcher's entry goes — its files are not deleted."
            if self.mod.linked
            else ""
        )
        if QMessageBox.question(
            self,
            "Remove mod",
            f"Remove '{self.mod.name}' from the list?\n\n"
            "It will be disabled first, restoring anything it replaced." + extra,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            self.manager.delete(self.mod)
        except (ModError, OSError) as exc:
            QMessageBox.warning(self, "Could not remove mod", str(exc))
        self.list_changed.emit()


class CategorySection(QWidget):
    """A collapsible group of mods, one per staging folder."""

    def __init__(self, title: str):
        super().__init__()
        self.rows: list[ModRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        self.header = QPushButton()
        self.header.setObjectName("SectionToggle")
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.toggled.connect(self._on_toggled)
        layout.addWidget(self.header)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(7)
        layout.addWidget(self.body)
        self.body_layout = body_layout

        self._title = title
        self.refresh_counts()

    def refresh_counts(self) -> None:
        total = len(self.rows)
        enabled = sum(1 for row in self.rows if row.mod.enabled)
        arrow = "▾" if self.header.isChecked() else "▸"
        suffix = f"{total} mod{'s' if total != 1 else ''}"
        if enabled:
            suffix += f"  ·  {enabled} enabled"
        # A button treats '&' as a mnemonic marker and swallows it, which
        # mangles folder names like "Custom Racepacks & Cities".
        title = self._title.upper().replace("&", "&&")
        self.header.setText(f"  {arrow}  {title}      {suffix}")

    def add_row(self, row: "ModRow") -> None:
        self.rows.append(row)
        self.body_layout.addWidget(row)
        self.refresh_counts()

    def _on_toggled(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.refresh_counts()


class ModsPanel(QWidget):
    """Mod library for one configured game."""

    mods_changed = Signal()

    def __init__(self, game: GameDef, game_root: Path):
        super().__init__()
        self.game = game
        self.manager = ModManager(game, game_root)
        self._filter = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(13)

        root.addWidget(self._build_toolbar())

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(14)
        self.list_layout.addStretch(1)
        self.scroll = scrollable(self.list_host)
        root.addWidget(self.scroll, 1)

        self._sections: list[CategorySection] = []
        self._rows: list[ModRow] = []
        # Building a row per mod costs a few hundred milliseconds on a library
        # of a hundred-odd, and most visits to a game never open this tab. The
        # list is built the first time it is actually looked at.
        self._loaded = False

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self._loaded = True
            self.reload()

    def _build_toolbar(self) -> QWidget:
        card = Card(
            "Mod library",
            self.game.mod_spec.staging_help or self.game.mod_spec.notes,
        )

        row = QHBoxLayout()
        row.setSpacing(9)

        if self.game.mod_spec.scan_staging:
            scan = QPushButton("Scan game folder")
            scan.setObjectName("Primary")
            scan.setToolTip(
                "Look through this game's folder for mods parked in "
                "subfolders and list them, without moving anything."
            )
            scan.clicked.connect(self._scan)
            row.addWidget(scan)

        add_file = QPushButton("Add mod file…")
        add_file.clicked.connect(self._import_file)
        row.addWidget(add_file)

        add_folder = QPushButton("Add folder…")
        add_folder.clicked.connect(self._import_folder)
        row.addWidget(add_folder)

        row.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter mods…")
        self.search.setFixedWidth(200)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_filter)
        row.addWidget(self.search)

        self.count_label = QLabel()
        self.count_label.setObjectName("Faint")
        row.addWidget(self.count_label)

        card.body.addLayout(row)
        return card

    # -- data ------------------------------------------------------------

    def _owner_map(self) -> dict[str, str]:
        """Destination path -> name of the enabled mod that owns it.

        Built once per reload; asking each row to work it out for itself made
        the list quadratic, which is felt at 50+ mods.
        """
        owners: dict[str, str] = {}
        for mod in self.manager.list_mods():
            if not mod.enabled:
                continue
            for entry in self.manager._read_receipt(mod):
                owners[entry["dest_rel"].lower()] = mod.name
        return owners

    def refresh_states(self) -> None:
        """Update what the existing rows say, without rebuilding the list.

        Ticking a mod changes every row's conflict warning and both counters,
        but not which rows exist — so nothing is destroyed and the scroll
        position is left exactly where the user had it.
        """
        owners = self._owner_map()
        for row in self._rows:
            row.refresh_state(owners)
        for section in self._sections:
            section.refresh_counts()
        self._update_count_label(
            total=len(self._rows),
            shown=len(self._rows),
            enabled=sum(1 for row in self._rows if row.mod.enabled),
        )

    def _update_count_label(self, total: int, shown: int, enabled: int) -> None:
        summary = f"{total} in library · {enabled} enabled"
        if self._filter and shown != total:
            summary = f"{shown} of {summary}"
        self.count_label.setText(summary)

    def reload(self, preserve_scroll: bool = True) -> None:
        previous = self.scroll.verticalScrollBar().value() if preserve_scroll else 0

        self._sections.clear()
        self._rows.clear()
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # deleteLater() alone is deferred to the event loop, so the old
                # rows stay painted over the new ones until it runs. Unparent
                # first to take them off screen immediately.
                widget.setParent(None)
                widget.deleteLater()

        groups = self.manager.by_category()
        owners = self._owner_map()
        needle = self._filter.lower()

        total = shown = enabled_total = 0
        insert_at = 0
        for category, mods in groups.items():
            enabled_total += sum(1 for m in mods if m.enabled)
            total += len(mods)
            visible = [m for m in mods if not needle or needle in m.name.lower()]
            if not visible:
                continue
            shown += len(visible)

            section = CategorySection(category or "Imported")
            for mod in visible:
                row = ModRow(mod, self.manager, owners)
                row.state_changed.connect(self._on_row_state_changed)
                row.list_changed.connect(self._on_row_list_changed)
                section.add_row(row)
                self._rows.append(row)
            self._sections.append(section)
            self.list_layout.insertWidget(insert_at, section)
            insert_at += 1

        if total == 0:
            self.list_layout.insertWidget(0, self._empty_state())
        elif shown == 0:
            note = Card()
            label = QLabel(f"Nothing matches “{self._filter}”.")
            label.setObjectName("Faint")
            label.setAlignment(Qt.AlignCenter)
            note.body.addWidget(label)
            self.list_layout.insertWidget(0, note)

        self._update_count_label(total=total, shown=shown, enabled=enabled_total)

        if preserve_scroll and previous:
            # After a rebuild the scrollbar's range is only correct once the
            # new widgets have been laid out, so restore on the next tick.
            QTimer.singleShot(0, lambda: self._restore_scroll(previous))

    def _restore_scroll(self, value: int) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(min(value, bar.maximum()))

    def _empty_state(self) -> QWidget:
        card = Card()
        staged = self.game.mod_spec.scan_staging
        label = QLabel(
            (
                "No mods indexed yet.\n\n"
                "If this copy of the game came with mod folders, use "
                "“Scan game folder” to index them where they sit — nothing is "
                "copied until you enable it."
            )
            if staged
            else "No mods yet. Add a .ar file, a .zip, or a folder."
        )
        label.setObjectName("Faint")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        card.body.addWidget(label)
        return card

    def enabled_slugs(self) -> list[str]:
        return [m.slug for m in self.manager.list_mods() if m.enabled]

    def _on_filter(self, text: str) -> None:
        self._filter = text.strip()
        # A new filter means a different list, so starting at the top is right.
        self.reload(preserve_scroll=False)

    def _on_row_state_changed(self) -> None:
        self.refresh_states()
        self.mods_changed.emit()

    def _on_row_list_changed(self) -> None:
        self.reload()
        self.mods_changed.emit()

    # -- actions ---------------------------------------------------------

    def _scan(self) -> None:
        try:
            result = self.manager.scan_staged()
        except OSError as exc:
            QMessageBox.warning(self, "Could not scan", str(exc))
            return
        self.reload()
        self.mods_changed.emit()

        if result.added:
            body = (
                f"Indexed {result.added} mod{'s' if result.added != 1 else ''}"
                + (f", {result.already_known} already known." if result.already_known else ".")
                + "\n\nTheir files stay where they are. Ticking a mod copies it "
                "into the game folder; unticking removes it again."
            )
        else:
            body = "No new mods found." + (
                f" All {result.already_known} are already listed."
                if result.already_known
                else ""
            )

        # Never let a skipped item pass silently — an untouched folder would
        # otherwise look like an empty one.
        if result.unmanaged:
            listed = "\n".join(
                f"  · {name}   ({category})" for category, name in result.unmanaged[:8]
            )
            more = (
                f"\n  … and {len(result.unmanaged) - 8} more"
                if len(result.unmanaged) > 8
                else ""
            )
            body += (
                f"\n\nLeft alone ({len(result.unmanaged)}):\n{listed}{more}\n\n"
                "These are packaged releases or documentation rather than "
                "drop-in mods. They usually carry their own README and install "
                "steps, so the launcher does not touch them."
            )

        QMessageBox.information(self, "Scan complete", body)

    def _import_file(self) -> None:
        suffixes = " ".join(f"*{s}" for s in self.game.mod_spec.archive_suffixes)
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a mod file", "", f"Mod files ({suffixes} *.zip);;All files (*)"
        )
        if path:
            self._do_import(Path(path), ask_destination=True)

    def _import_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select a mod folder")
        if path:
            self._do_import(Path(path))

    def _ask_destination(self, source: Path) -> str | None:
        """Ask which content folder a loose file belongs in.

        A downloaded course or track is just a file; nothing in it says whether
        it is Supercross or Baja, and dropping it in the game root would leave
        the game unable to find it. Only the person who downloaded it knows.
        Returns the chosen folder, "" for the game root, or None if cancelled.
        """
        destinations = self.manager.content_destinations()
        if not destinations:
            return ""

        dialog = QDialog(self)
        dialog.setWindowTitle("Where does this go?")
        dialog.setMinimumWidth(430)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)

        heading = QLabel(f"Install “{source.name}” into")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)

        if self.game.mod_spec.content_help:
            blurb = QLabel(self.game.mod_spec.content_help)
            blurb.setObjectName("Faint")
            blurb.setWordWrap(True)
            layout.addWidget(blurb)

        picker = QComboBox()
        for dest in destinations:
            picker.addItem(dest, dest)
        picker.addItem("The game folder itself", "")
        layout.addWidget(picker)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        buttons.button(QDialogButtonBox.Ok).setText("Add mod")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return None
        return picker.currentData()

    def _do_import(self, source: Path, ask_destination: bool = False) -> None:
        destination = ""
        if ask_destination:
            destination = self._ask_destination(source)
            if destination is None:
                return
        try:
            mod = self.manager.import_path(source, dest_prefix=destination)
        except (ModError, OSError) as exc:
            QMessageBox.warning(self, "Could not import mod", f"{source}\n\n{exc}")
            return
        self.reload()
        self.mods_changed.emit()
        QMessageBox.information(
            self,
            "Mod imported",
            f"'{mod.name}' was added.\n\nTick it to install it into "
            + (mod.dest_prefix if mod.dest_prefix else "the game folder")
            + ".",
        )
