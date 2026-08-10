"""The Lap Records tab: your times, and the community's.

Two axes, so two levels of tabs. The outer one is the game, because a Midtown
Madness time and a Monster Truck Madness time have nothing to say to each
other. The inner one is the board — Vanilla and Modded — because a lap set on
the stock city and one set on a racepack are not the same lap even when the
race has the same name.

Records that came off this machine are marked. Everything else arrived over
the network from a channel anyone with the launcher can post to, and the page
says so rather than presenting it as fact.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from ..games.registry import GAMES
from ..records import mm1
from . import theme
from .widgets import Card

# Games that can produce records at all. The others get a tab explaining why
# rather than being hidden, so the roadmap is visible the way the library's
# greyed-out cards are.
SUPPORTED = ("mm1",)

BOARDS = (
    (mm1.BOARD_VANILLA, "Vanilla", "Stock cars, stock races, no archives loaded."),
    (mm1.BOARD_MODDED, "Modded", "Racepacks allowed. Stock cars only."),
)

COLUMNS = ("Race", "Time", "Car", "Driver", "Difficulty", "Source")

# label, column, order. Race order is the default because a board is normally
# read race by race; the other two answer "what are the fastest times here".
SORTS = (
    ("Race order", 0, Qt.AscendingOrder),
    ("Fastest first", 1, Qt.AscendingOrder),
    ("Slowest first", 1, Qt.DescendingOrder),
)


class RecordItem(QTreeWidgetItem):
    """A row that sorts on its real values rather than on what it displays.

    Times are shown as "1:41.234" and "41.228", and sorted as text the longer
    lap comes first — the string starts with a 1. Every column therefore
    carries a sort key alongside the label it shows.
    """

    def __init__(self, columns: list[str], keys: dict[int, object]):
        super().__init__(columns)
        self._keys = keys

    def __lt__(self, other: "QTreeWidgetItem") -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        mine = self._keys.get(column)
        theirs = getattr(other, "_keys", {}).get(column)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return mine < theirs


class BoardView(QWidget):
    """One board for one game: a table of races and the best time on each."""

    def __init__(self, game_id: str, board: str, blurb: str):
        super().__init__()
        self.game_id = game_id
        self.board = board

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(10)

        note = QLabel(blurb)
        note.setObjectName("Faint")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.tree = QTreeWidget()
        self.tree.setObjectName("RecordTable")
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(COLUMNS)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QTreeWidget.NoSelection)
        self.tree.setFocusPolicy(Qt.NoFocus)
        # A verified run links to its own video; double-click opens it.
        self.tree.itemDoubleClicked.connect(self._open_proof)
        # Clicking a header sorts too, on the same real values the selector
        # uses rather than on the displayed text.
        self.tree.setSortingEnabled(True)
        self.tree.header().setSortIndicatorShown(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        layout.addWidget(self.tree, 1)

        self.empty = QLabel()
        self.empty.setObjectName("Faint")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.empty.setContentsMargins(0, 30, 0, 0)
        layout.addWidget(self.empty)

    @staticmethod
    def _open_proof(item, _column: int) -> None:
        url = item.data(0, Qt.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def show_records(self, records: list, own_names: set[str],
                     sort: int = 0) -> None:
        self.tree.clear()
        rows = [r for r in records if r.game == self.game_id and r.board == self.board]
        # Best time per race first, then by race order, so the table reads as
        # a leaderboard rather than as a log of attempts.
        best: dict[tuple, object] = {}
        for record in rows:
            key = (record.difficulty, record.race)
            current = best.get(key)
            if current is None or record.seconds < current.seconds:
                best[key] = record

        ordered = sorted(best.values(), key=lambda r: (r.race, r.difficulty))
        # Sorting is switched off while rows are added, then switched back on
        # with the wanted order. Leaving it on makes every insert re-sort the
        # whole table, which on a full board is sixty-four needless passes.
        self.tree.setSortingEnabled(False)
        for record in ordered:
            who = record.username or record.driver
            item = RecordItem(
                [
                    f"{record.race_name}"
                    + (f"  ·  {record.race_kind}" if record.race_kind else ""),
                    record.formatted,
                    # speedrun.com does not report which car a run used, so
                    # the column is dashed rather than left ambiguously blank.
                    record.car_name or "—",
                    who,
                    record.difficulty.title(),
                    "" if record.source == "launcher" else record.source,
                ],
                {
                    # Race sorts by its position in the game, not its name, so
                    # "race order" means the order they appear in the game.
                    0: (record.race, record.difficulty),
                    1: record.seconds,
                    2: record.car_name.lower(),
                    3: who.lower(),
                    4: record.difficulty.lower(),
                    5: record.source.lower(),
                },
            )
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            if record.url:
                item.setData(0, Qt.UserRole, record.url)
                item.setToolTip(
                    len(COLUMNS) - 1,
                    f"Verified on {record.source}. Double-click to open the run.",
                )
            if who in own_names:
                # Your own row, so a board full of other people's times still
                # shows you where you stand at a glance.
                for column in range(len(COLUMNS)):
                    item.setForeground(column, theme.accent_brush())
                item.setToolTip(0, "Set on this machine")
            self.tree.addTopLevelItem(item)

        label, column, order = SORTS[sort if 0 <= sort < len(SORTS) else 0]
        self.tree.sortItems(column, order)
        self.tree.setSortingEnabled(True)

        has_rows = bool(ordered)
        self.tree.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        if not has_rows:
            self.empty.setText(
                "No times yet. Finish a race with the launcher running and it "
                "will appear here."
                if self.board == mm1.BOARD_VANILLA
                else "No times yet. Race with a racepack enabled and a stock "
                "car to fill this board."
            )


class GameRecords(QWidget):
    """Vanilla and Modded for one game."""

    def __init__(self, game_id: str):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.views: dict[str, BoardView] = {}
        for board, label, blurb in BOARDS:
            view = BoardView(game_id, board, blurb)
            self.views[board] = view
            self.tabs.addTab(view, label)
        layout.addWidget(self.tabs)

    def show_records(self, records: list, own_names: set[str],
                     sort: int = 0) -> None:
        for board, view in self.views.items():
            view.show_records(records, own_names, sort)
            index = list(self.views).index(board)
            count = sum(
                1 for r in records if r.board == board and r.game == view.game_id
            )
            label = dict((b, l) for b, l, _ in BOARDS)[board]
            self.tabs.setTabText(index, f"{label}  {count}" if count else label)


class RecordsPage(QWidget):
    """Lap records, by game and by board."""

    def __init__(self, config: Config, records_source):
        super().__init__()
        self.config = config
        # A callable rather than a list, so the page always draws whatever the
        # window currently holds instead of a copy taken when it was built.
        self._records_source = records_source

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 24)
        root.setSpacing(16)

        title = QLabel("Lap Records")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        caution = Card(
            "How these are collected",
            "The launcher reads the game's own best-time table before and "
            "after a session, so a record has to be set while the launcher is "
            "running. Community times are submitted by players and are "
            "moderated rather than independently verified. Rows marked "
            "speedrun.com come from that site's leaderboards instead and have "
            "been checked against video by its moderators; double-click one "
            "to watch the run.",
        )
        root.addWidget(caution)

        controls = QHBoxLayout()
        controls.setSpacing(9)
        sort_label = QLabel("Sort by")
        sort_label.setObjectName("Faint")
        controls.addWidget(sort_label)
        self.sort_box = QComboBox()
        for label, _, _ in SORTS:
            self.sort_box.addItem(label)
        self.sort_box.setToolTip(
            "Fastest first compares every race against every other, so a short "
            "Blitz will outrank a long Circuit. Clicking a column header sorts "
            "by that column instead."
        )
        self.sort_box.currentIndexChanged.connect(lambda _: self.refresh())
        controls.addWidget(self.sort_box)
        controls.addStretch(1)
        root.addLayout(controls)

        self.games = QTabWidget()
        self.views: dict[str, GameRecords] = {}
        for game in GAMES:
            if game.id in SUPPORTED:
                view = GameRecords(game.id)
                self.views[game.id] = view
                self.games.addTab(view, game.title)
            else:
                self.games.addTab(self._not_yet(game.title), game.title)
        root.addWidget(self.games, 1)

        self.refresh()

    @staticmethod
    def _not_yet(title: str) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 40, 0, 0)
        label = QLabel(
            f"{title} does not have lap records yet.\n\nMidtown Madness keeps "
            "its best times in a file the launcher can read. The other games "
            "each store theirs differently, and support is added one game at "
            "a time."
        )
        label.setObjectName("Faint")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        layout.addWidget(label)
        layout.addStretch(1)
        return host

    def refresh(self) -> None:
        records = list(self._records_source() or [])
        own = {self.config.settings.username} - {""}
        sort = self.sort_box.currentIndex()
        for view in self.views.values():
            view.show_records(records, own, sort)
