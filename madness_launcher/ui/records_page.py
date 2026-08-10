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

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from ..games.registry import GAMES
from ..records import mm1, profiles
from ..news.model import age_of
from . import theme
from .widgets import Card

# Games that can produce records at all. The others get a tab explaining why
# rather than being hidden, so the roadmap is visible the way the library's
# greyed-out cards are.
SUPPORTED = ("mm1", "mm2")

BOARDS = (
    (mm1.BOARD_VANILLA, "Vanilla", "Stock cars, stock races, no archives loaded."),
    (mm1.BOARD_MODDED, "Modded", "Racepacks allowed. Stock cars only."),
)

COLUMNS = ("#", "Race", "Time", "Car", "Driver", "Difficulty", "Source")

# Named once rather than counted at every use.
COL_RANK, COL_RACE, COL_TIME, COL_CAR, COL_DRIVER, COL_DIFF, COL_SOURCE = range(7)

# Records that came from an external leaderboard rather than from a launcher.
EXTERNAL = "speedrun.com"

# What to call a city folder on screen.
CITY_LABELS = {"chicago": "Chicago", "london": "London",
               "sf": "San Francisco"}

# label, column, order. Race order is the default because a board is normally
# read race by race; the other two answer "what are the fastest times here".
SORTS = (
    ("Race order", COL_RANK, Qt.AscendingOrder),
    ("Fastest first", COL_TIME, Qt.AscendingOrder),
    ("Slowest first", COL_TIME, Qt.DescendingOrder),
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

    def __init__(self, game_id: str, city: str, board: str, blurb: str):
        super().__init__()
        self.game_id = game_id
        self.city = city
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
        header.setSectionResizeMode(COL_RACE, QHeaderView.Stretch)
        for column in range(len(COLUMNS)):
            if column != COL_RACE:
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
                     sort: int = 0, show_external: bool = True) -> None:
        self.tree.clear()
        rows = [
            r for r in records
            if r.game == self.game_id and r.board == self.board
            and (not self.city or r.city.lower() == self.city)
        ]

        # One row per driver per race. Collapsing to a single best time made
        # the board useless the moment verified world records sat beside
        # community ones: every race already held a world record, so nobody
        # else's time could appear on it.
        #
        # Keyed by car too, matching how the game records a time and how the
        # relay groups them: a faster lap in the same car replaces the old one
        # rather than sitting beside it. Source is not part of the key, so a
        # time replaces your own earlier one however it arrived.
        best: dict[tuple, object] = {}
        for record in rows:
            who = (record.username or record.driver).lower()
            key = (record.city.lower(), record.difficulty, record.race,
                   who, record.car.lower())
            current = best.get(key)
            if current is None or record.seconds < current.seconds:
                best[key] = record

        kept = list(best.values())
        if not show_external:
            kept = [r for r in kept if r.source != EXTERNAL]

        # Position within its own race, over what is actually on screen.
        # Whoever is quickest is first, whether that is a verified world
        # record or somebody who has just beaten one.
        ranks: dict[int, int] = {}
        grouped: dict[tuple, list] = {}
        for record in kept:
            grouped.setdefault((record.difficulty, record.race), []).append(record)
        for group in grouped.values():
            group.sort(key=lambda r: r.seconds)
            for position, record in enumerate(group, 1):
                ranks[id(record)] = position

        ordered = sorted(kept, key=lambda r: (r.race, r.difficulty, r.seconds))
        # Sorting is switched off while rows are added and back on afterwards.
        # Leaving it on re-sorts the whole table on every insert.
        self.tree.setSortingEnabled(False)
        for record in ordered:
            who = record.username or record.driver
            rank = ranks[id(record)]
            item = RecordItem(
                [
                    str(rank),
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
                    COL_RANK: (record.race, record.difficulty, record.seconds),
                    COL_RACE: (record.race, record.difficulty, record.seconds),
                    COL_TIME: record.seconds,
                    COL_CAR: record.car_name.lower(),
                    COL_DRIVER: who.lower(),
                    COL_DIFF: record.difficulty.lower(),
                    COL_SOURCE: record.source.lower(),
                },
            )
            item.setTextAlignment(COL_RANK, Qt.AlignRight | Qt.AlignVCenter)
            item.setTextAlignment(COL_TIME, Qt.AlignRight | Qt.AlignVCenter)
            if rank == 1:
                item.setToolTip(COL_RANK, "Fastest on this race")
            if record.url:
                item.setData(0, Qt.UserRole, record.url)
                item.setToolTip(
                    COL_SOURCE,
                    f"Verified on {record.source}. Double-click to open the run.",
                )
            if who in own_names:
                # Your own row, so a board full of other people's times still
                # shows you where you stand at a glance.
                for column in range(len(COLUMNS)):
                    item.setForeground(column, theme.accent_brush())
                item.setToolTip(COL_RACE, "Set on this machine")
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


