"""Application shell: sidebar navigation over a stack of game pages."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__, branding, identity, paths
from ..chat import DEFAULT_HOST
from ..config import Config
from ..detect import identify_as
from ..games.registry import GAMES, PLANNED, by_id
from ..news import NewsService, ThumbnailCache, safe_url
from ..records import mm1 as mm1_records
from ..records import session as record_session
from ..records import store as record_store
from ..records.submit import RecordSubmitter
from . import gameart, theme, wordmark
from .chat_page import ChatPage
from .game_page import GamePage
from .library_page import LibraryPage
from .news_page import NewsPage
from .records_page import RecordsPage
from .presence import Presence
from .setup_page import SetupPage
from .username_dialog import UsernameDialog
from .widgets import Card, LogoArea, StatusDot, scrollable

SIDEBAR_WIDTH = 256
SIDEBAR_ICON = 18
# What a game entry has left for its label once the sidebar margins, the button
# padding, the icon and the status dot have taken their share. Long titles are
# elided into this rather than being allowed to run under the dot.
ENTRY_TEXT_WIDTH = SIDEBAR_WIDTH - 28 - 22 - SIDEBAR_ICON - 6 - 22
LIBRARY_KEY = "__library__"
NEWS_KEY = "__news__"
RECORDS_KEY = "__records__"
CHAT_KEY = "__chat__"
SETTINGS_KEY = "__settings__"

# Long enough that the window is up and interactive before the launcher makes
# its first outbound request of the session.
NEWS_START_DELAY_MS = 1200

# How often a launcher that is simply left open asks for the feed again. The
# service throttles to five minutes of its own accord, so this is the interval
# at which a board on screen catches up with records other people have set.
FEED_POLL_MS = 10 * 60 * 1000


NO_USERNAME = "No username set"


class MainWindow(QMainWindow):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self._pages: dict[str, QWidget] = {}
        self._entries: dict[str, QPushButton] = {}
        self._dots: dict[str, StatusDot] = {}
        self._accent = ""
        self._chat: ChatPage | None = None
        self._library: LibraryPage | None = None
        self._news: NewsPage | None = None
        self._lap_records: RecordsPage | None = None
        self._saving_news_url = False

        # Owns the shared chat connection so the head count is live whether or
        # not the Chat Room page has ever been opened.
        self.presence = Presence(config, parent=self)
        self.presence.count_changed.connect(self._on_presence_count)
        self.presence.state_changed.connect(self._on_presence_state)

        # Held by the window rather than the page for the same reason presence
        # is: the sidebar shows an unread marker whether or not the News tab
        # has ever been opened, and the thumbnail cache is worth keeping across
        # visits to it.
        self.news = NewsService(config, parent=self)
        self.news.updated.connect(self._on_news_updated)
        self.news.state_changed.connect(self._on_news_state)
        self.thumbs = ThumbnailCache(self)

        # Lap records. Watchers are held here rather than on the game page
        # because a page can be rebuilt or navigated away from while the
        # game it started is still running.
        self._watchers: list[object] = []
        self.submitter = RecordSubmitter(self)
        self.submitter.failed.connect(self._on_submit_failed)
        # Records worth sending before a webhook was known. The import runs
        # during startup and the webhook arrives with the news feed a moment
        # later, so without this a first run imports a whole history and
        # posts none of it.
        self._unsent: list = []
        # Last, because it can submit, and everything submitting depends on
        # has to exist by the time it runs.
        self._load_race_tables()
        self.records = record_store.load()
        self._import_existing_records()

        self.setWindowTitle(APP_NAME)
        self.resize(1120, 740)
        self.setMinimumSize(940, 620)

        root = QWidget()
        root.setObjectName("Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.setCentralWidget(root)

        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.setStatusBar(bar)
        bar.showMessage(f"{APP_NAME} {__version__}")

        self._build_settings_page()
        self._select_initial()
        QTimer.singleShot(0, self.presence.start)
        QTimer.singleShot(NEWS_START_DELAY_MS, self.news.refresh)
        # A launcher left open all evening must still pick up records other
        # people set. Without this it fetches once at startup and never again,
        # and the board a player is looking at silently ages.
        self._feed_poll = QTimer(self)
        self._feed_poll.setInterval(FEED_POLL_MS)
        self._feed_poll.timeout.connect(self.news.refresh)
        self._feed_poll.start()
        self._refresh_news_entry()

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(side)
        layout.setContentsMargins(14, 20, 14, 14)
        layout.setSpacing(6)

        self.logo = LogoArea()
        self.logo.clicked.connect(self._choose_logo)
        self._refresh_logo()
        layout.addWidget(self.logo)

        layout.addSpacing(22)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.library_entry = QPushButton(" Library")
        self.library_entry.setObjectName("GameEntry")
        self.library_entry.setCheckable(True)
        self.library_entry.setCursor(Qt.PointingHandCursor)
        self.library_entry.setToolTip("All games, with artwork and status")
        self.library_entry.setIcon(QIcon(gameart.nav_glyph("library", SIDEBAR_ICON)))
        self.library_entry.setIconSize(QSize(SIDEBAR_ICON, SIDEBAR_ICON))
        self.library_entry.clicked.connect(lambda: self._show(LIBRARY_KEY))
        self.nav_group.addButton(self.library_entry)
        self._entries[LIBRARY_KEY] = self.library_entry
        layout.addWidget(self.library_entry)

        layout.addSpacing(18)

        games_label = QLabel("GAMES")
        games_label.setObjectName("SectionLabel")
        layout.addWidget(games_label)
        layout.addSpacing(4)

        for game in GAMES:
            entry = self._make_entry(game.id, game.title, game.year)
            layout.addWidget(entry)

        # Only shown while something is actually pending. Every Madness game is
        # supported now, so this section disappears rather than sitting there as
        # an empty heading; it comes back on its own if a title is ever added to
        # PLANNED.
        if PLANNED:
            layout.addSpacing(18)
            planned_label = QLabel("COMING SOON")
            planned_label.setObjectName("SectionLabel")
            layout.addWidget(planned_label)
            layout.addSpacing(4)

            for game_id, title, year in PLANNED:
                entry = QPushButton(f"  {title}")
                entry.setObjectName("GameEntry")
                entry.setEnabled(False)
                entry.setToolTip("Not supported yet")
                layout.addWidget(entry)

        layout.addSpacing(18)
        community_label = QLabel("COMMUNITY")
        community_label.setObjectName("SectionLabel")
        layout.addWidget(community_label)
        layout.addSpacing(4)

        self.news_entry = QPushButton(" News")
        self.news_entry.setObjectName("GameEntry")
        self.news_entry.setCheckable(True)
        self.news_entry.setCursor(Qt.PointingHandCursor)
        self.news_entry.setIcon(QIcon(gameart.nav_glyph("news", SIDEBAR_ICON)))
        self.news_entry.setIconSize(QSize(SIDEBAR_ICON, SIDEBAR_ICON))
        self.news_entry.clicked.connect(lambda: self._show(NEWS_KEY))
        self.nav_group.addButton(self.news_entry)
        self._entries[NEWS_KEY] = self.news_entry
        layout.addWidget(self.news_entry)

        self.records_entry = QPushButton(" Lap Records")
        self.records_entry.setObjectName("GameEntry")
        self.records_entry.setCheckable(True)
        self.records_entry.setCursor(Qt.PointingHandCursor)
        self.records_entry.setToolTip("Fastest times, by game and by board")
        self.records_entry.setIcon(QIcon(gameart.nav_glyph("records", SIDEBAR_ICON)))
        self.records_entry.setIconSize(QSize(SIDEBAR_ICON, SIDEBAR_ICON))
        self.records_entry.clicked.connect(lambda: self._show(RECORDS_KEY))
        self.nav_group.addButton(self.records_entry)
        self._entries[RECORDS_KEY] = self.records_entry
        layout.addWidget(self.records_entry)

        self.chat_entry = QPushButton(" Chat Room")
        self.chat_entry.setObjectName("GameEntry")
        self.chat_entry.setCheckable(True)
        self.chat_entry.setCursor(Qt.PointingHandCursor)
        self.chat_entry.setIcon(QIcon(gameart.nav_glyph("chat", SIDEBAR_ICON)))
        self.chat_entry.setIconSize(QSize(SIDEBAR_ICON, SIDEBAR_ICON))
        self.chat_entry.clicked.connect(lambda: self._show(CHAT_KEY))
        self.nav_group.addButton(self.chat_entry)
        self._entries[CHAT_KEY] = self.chat_entry
        layout.addWidget(self.chat_entry)

        layout.addStretch(1)

        # A hairline separates the account block from the navigation above it,
        # so the empty space between them reads as deliberate rather than as a
        # gap the layout failed to fill.
        rule = QFrame()
        rule.setObjectName("SidebarRule")
        rule.setFixedHeight(1)
        layout.addWidget(rule)
        layout.addSpacing(10)

        # Whoever is using the launcher, by the name they chose for themselves.
        # Always present, so the slot does not appear and disappear as the name
        # is set or cleared.
        self.account_label = QLabel()
        self.account_label.setObjectName("AccountName")
        layout.addWidget(self.account_label)
        layout.addSpacing(2)
        self._refresh_sidebar_username()

        settings = QPushButton(" Settings")
        settings.setObjectName("GameEntry")
        settings.setCheckable(True)
        settings.setCursor(Qt.PointingHandCursor)
        settings.setIcon(QIcon(gameart.nav_glyph("settings", SIDEBAR_ICON)))
        settings.setIconSize(QSize(SIDEBAR_ICON, SIDEBAR_ICON))
        settings.clicked.connect(lambda: self._show(SETTINGS_KEY))
        self.nav_group.addButton(settings)
        self._entries[SETTINGS_KEY] = settings
        layout.addWidget(settings)

        # How many people have the launcher open, under Settings.
        count_row = QWidget()
        count_layout = QHBoxLayout(count_row)
        count_layout.setContentsMargins(13, 6, 13, 0)
        count_layout.setSpacing(7)

        self.presence_dot = StatusDot("idle")
        count_layout.addWidget(self.presence_dot, 0, Qt.AlignVCenter)

        self.presence_label = QLabel()
        self.presence_label.setObjectName("OnlineCount")
        count_layout.addWidget(self.presence_label, 1, Qt.AlignVCenter)
        layout.addWidget(count_row)
        self._refresh_presence()

        return side

    def _make_entry(self, game_id: str, title: str, year: str) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # Elided, not wrapped: the status dot sits on the button's right edge,
        # and a long title would otherwise run underneath it.
        metrics = QFontMetrics(self._entry_font())
        label = metrics.elidedText(title, Qt.ElideRight, ENTRY_TEXT_WIDTH)
        button = QPushButton(f" {label}")
        button.setObjectName("GameEntry")
        # The game's own icon once it is set up; a silhouette until then.
        button.setIcon(QIcon(self._mark_for(game_id, SIDEBAR_ICON)))
        button.setIconSize(QSize(SIDEBAR_ICON, SIDEBAR_ICON))
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(f"{title} ({year})")
        button.clicked.connect(lambda _=False, gid=game_id: self._show(gid))
        self.nav_group.addButton(button)
        self._entries[game_id] = button
        row.addWidget(button, 1)

        dot = StatusDot("idle")
        self._dots[game_id] = dot
        # Beside the button rather than over it: with an icon on the left there
        # is no longer slack at the right for the dot to overlap into.
        row.addSpacing(6)
        row.addWidget(dot, 0, Qt.AlignVCenter)
        row.addSpacing(4)

        return host

    @staticmethod
    def _entry_font() -> QFont:
        """The font the stylesheet gives a sidebar entry.

        Measured explicitly because a bare QPushButton has not been polished
        yet, so its own metrics would be the application default rather than
        the 13px medium the stylesheet applies.
        """
        font = QFont(theme.FONT)
        font.setPixelSize(13)
        font.setWeight(QFont.Medium)
        return font

    def _mark_for(self, game_id: str, size: int):
        """The game's icon at `size`, falling back to a painted silhouette."""
        game = by_id(game_id)
        if game is None:
            return QPixmap()
        install = self.config.install(game_id)
        return gameart.mark(game, install.path if install else None, size)

    def _refresh_entry_icons(self) -> None:
        """Re-read icons after an install path changes."""
        gameart.clear_cache()
        for game in GAMES:
            button = self._entries.get(game.id)
            if button is not None:
                button.setIcon(QIcon(self._mark_for(game.id, SIDEBAR_ICON)))

    # -- identity --------------------------------------------------------

    def _refresh_sidebar_username(self) -> None:
        """Show the launcher username above Settings.

        Kept in step with every route that can change it — first run, Settings,
        and a rename from the chat page — so the sidebar never shows a name the
        user has already replaced.
        """
        name = self.config.settings.username.strip()
        label = self.account_label
        # Elide rather than widen: the sidebar is a fixed 236px, and a long
        # name would otherwise push the layout out of shape.
        text = label.fontMetrics().elidedText(
            name or NO_USERNAME, Qt.ElideRight, SIDEBAR_WIDTH - 52
        )
        label.setText(text)
        label.setProperty("unset", not name)
        label.setToolTip(
            f"Signed in as {name}" if name
            else "No username yet — set one in Settings"
        )
        # The stylesheet keys off the `unset` property, so re-evaluate it.
        label.style().unpolish(label)
        label.style().polish(label)

    # -- presence --------------------------------------------------------

    def _on_presence_count(self, count: int) -> None:
        self._refresh_presence()

    def _on_presence_state(self, state: str) -> None:
        self._refresh_presence()

    def _refresh_presence(self) -> None:
        """Show the head count, or why there isn't one."""
        state = self.presence.state
        count = self.presence.count
        if state == "online":
            plural = "" if count == 1 else "s"
            self.presence_label.setText(f"{count} launcher{plural} open")
            self.presence_dot.set_state("good")
            tip = (
                f"{count} {'person is' if count == 1 else 'people are'} in the "
                "chat room right now, counting you."
            )
        elif state == "connecting":
            self.presence_label.setText("Counting…")
            self.presence_dot.set_state("warn")
            tip = "Connecting to the chat room to count who else is online."
        elif state == "disabled":
            self.presence_label.setText("Count is off")
            self.presence_dot.set_state("idle")
            tip = "Turn the online count back on in Settings."
        elif not identity.is_valid(self.config.settings.username):
            self.presence_label.setText("Set a username")
            self.presence_dot.set_state("idle")
            tip = "Pick a username in Settings to be counted."
        else:
            self.presence_label.setText("Offline")
            self.presence_dot.set_state("bad")
            tip = "Not connected. The launcher will keep trying."
        self.presence_label.setToolTip(tip)
        self.presence_dot.setToolTip(tip)

    def _set_online_count_enabled(self, value: bool) -> None:
        self.config.settings.show_online_count = value
        try:
            self.config.save()
        except OSError as exc:
            QMessageBox.warning(self, "Could not save settings", str(exc))
            return
        self.presence.refresh()
        self._refresh_presence()

    def _refresh_identity_controls(self) -> None:
        name = self.config.settings.username
        self.username_label.setText(name or "No username set")
        self.username_label.setStyleSheet(
            "" if name else f"color: {theme.FAINT};"
        )

    def _change_username(self) -> None:
        dialog = UsernameDialog(self.config.settings.username, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._set_username(dialog.username())

    def _set_username(self, name: str) -> None:
        self.config.settings.username = name
        try:
            self.config.save()
        except OSError as exc:
            QMessageBox.warning(self, "Could not save username", str(exc))
            return
        self._refresh_identity_controls()
        self._refresh_sidebar_username()
        if self._chat is not None:
            self._chat.apply_username(name)
        # Presence connects under this name, so a rename has to reconnect.
        self.presence.refresh()
        self._refresh_presence()
        self.flash_status(f"Username set to {name}")

    def _on_username_changed(self, name: str) -> None:
        """The chat page changed the name; keep Settings and sidebar in step."""
        self._refresh_identity_controls()
        self._refresh_sidebar_username()

    def prompt_first_run(self) -> None:
        """Ask for a username the first time the launcher is opened."""
        if self.config.settings.username:
            return
        dialog = UsernameDialog("", first_run=True, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self._set_username(dialog.username())
        else:
            # Skipped: chat asks again when they try to join.
            self._refresh_identity_controls()
            self._refresh_sidebar_username()

    # -- logo ------------------------------------------------------------

    def _refresh_logo(self) -> None:
        stored = branding.stored_logo()
        if stored is not None and self.logo.set_logo(stored):
            return
        if stored is not None:
            # Present but unreadable: drop it rather than show a broken slot.
            branding.clear_logo()
        # No usable logo of the user's own, so show the launcher's own mark
        # rather than an empty dashed box. Still click-to-replace.
        try:
            self.logo.set_logo(wordmark.default_logo())
        except Exception:
            self.logo.set_logo(None)

    def _choose_logo(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choose a logo image", "", branding.FILE_FILTER
        )
        if not chosen:
            return
        try:
            installed = branding.install_logo(Path(chosen))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Could not use that image", str(exc))
            return

        if not self.logo.set_logo(installed):
            branding.clear_logo()
            self.logo.set_logo(None)
            QMessageBox.warning(
                self,
                "Could not use that image",
                f"{Path(chosen).name} could not be decoded as an image.",
            )
            return

        self._refresh_logo_controls()
        self.flash_status("Logo updated")

    def _clear_logo(self) -> None:
        if QMessageBox.question(
            self,
            "Remove logo",
            "Remove the sidebar logo?\n\nThe image you chose it from is not "
            "touched.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        branding.clear_logo()
        self._refresh_logo()
        self._refresh_logo_controls()

    def _refresh_logo_controls(self) -> None:
        has_logo = branding.stored_logo() is not None
        self.logo_button.setText("Change image…" if has_logo else "Choose image…")
        self.logo_clear.setEnabled(has_logo)

    def _refresh_dots(self) -> None:
        for game in GAMES:
            dot = self._dots.get(game.id)
            if dot is None:
                continue
            install = self.config.install(game.id)
            if not install or not install.path:
                dot.set_state("idle")
                continue
            result = identify_as(Path(install.path), game)
            if result is None or not result.playable:
                dot.set_state("bad")
            elif result.missing_data or result.absent_with_residue:
                dot.set_state("warn")
            else:
                dot.set_state("good")

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def _build_settings_page(self) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(34, 28, 34, 24)
        layout.setSpacing(18)

        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        identity_card = Card(
            "Identity",
            "The name other people see in the chat room.",
        )
        identity_row = QHBoxLayout()
        identity_row.setSpacing(10)

        self.username_label = QLabel()
        self.username_label.setObjectName("CardTitle")
        identity_row.addWidget(self.username_label)

        change_name = QPushButton("Change username…")
        change_name.clicked.connect(self._change_username)
        identity_row.addWidget(change_name)
        identity_row.addStretch(1)
        identity_card.body.addLayout(identity_row)
        layout.addWidget(identity_card)

        appearance = Card(
            "Sidebar logo",
            "Shown at the top of the sidebar. The image is copied into the "
            "launcher's data folder, so moving the original will not break it.",
        )
        logo_row = QHBoxLayout()
        logo_row.setSpacing(9)
        self.logo_button = QPushButton()
        self.logo_button.clicked.connect(self._choose_logo)
        logo_row.addWidget(self.logo_button)

        self.logo_clear = QPushButton("Remove")
        self.logo_clear.setObjectName("Danger")
        self.logo_clear.clicked.connect(self._clear_logo)
        logo_row.addWidget(self.logo_clear)
        logo_row.addStretch(1)
        appearance.body.addLayout(logo_row)
        layout.addWidget(appearance)

        behaviour = Card("Behaviour")
        close_box = QCheckBox("Close the launcher after starting a game")
        close_box.setChecked(self.config.settings.close_on_launch)
        close_box.toggled.connect(self._set_close_on_launch)
        behaviour.body.addWidget(close_box)

        count_box = QCheckBox("Show how many launchers are open")
        count_box.setChecked(self.config.settings.show_online_count)
        count_box.toggled.connect(self._set_online_count_enabled)
        behaviour.body.addWidget(count_box)

        records_box = QCheckBox("Publish my lap records to the community board")
        records_box.setChecked(self.config.settings.records_submit)
        records_box.toggled.connect(self._set_records_submit)
        behaviour.body.addWidget(records_box)

        records_note = QLabel(
            "Off by default. When on, a time you set while the launcher is "
            "running is posted to the community board along with your "
            "username, the race and the car. Records are not verified — the "
            "game keeps them in a file on your own machine — so the board is "
            "a scoreboard rather than a record book."
        )
        records_note.setObjectName("Faint")
        records_note.setWordWrap(True)
        behaviour.body.addWidget(records_note)

        count_note = QLabel(
            "Counting means joining the chat room, so your username is visible "
            f"to anyone on {DEFAULT_HOST} while the launcher is open. Turn this "
            "off and the launcher makes no chat connection until you open the "
            "Chat Room yourself."
        )
        count_note.setObjectName("Faint")
        count_note.setWordWrap(True)
        behaviour.body.addWidget(count_note)
        layout.addWidget(behaviour)

        news_card = Card(
            "News",
            "Where the News tab reads announcements and video uploads from. "
            "This is a plain JSON file published by the community's relay — "
            "the launcher only ever reads it, and holds no Discord credentials "
            "of its own.",
        )
        news_row = QHBoxLayout()
        news_row.setSpacing(9)

        self.news_url_field = QLineEdit(self.config.settings.news_url)
        self.news_url_field.setPlaceholderText(
            "https://example.com/news.json — leave empty to turn the tab off"
        )
        self.news_url_field.editingFinished.connect(self._save_news_url)
        news_row.addWidget(self.news_url_field, 1)

        news_check = QPushButton("Check now")
        news_check.setObjectName("Ghost")
        news_check.clicked.connect(self._check_news_now)
        news_row.addWidget(news_check)
        news_card.body.addLayout(news_row)
        layout.addWidget(news_card)

        storage = Card(
            "Storage",
            "Mods, backups and settings live here. Nothing is written into a "
            "game folder except by the mod manager.",
        )
        path_label = QLabel(str(paths.app_root()))
        path_label.setObjectName("Mono")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        storage.body.addWidget(path_label)

        open_row = QHBoxLayout()
        open_btn = QPushButton("Open data folder")
        open_btn.setObjectName("Ghost")
        open_btn.clicked.connect(self._open_data_folder)
        open_row.addWidget(open_btn)
        open_row.addStretch(1)
        storage.body.addLayout(open_row)
        layout.addWidget(storage)

        games_card = Card("Configured games")
        self.configured_list = QVBoxLayout()
        self.configured_list.setSpacing(8)
        games_card.body.addLayout(self.configured_list)
        layout.addWidget(games_card)
        self._games_card = games_card

        about = QLabel(
            f"{APP_NAME} {__version__} — a single front end for the Madness "
            "games. Midtown Madness support is built on Open1560."
        )
        about.setObjectName("Faint")
        about.setWordWrap(True)
        layout.addWidget(about)

        layout.addStretch(1)
        self._pages[SETTINGS_KEY] = scrollable(host)
        self.stack.addWidget(self._pages[SETTINGS_KEY])

    def _refresh_configured_list(self) -> None:
        while self.configured_list.count():
            item = self.configured_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        any_configured = False
        for game in GAMES:
            install = self.config.install(game.id)
            if not install or not install.path:
                continue
            any_configured = True
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)

            label = QLabel(f"{game.title}")
            row_layout.addWidget(label)

            path = QLabel(install.path)
            path.setObjectName("Mono")
            row_layout.addWidget(path, 1)

            forget = QPushButton("Forget")
            forget.setObjectName("Danger")
            forget.clicked.connect(lambda _=False, gid=game.id: self._forget(gid))
            row_layout.addWidget(forget)

            self.configured_list.addWidget(row)

        if not any_configured:
            empty = QLabel("No games configured yet.")
            empty.setObjectName("Faint")
            self.configured_list.addWidget(empty)

    def _library_page(self) -> "LibraryPage":
        """Built on first use, then kept: refreshing it is cheap."""
        if self._library is None:
            self._library = LibraryPage(self.config)
            self._library.opened.connect(self._show)
            self._library.played.connect(self._play_from_library)
            self._library.status_message.connect(self.flash_status)
            self._pages[LIBRARY_KEY] = self._library
            self.stack.addWidget(self._library)
        return self._library

    def _play_from_library(self, game_id: str) -> None:
        """Play from a card: open the game, then press its Play button.

        Routed through the game page rather than duplicating the launch path,
        so elevation, the CPU pin and the hook all behave identically to
        starting the game from its own Play tab.
        """
        self._show(game_id)
        page = self._pages.get(game_id)
        if isinstance(page, GamePage):
            page.start()

    # ------------------------------------------------------------------
    # Lap records
    # ------------------------------------------------------------------

    def _load_race_tables(self) -> None:
        """Adopt Midtown Madness's race names, from the install if configured.

        Without this every record that names its race rather than numbering
        it — which is all of them from speedrun.com — fails to place and the
        board shows nothing.
        """
        install = self.config.install("mm1")
        mm1_records.load_city(
            Path(install.path) if install and install.path else None
        )

    def _import_existing_records(self) -> None:
        """Take in whatever the games already have on disk.

        A player who has owned Midtown Madness for years arrives with a full
        table of times. Without this the tab is empty until they beat one of
        their own records, which for a good driver could be never.

        Only what is genuinely new to the store is published, so this runs on
        every start without re-posting anything, and improvements made outside
        the launcher are picked up too.
        """
        from ..records.session import existing_records

        fresh: list = []
        for game_id in record_session.GAMES_WITH_RECORDS:
            install = self.config.install(game_id)
            if not install or not install.path:
                continue
            try:
                fresh += existing_records(
                    Path(install.path), game_id, self.config.settings.username
                )
            except OSError:
                continue
        # Anything the user has deleted stays deleted. Without this the
        # game's own tables put it straight back on the next launch, and
        # publish it again.
        gone = record_store.forgotten()
        fresh = [r for r in fresh if record_store.key_id(r) not in gone]
        if not fresh:
            return

        before = {(r.game, r.board, r.difficulty, r.race): r.seconds
                  for r in self.records}
        merged = record_store.merge(self.records, fresh)
        added = [
            r for r in merged
            if before.get((r.game, r.board, r.difficulty, r.race)) is None
            or r.seconds < before[(r.game, r.board, r.difficulty, r.race)]
        ]
        if not added:
            return
        self.records = merged
        record_store.save(self.records)
        self._maybe_submit(added)

    def adopt_record_watcher(self, watcher) -> None:
        """Take ownership of a watcher for a session that has just started."""
        watcher.setParent(self)
        watcher.found.connect(self._on_records_found)
        watcher.rejected.connect(self._on_record_rejected)
        watcher.finished.connect(self._on_session_finished)
        self._watchers.append(watcher)

    def all_records(self) -> list:
        """Everything to show: this machine's times and the community board.

        Merged rather than shown separately, so a race has one row with the
        fastest time on it whoever set it. A local record always wins a tie,
        because it is the one the launcher actually watched being set.
        """
        merged = record_store.merge(
            record_store.from_feed(self.news.feed.records), self.records
        )
        return merged

    def _on_records_found(self, entries: list) -> None:
        self.records = record_store.merge(self.records, entries)
        record_store.save(self.records)

        count = len(entries)
        best = min(entries, key=lambda e: e.seconds)
        self.flash_status(
            f"{count} new record{'s' if count != 1 else ''} — "
            f"{best.race_name} in {best.formatted}"
        )
        if self._lap_records is not None:
            self._lap_records.refresh()
        self._maybe_submit(entries)

    def _on_session_finished(self, found: int) -> None:
        """Say something at the end of every watched session, including none.

        The game only stores a time when it beats the one already there, and
        only when the race was placed well enough, so most sessions produce
        nothing. Reporting that plainly is the difference between a quiet
        feature and one that looks broken.
        """
        if found:
            return
        self.flash_status(
            "No new records this session — Midtown Madness only saves a time "
            "when it beats your stored best for that race and difficulty."
        )

    def _on_record_rejected(self, what: str, why: str) -> None:
        # Said out loud rather than swallowed: a personal best that quietly
        # fails to count is worse than one that says why.
        self.flash_status(f"Record not counted — {what}: {why}")

    def _maybe_submit(self, entries: list) -> None:
        """Send records to the community board, if the user asked us to."""
        if not self.config.settings.records_submit:
            return
        # Each game posts to its own channel, so the records are grouped by
        # game and each group goes to its own webhook.
        pending = self._unsent + list(entries)
        self._unsent = []
        by_game: dict[str, list] = {}
        for entry in pending:
            by_game.setdefault(entry.game, []).append(entry)

        sent = 0
        for game, group in by_game.items():
            webhook = self._webhook_for(game)
            if not webhook:
                # Held until the feed arrives with one, rather than dropped.
                self._unsent.extend(group)
                continue
            sent += self.submitter.submit(webhook, group)
        if sent:
            self.flash_status(
                f"Sent {sent} record{'s' if sent != 1 else ''} to the board"
            )
        return

    def _webhook_for(self, game: str) -> str:
        """Where this game's records go, or nowhere.

        Only this game's own entry counts. There is deliberately no fallback
        to another game's webhook: falling back published Midtown Madness 2's
        entire imported history into the Midtown Madness channel, because the
        feed had not yet been rebuilt with the per-game map and the single
        old URL looked like a reasonable default. It was not. A record with
        nowhere to go waits; it does not go somewhere else.

        The per-machine override in Settings still wins, since it is set by
        hand for testing against one channel.
        """
        override = self.config.settings.records_webhook
        if override:
            return override
        return (self.news.feed.records_webhooks or {}).get(game, "")

    def _on_submit_failed(self, entry, reason: str) -> None:
        self.flash_status(f"Could not send {entry.race_name}: {reason}")

    def _records_page(self) -> "RecordsPage":
        if self._lap_records is None:
            self._lap_records = RecordsPage(self.config, self.all_records)
            self._lap_records.refresh_requested.connect(self._refresh_records_now)
            self._lap_records.fetched_at = lambda: self.news.fetched_at
            self._pages[RECORDS_KEY] = self._lap_records
            self.stack.addWidget(self._lap_records)
        return self._lap_records

    def _news_page(self) -> "NewsPage":
        """Built on first use. The feed itself is already loaded by then."""
        if self._news is None:
            self._news = NewsPage(self.news, self.thumbs)
            self._news.seen.connect(self._refresh_news_entry)
            self._pages[NEWS_KEY] = self._news
            self.stack.addWidget(self._news)
        return self._news

    def _refresh_records_now(self) -> None:
        """The Refresh button on the Lap Records page.

        Forced past the throttle, because somebody pressing Refresh has a
        reason to think the board is behind and being told to wait is not an
        answer.
        """
        self.news.refresh(force=True)
        self.flash_status("Checking the community board…")

    def _on_news_updated(self, _feed: object) -> None:
        self._refresh_news_entry()
        # A feed carries the community board, so a launcher sitting on the Lap
        # Records tab has to redraw when one arrives. Without this a record
        # somebody else set only appears after navigating away and back.
        if self._lap_records is not None:
            self._lap_records.refresh()
        # The feed carries the webhook, so anything held back at startup can
        # go now.
        if self._unsent and self.config.settings.records_submit:
            waiting, self._unsent = self._unsent, []
            self._maybe_submit(waiting)

    def _on_news_state(self, _state: str) -> None:
        self._refresh_news_entry()

    def _refresh_news_entry(self) -> None:
        """Mark the sidebar entry when there is something the user has not read.

        The count is deliberately quiet — a number after the label, the same
        shape the chat room uses — rather than a coloured badge. News is not
        urgent, and the sidebar already carries a status dot per game.
        """
        unread = self.news.unread()
        self.news_entry.setText(" News" + (f"      {unread}" if unread else ""))
        if unread:
            plural = "s" if unread != 1 else ""
            self.news_entry.setToolTip(f"{unread} new post{plural} since you last looked")
        elif self.news.state == "error":
            self.news_entry.setToolTip(
                self.news.error or "Could not reach the news source"
            )
        elif not self.news.url:
            self.news_entry.setToolTip("No news source set — see Settings")
        else:
            self.news_entry.setToolTip("Announcements and new videos")

    def _chat_page(self) -> "ChatPage":
        """The chat page is built on first use; it holds a live connection."""
        if self._chat is None:
            self._chat = ChatPage(self.config, client=self.presence.client)
            self._chat.joined_chat.connect(self.presence.note_user_connected)
            self._chat.left_chat.connect(self.presence.note_user_disconnected)
            self._chat.online_count_changed.connect(self._on_online_count)
            self._chat.username_changed.connect(self._on_username_changed)
            self._pages[CHAT_KEY] = self._chat
            self.stack.addWidget(self._chat)
        return self._chat

    def _on_online_count(self, count: int) -> None:
        self.chat_entry.setText(f" Chat Room" + (f"      {count}" if count else ""))
        self.chat_entry.setToolTip(
            f"{count} user{'s' if count != 1 else ''} in the chat room"
            if count
            else "Not connected to the chat room"
        )

    def _page_for(self, game_id: str) -> QWidget:
        """Build (or rebuild) the page for a game based on current config."""
        game = by_id(game_id)
        assert game is not None

        install = self.config.install(game_id)
        if install and install.path:
            page = GamePage(game, self.config)
            page.install_changed.connect(self._on_install_changed)
        else:
            page = SetupPage(game, self.config)
            page.located.connect(self._on_game_located)
        return page

    def _show(self, key: str) -> None:
        # Whatever we move to, the Overview backdrops stop decoding, and the
        # chat page learns whether it is the thing on screen.
        for other_key, other in self._pages.items():
            if other_key != key and isinstance(other, GamePage):
                other.overview.set_active(False)
        if self._chat is not None:
            self._chat.set_visible_to_user(key == CHAT_KEY)

        if key == NEWS_KEY:
            page = self._news_page()
            self.stack.setCurrentWidget(page)
            self.news_entry.setChecked(True)
            # After the page is current, so its own visibility check is true
            # when it decides whether the arriving feed counts as read.
            page.set_visible_to_user(True)
            self._refresh_news_entry()
            self._apply_accent(theme.DEFAULT_ACCENT)
            return

        if key == RECORDS_KEY:
            page = self._records_page()
            # Ask for a fresh feed on the way in. Throttled by the service, so
            # opening the tab repeatedly costs one request every few minutes,
            # but somebody who opens it to check the board gets the board as
            # it is rather than as it was when the launcher started.
            self.news.refresh()
            page.refresh()
            self.stack.setCurrentWidget(page)
            self.records_entry.setChecked(True)
            self._apply_accent(theme.DEFAULT_ACCENT)
            return

        if key == SETTINGS_KEY:
            self._refresh_configured_list()
            self._refresh_logo_controls()
            self._refresh_identity_controls()
            self.news_url_field.setText(self.config.settings.news_url)
            self.stack.setCurrentWidget(self._pages[SETTINGS_KEY])
            self._entries[SETTINGS_KEY].setChecked(True)
            self._apply_accent(theme.DEFAULT_ACCENT)
            return

        if key == LIBRARY_KEY:
            page = self._library_page()
            page.refresh()
            self.stack.setCurrentWidget(page)
            self.library_entry.setChecked(True)
            self._apply_accent(theme.DEFAULT_ACCENT)
            return

        if key == CHAT_KEY:
            self.stack.setCurrentWidget(self._chat_page())
            self.chat_entry.setChecked(True)
            self._apply_accent(theme.DEFAULT_ACCENT)
            return

        if key not in self._pages:
            page = self._page_for(key)
            self._pages[key] = page
            self.stack.addWidget(page)

        page = self._pages[key]
        if isinstance(page, GamePage):
            page.refresh()
            page.overview.set_active(page.tabs.currentWidget() is page.overview)
        self.stack.setCurrentWidget(page)
        button = self._entries.get(key)
        if button:
            button.setChecked(True)

        game = by_id(key)
        self._apply_accent(game.accent if game else theme.DEFAULT_ACCENT)
        self._refresh_dots()

    def _rebuild_page(self, game_id: str) -> None:
        old = self._pages.pop(game_id, None)
        if old is not None:
            if hasattr(old, "release"):
                old.release()
            self.stack.removeWidget(old)
            old.setParent(None)
            old.deleteLater()
        self._show(game_id)

    def _select_initial(self) -> None:
        # The library is the front door: it shows every game at once instead of
        # dropping into whichever one happened to be configured first.
        self._show(LIBRARY_KEY if GAMES else SETTINGS_KEY)

    # ------------------------------------------------------------------
    # Reactions
    # ------------------------------------------------------------------

    def _apply_accent(self, accent: str) -> None:
        """No longer needed: each game page styles its own accent.

        Kept as a no-op so the call sites read the same; the application-wide
        stylesheet is set once at startup and never replaced.
        """
        return

    def _on_game_located(self, game_id: str) -> None:
        self._rebuild_page(game_id)
        self._refresh_entry_icons()
        if self._library is not None:
            self._library.refresh()
        self.flash_status("Game folder saved")

    def _on_install_changed(self) -> None:
        # A newly configured install may carry racepacks with their own race
        # table, which is the authority over the built-in one.
        self._load_race_tables()
        self._refresh_dots()
        self._refresh_entry_icons()
        if self._library is not None:
            self._library.refresh()

    def _save_news_url(self) -> None:
        """Store a new feed URL and fetch from it straight away.

        Rejects anything that is not http(s) rather than saving it silently:
        a typo here otherwise shows up much later as a News tab that never
        loads, with nothing on screen to say why.
        """
        # editingFinished fires again when the warning below takes focus away
        # from the field, which without this would stack dialogs.
        if self._saving_news_url:
            return
        entered = self.news_url_field.text().strip()
        if entered == self.config.settings.news_url:
            return
        self._saving_news_url = True
        try:
            self._apply_news_url(entered)
        finally:
            self._saving_news_url = False

    def _apply_news_url(self, entered: str) -> None:
        if entered and not safe_url(entered):
            QMessageBox.warning(
                self,
                "That is not a usable address",
                "The news source has to be an http:// or https:// URL "
                "pointing at a JSON file.",
            )
            self.news_url_field.setText(self.config.settings.news_url)
            return

        self.config.settings.news_url = entered
        try:
            self.config.save()
        except OSError as exc:
            QMessageBox.warning(self, "Could not save settings", str(exc))
            return
        self.news.refresh(force=True)
        self._refresh_news_entry()
        self.flash_status("News source updated" if entered else "News source cleared")

    def _check_news_now(self) -> None:
        self._save_news_url()
        self.news.refresh(force=True)
        self.flash_status(
            "Checking for news…" if self.news.url else "No news source set"
        )

    def _set_records_submit(self, value: bool) -> None:
        self.config.settings.records_submit = value
        try:
            self.config.save()
        except OSError as exc:
            QMessageBox.warning(self, "Could not save settings", str(exc))
            return
        self.flash_status(
            "Lap records will be published" if value
            else "Lap records stay on this machine"
        )

    def _set_close_on_launch(self, value: bool) -> None:
        self.config.settings.close_on_launch = value
        try:
            self.config.save()
        except OSError as exc:
            QMessageBox.warning(self, "Could not save settings", str(exc))

    def _open_data_folder(self) -> None:
        import os

        root = paths.app_root()
        paths.ensure_dirs(root)
        os.startfile(str(root))  # noqa: S606 - Windows shell open

    def _forget(self, game_id: str) -> None:
        game = by_id(game_id)
        name = game.title if game else game_id
        if QMessageBox.question(
            self,
            "Forget game",
            f"Remove the saved folder for {name}?\n\n"
            "Mods stay in the launcher's library and installed mod files stay "
            "in the game folder. Nothing in the game folder is deleted.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self.config.forget(game_id)
        try:
            self.config.save()
        except OSError as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self._rebuild_page(game_id)
        self._refresh_configured_list()
        self._refresh_dots()
        self._refresh_entry_icons()
        if self._library is not None:
            self._library.refresh()

    def closeEvent(self, event):  # noqa: N802 - Qt naming
        self.presence.stop()
        # Requests still in flight would otherwise deliver into a half torn
        # down window.
        self.news.stop()
        self.thumbs.stop()
        # Tear down media players explicitly; leaving them to garbage
        # collection can hang the process on the Windows backend.
        for page in self._pages.values():
            if hasattr(page, "release"):
                page.release()
        super().closeEvent(event)

    def flash_status(self, message: str, msecs: int = 6000) -> None:
        self.statusBar().showMessage(message, msecs)
        QTimer.singleShot(
            msecs, lambda: self.statusBar().showMessage(f"{APP_NAME} {__version__}")
        )
