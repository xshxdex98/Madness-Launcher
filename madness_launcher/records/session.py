"""Watching one play session for new lap records.

The launcher takes a snapshot of the game's own best-time tables just before
starting it, waits for the process to exit, and snapshots again. Anything that
improved in between was driven while the launcher was watching.

That "while the launcher was watching" is the only integrity property worth
much here, and it is worth stating what it is not. It does not prove a time is
genuine — the .dat is a file on the player's disk and a float in it can be
edited. What it does rule out is the easy case: pasting somebody else's save
in, or hand-writing a table full of records, and having the launcher publish
all of it. A submission has to appear during a session the launcher itself
started, be a stock car, and be a lap that could physically fit inside the
time the game was actually open.

Polled rather than threaded, for the same reason the IRC client is: the whole
application runs on the GUI thread, and a poll every few seconds costs
nothing next to a game.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from . import mm1

# How often to ask whether the game has exited.
POLL_MS = 3000

# The game writes its tables as it shuts down, and the process can be gone
# before the last write has landed. Cheap insurance against reading a file
# mid-rewrite.
SETTLE_MS = 1500

# A session that has run this long is almost certainly someone who left the
# game open, not a race. The watcher stops polling rather than living forever.
MAX_SESSION_HOURS = 12

# Nobody drives a competitive lap in under this. Anything faster is a mistake
# in the file or an attempt at one.
MIN_PLAUSIBLE_SECONDS = 8.0

# Allowance for the game already being loaded when the clock started, plus
# menu time. A lap cannot take longer than the session that produced it, but
# the session is measured generously.
SESSION_SLACK_SECONDS = 30.0

# Games whose record tables the launcher can read. Both keep them the
# same way; profiles.py holds what differs.
GAMES_WITH_RECORDS = ("mm1", "mm2")


@dataclass
class Submission:
    """One record, ready to be shown or sent."""

    game: str
    board: str
    # Which city the race belongs to. One game can have more than one,
    # and its race numbering restarts in each — London race 0 and SF
    # race 0 are different races that would otherwise share an identity.
    city: str
    race: int
    race_name: str
    race_kind: str
    difficulty: str
    car: str
    car_name: str
    seconds: float
    # The name on the in-game profile, which is not the launcher username and
    # is worth keeping: it is what the game itself recorded.
    driver: str
    username: str = ""
    set_at: str = ""
    # Slugs of the mods enabled at launch. Empty is what makes a run vanilla.
    mods: list[str] = field(default_factory=list)
    # Where the time came from: this launcher, or an external leaderboard.
    # Shown in the table, because a moderator-verified speedrun.com run and a
    # self-reported one are not the same claim.
    source: str = "launcher"
    # Proof, when the source has any — a link to the verified run.
    url: str = ""

    @property
    def formatted(self) -> str:
        minutes, seconds = divmod(self.seconds, 60)
        return f"{int(minutes)}:{seconds:06.3f}" if minutes else f"{seconds:.3f}"

    def as_dict(self) -> dict:
        return {
            "game": self.game,
            "board": self.board,
            "city": self.city,
            "race": self.race,
            "race_name": self.race_name,
            "race_kind": self.race_kind,
            "difficulty": self.difficulty,
            "car": self.car,
            "car_name": self.car_name,
            "seconds": round(self.seconds, 3),
            "driver": self.driver,
            "username": self.username,
            "set_at": self.set_at,
            "mods": sorted(self.mods),
            "source": self.source,
            "url": self.url,
        }


def plausible(entry: Submission, session_seconds: float) -> tuple[bool, str]:
    """Whether a record could have been set in the session that produced it.

    Deliberately a small number of cheap, non-negotiable checks rather than an
    attempt at anti-cheat. Each one rules out a specific way the data can be
    obviously wrong; none of them can tell a good driver from a patient one
    with a hex editor.
    """
    if entry.board not in (mm1.BOARD_VANILLA, mm1.BOARD_MODDED):
        return False, "not a stock car"
    if entry.seconds < MIN_PLAUSIBLE_SECONDS:
        return False, f"{entry.formatted} is faster than anyone drives"
    if entry.seconds > mm1.MAX_TIME:
        return False, "longer than an hour"
    if entry.seconds > session_seconds + SESSION_SLACK_SECONDS:
        return False, (
            f"a {entry.formatted} lap does not fit in a "
            f"{int(session_seconds)}s session"
        )
    if entry.race < 0 or not entry.race_name:
        return False, "unknown race"
    return True, ""


SOURCE_LAUNCHER = "launcher"
SOURCE_IMPORTED = "imported"


def existing_records(
    install: Path, game_id: str = "mm1", username: str = ""
) -> list[Submission]:
    """Everything already in the game's tables, as records.

    A player who has had the game for years arrives with a full table and,
    without this, an empty board until they beat one of their own times. Their
    history is right there on disk and belongs in the tab.

    Marked as imported rather than passed off as witnessed. The launcher did
    not see these driven and cannot say when or how they were set, so they
    carry a different source and the board shows which is which. Publishing
    them is still governed by the opt-in.
    """
    unapproved = mm1.unapproved_archives(Path(install), game_id)
    out: list[Submission] = []
    for record in mm1.snapshot(Path(install), game=game_id).values():
        board = mm1.classify(record.car, unapproved, game_id)
        if board is None or not (MIN_PLAUSIBLE_SECONDS <= record.seconds <= mm1.MAX_TIME):
            continue
        out.append(
            Submission(
                game=game_id,
                board=board,
                city=record.city,
                race=record.race,
                race_name=record.race_name,
                race_kind=record.kind,
                difficulty=record.difficulty,
                car=record.car,
                car_name=record.car_name,
                seconds=record.seconds,
                driver=record.driver,
                username=username,
                set_at="",
                mods=unapproved,
                source=SOURCE_IMPORTED,
            )
        )
    return out


class RecordWatcher(QObject):
    """Watches one running game and reports what improved when it exits."""

    # list[Submission] — everything witnessed and plausible.
    found = Signal(list)
    # A record was seen but thrown out, with the reason. Surfaced rather than
    # swallowed: silently dropping somebody's personal best is worse than
    # telling them why it did not count.
    rejected = Signal(str, str)
    # The session ended. Carries how many records came out of it, including
    # none. Emitted even when nothing was found, because silence is not an
    # answer: a player who finishes a race and sees nothing cannot tell "you
    # did not beat your time" from "this is broken", and will assume broken.
    finished = Signal(int)

    def __init__(
        self,
        game_id: str,
        install: Path,
        process,
        username: str = "",
        mods: list[str] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.game_id = game_id
        self.install = Path(install)
        self.process = process
        self.username = username
        # What the game will actually load, judged from the folder itself.
        # Taken now rather than at the end, so archives added mid-session
        # cannot retroactively qualify a run for the vanilla board.
        self.unapproved = mm1.unapproved_archives(self.install, game_id)
        self.mods = self.unapproved or list(mods or [])
        self._started = time.monotonic()
        self._before = mm1.snapshot(self.install, game=self.game_id)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._check)

    @classmethod
    def supported(cls, game_id: str) -> bool:
        return game_id in GAMES_WITH_RECORDS

    def start(self) -> None:
        if self._before or self.install.is_dir():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    # -- polling ---------------------------------------------------------

    def _check(self) -> None:
        elapsed = time.monotonic() - self._started
        if elapsed > MAX_SESSION_HOURS * 3600:
            self._timer.stop()
            return
        try:
            running = self.process.poll() is None
        except Exception:
            # An elevated launch hands back a raw handle rather than a Popen;
            # if it cannot be polled there is nothing to wait for.
            self._timer.stop()
            return
        if running:
            return
        self._timer.stop()
        QTimer.singleShot(SETTLE_MS, self._collect)

    def _collect(self) -> None:
        session_seconds = time.monotonic() - self._started
        after = mm1.snapshot(self.install, game=self.game_id)
        improved = mm1.improvements(self._before, after)

        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        good: list[Submission] = []
        for record in improved:
            board = mm1.classify(record.car, self.unapproved, self.game_id)
            entry = Submission(
                game=self.game_id,
                board=board or "",
                city=record.city,
                race=record.race,
                race_name=record.race_name,
                race_kind=record.kind,
                difficulty=record.difficulty,
                car=record.car,
                car_name=record.car_name,
                seconds=record.seconds,
                driver=record.driver,
                username=self.username,
                set_at=stamp,
                mods=self.mods,
                source=SOURCE_LAUNCHER,
            )
            ok, why = plausible(entry, session_seconds)
            if ok:
                good.append(entry)
            else:
                self.rejected.emit(f"{entry.race_name} {entry.formatted}", why)

        if good:
            self.found.emit(good)
        self.finished.emit(len(good))