class CityBoards(QWidget):
    """Vanilla and Modded for one city of one game."""

    def __init__(self, game_id: str, city: str = ""):
        super().__init__()
        self.game_id = game_id
        self.city = city
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.views: dict[str, BoardView] = {}
        for board, label, blurb in BOARDS:
            view = BoardView(game_id, city, board, blurb)
            self.views[board] = view
            self.tabs.addTab(view, label)
        layout.addWidget(self.tabs)

    def matches(self, record) -> bool:
        return (record.game == self.game_id
                and (not self.city or record.city.lower() == self.city))

    def show_records(self, records: list, own_names: set[str],
                     sort: int = 0, show_external: bool = True) -> None:
        for index, (board, view) in enumerate(self.views.items()):
            view.show_records(records, own_names, sort, show_external)
            count = sum(1 for r in records
                        if r.board == board and self.matches(r))
            label = dict((b, l) for b, l, _ in BOARDS)[board]
            self.tabs.setTabText(index, f"{label}  {count}" if count else label)


class GameRecords(QWidget):
    """One game's boards, under a city level when the game has cities.

    Midtown Madness has only Chicago, so a city tab there would be a tab
    with nothing to choose. Midtown Madness 2 has London and San
    Francisco, and their races are numbered separately — without the
    split the two cities' boards would read as one long confusing list.
    """

    def __init__(self, game_id: str):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        spec = profiles.profile(game_id)
        self.cities: dict[str, CityBoards] = {}
        self.city_tabs: QTabWidget | None = None

        if len(spec.cities) > 1:
            self.city_tabs = QTabWidget()
            for city in spec.cities:
                boards = CityBoards(game_id, city)
                self.cities[city] = boards
                self.city_tabs.addTab(boards, CITY_LABELS.get(city, city.title()))
            layout.addWidget(self.city_tabs)
        else:
            only = spec.cities[0] if spec.cities else ""
            boards = CityBoards(game_id, only)
            self.cities[only] = boards
            layout.addWidget(boards)

    @property
    def views(self) -> dict:
        """The boards of the first city, for a single-city game."""
        return next(iter(self.cities.values())).views

    @property
    def tabs(self):
        """The board tabs of the first city."""
        return next(iter(self.cities.values())).tabs

    def show_records(self, records: list, own_names: set[str],
                     sort: int = 0, show_external: bool = True) -> None:
        for index, (city, boards) in enumerate(self.cities.items()):
            boards.show_records(records, own_names, sort, show_external)
            if self.city_tabs is not None:
                count = sum(1 for r in records if boards.matches(r))
                label = CITY_LABELS.get(city, city.title())
                self.city_tabs.setTabText(
                    index, f"{label}  {count}" if count else label
                )


class RecordsPage(QWidget):
    """Lap records, by game and by board."""

    # Asked to fetch the community board again. The window owns the feed,
    # so the page requests rather than performs it.
    refresh_requested = Signal()

    def __init__(self, config: Config, records_source):
        super().__init__()
        self.config = config
        # A callable rather than a list, so the page always draws whatever the
        # window currently holds instead of a copy taken when it was built.
        self._records_source = records_source
        # Set by the window; when the feed last arrived, for the status line.
        self.fetched_at = None

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
        self.show_wr = QCheckBox("Include speedrun.com world records")
        self.show_wr.setChecked(True)
        self.show_wr.setToolTip(
            "Verified runs from speedrun.com, shown alongside community "
            "times. Turn this off to read the community board on its own. "
            "Either way the fastest time on a race is ranked first, so beating "
            "a world record takes the top spot from it."
        )
        self.show_wr.toggled.connect(lambda _: self.refresh())
        controls.addWidget(self.show_wr)
        controls.addStretch(1)

        self.status = QLabel()
        self.status.setObjectName("Faint")
        controls.addWidget(self.status, 0, Qt.AlignVCenter)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("Ghost")
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.setToolTip(
            "Fetch the community board now. It also refreshes on its own every "
            "few minutes, and whenever this tab is opened."
        )
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        controls.addWidget(self.refresh_button, 0, Qt.AlignVCenter)
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
        external = self.show_wr.isChecked()
        for view in self.views.values():
            view.show_records(records, own, sort, external)
        self._refresh_status(len(records))

    def _refresh_status(self, count: int) -> None:
        """How much is on the board, and how old it is."""
        when = age_of(self.fetched_at()) if self.fetched_at else ""
        shown = f"{count} record{'s' if count != 1 else ''}"
        self.status.setText(f"{shown} · updated {when}" if when else shown)
