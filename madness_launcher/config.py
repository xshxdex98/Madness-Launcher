"""Persistent launcher state.

Written atomically: a partially flushed config would lose every configured
game path, which is the one thing the user cannot easily reconstruct.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import paths

CONFIG_VERSION = 1

# The published news feed: the relay's output, committed to the launcher's own
# repository and served raw. Shipping a default means a user never has to know
# the URL exists; Settings can still override it per-machine, and clearing it
# there turns the News tab off without disabling anything else.
DEFAULT_NEWS_URL = (
    "https://raw.githubusercontent.com/xshxdex98/Madness-Launcher/main/news.json"
)


@dataclass
class InstallConfig:
    """Everything the launcher remembers about one configured game."""

    path: str = ""
    # ExeTarget.id, or CUSTOM_TARGET when custom_exe names the executable.
    target: str = ""
    # Filename of a user-nominated executable, for repacks that rename it.
    custom_exe: str = ""
    # Video looped behind the Overview tab. Referenced in place, never copied.
    background_video: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    extra_args: str = ""
    # Mod slug -> enabled. Ordering/priority lives in the mod's own manifest.
    enabled_mods: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstallConfig":
        return cls(
            path=data.get("path", ""),
            target=data.get("target", ""),
            custom_exe=data.get("custom_exe", ""),
            background_video=data.get("background_video", ""),
            options=dict(data.get("options", {})),
            extra_args=data.get("extra_args", ""),
            enabled_mods=list(data.get("enabled_mods", [])),
        )


@dataclass
class Settings:
    close_on_launch: bool = False
    confirm_mod_changes: bool = True
    # The name shown in the chat room. Empty until first run has been through.
    username: str = ""
    # Chat is opt-in: joining connects to a public IRC network, which is not
    # something to do behind the user's back on startup.
    chat_autojoin: bool = False
    # Show a live head count in the sidebar. Being counted means being in the
    # room, and the room is public, so this is stated plainly in Settings and
    # can be turned off; with it off the launcher makes no chat connection
    # until the user opens the Chat Room themselves.
    show_online_count: bool = True
    chat_sound: bool = True
    chat_host: str = ""
    chat_port: int = 0
    chat_channel: str = ""
    chat_tls: bool = True
    # Where the News tab reads its feed from. Empty until someone points it at
    # a relay; the tab explains itself rather than failing when it is unset.
    news_url: str = DEFAULT_NEWS_URL
    # Timestamp of the newest item the user has actually seen, so the sidebar
    # can mark unread posts. ISO 8601; empty on a fresh install, which counts
    # as "nothing is unread" rather than "everything is".
    news_last_seen: str = ""
    # Sending lap records to the community board is opt-in. It publishes
    # the username under a time in a public channel, which is not
    # something to start doing on somebody's behalf.
    records_submit: bool = False
    # Normally delivered in the news feed so it can be rotated without a
    # rebuild; set here only to point one machine somewhere else.
    records_webhook: str = ""
    # Colours the user has changed, as {palette field: "#RRGGBB"}. Only the
    # differences from the shipped palette are kept, so a future change to the
    # defaults reaches anyone who has not overridden that particular colour.
    theme: dict[str, str] = field(default_factory=dict)
    # Per-game overrides, {game id: same shape}. A game with no entry uses the
    # theme above; an entry is created only when someone customises that game,
    # which is why absent and empty have to mean different things here.
    game_themes: dict[str, dict[str, str]] = field(default_factory=dict)

    @staticmethod
    def _colours(raw: Any) -> dict[str, str]:
        """A {field: colour} mapping, discarding anything that is not one."""
        if not isinstance(raw, dict):
            return {}
        return {
            str(k): str(v)
            for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, str)
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        return cls(
            close_on_launch=bool(data.get("close_on_launch", False)),
            confirm_mod_changes=bool(data.get("confirm_mod_changes", True)),
            username=str(data.get("username", "")),
            chat_autojoin=bool(data.get("chat_autojoin", False)),
            show_online_count=bool(data.get("show_online_count", True)),
            chat_sound=bool(data.get("chat_sound", True)),
            chat_host=str(data.get("chat_host", "")),
            chat_port=int(data.get("chat_port", 0) or 0),
            chat_channel=str(data.get("chat_channel", "")),
            chat_tls=bool(data.get("chat_tls", True)),
            news_url=str(data.get("news_url", DEFAULT_NEWS_URL)),
            news_last_seen=str(data.get("news_last_seen", "")),
            records_submit=bool(data.get("records_submit", False)),
            records_webhook=str(data.get("records_webhook", "")),
            theme=cls._colours(data.get("theme")),
            game_themes=cls._game_themes(data.get("game_themes")),
        )

    @classmethod
    def _game_themes(cls, raw: Any) -> dict[str, dict[str, str]]:
        # `or {}` is not enough of a guard: a non-empty value of the wrong
        # type gets through it and then fails on .items(), which would stop
        # the launcher starting over an edited config file.
        if not isinstance(raw, dict):
            return {}
        return {
            str(game_id): cls._colours(colours)
            for game_id, colours in raw.items()
            if isinstance(colours, dict)
        }


class Config:
    def __init__(self) -> None:
        self.installs: dict[str, InstallConfig] = {}
        self.settings = Settings()

    # -- persistence -----------------------------------------------------

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        f = paths.config_file()
        if not f.is_file():
            return cfg
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt config must not stop the launcher from starting; the
            # user can simply re-add their games.
            return cfg
        for game_id, raw in (data.get("installs") or {}).items():
            if isinstance(raw, dict):
                cfg.installs[game_id] = InstallConfig.from_dict(raw)
        cfg.settings = Settings.from_dict(data.get("settings") or {})
        return cfg

    def save(self) -> None:
        paths.ensure_dirs(paths.app_root())
        payload = {
            "version": CONFIG_VERSION,
            "installs": {k: asdict(v) for k, v in self.installs.items()},
            "settings": asdict(self.settings),
        }
        target = paths.config_file()
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, target)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise

    # -- accessors -------------------------------------------------------

    def install(self, game_id: str) -> InstallConfig | None:
        return self.installs.get(game_id)

    def install_or_new(self, game_id: str) -> InstallConfig:
        if game_id not in self.installs:
            self.installs[game_id] = InstallConfig()
        return self.installs[game_id]

    def forget(self, game_id: str) -> None:
        self.installs.pop(game_id, None)

    def is_configured(self, game_id: str) -> bool:
        inst = self.installs.get(game_id)
        return bool(inst and inst.path)
