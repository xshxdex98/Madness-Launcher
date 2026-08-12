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

from . import motocross, reader

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

# Games that keep their records the AGE way — one save file of fixed-size
# records. profiles.py holds what differs between them.
AGE_GAMES = ("mm1", "mm2")

# Motocross Madness keeps a separate table beside each track instead, so it
# is read by its own module. See records/motocross.py.
MOTOCROSS_GAMES = ("mcm2",)

# Games whose record tables the launcher can read at all.
GAMES_WITH_RECORDS = AGE_GAMES + MOTOCROSS_GAMES


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
    # The track's filename, for a game whose tracks are files rather than a
    # fixed list. Carried separately from race_name because the name is
    # learned and the filename is what it is learned against: a launcher
    # that has never ridden the track needs the pair to show the real name.
    track: str = ""

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
            **({"track": self.track} if self.track else {}),
        }


def plausible(entry: Submission, session_seconds: float) -> tuple[bool, str]:
    """Whether a record could have been set in the session that produced it.

    Deliberately a small number of cheap, non-negotiable checks rather than an
    attempt at anti-cheat. Each one rules out a specific way the data can be
    obviously wrong; none of them can tell a good driver from a patient one
    with a hex editor.
    """
    if entry.board not in (reader.BOARD_VANILLA, reader.BOARD_MODDED):
        return False, "not a stock car"
    if entry.seconds < MIN_PLAUSIBLE_SECONDS:
        return False, f"{entry.formatted} is faster than anyone drives"
    if entry.seconds > reader.MAX_TIME:
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


def _from_moto(
    record: "motocross.MotoRecord",
    username: str,
    bike_class: str,
    source: str,
    set_at: str = "",
) -> Submission:
    """One Motocross time as a Submission.

    Everything the board already knows how to show, mapped onto the fields it
    already has. The discipline goes in `city` because that is the field the
    records page turns into tabs, and Supercross against Enduro is exactly
    the split worth having tabs for. The class goes in `car` because it is
    what the time was set on, which is what `car` means.
    """
    return Submission(
        game=record.game,
        board=record.board,
        city=record.folder.upper(),
        race=record.race,
        race_name=record.race_name,
        race_kind=record.kind,
        difficulty="",
        car=bike_class,
        car_name=bike_class,
        track=record.track,
        seconds=record.seconds,
        driver=record.driver,
        username=username,
        set_at=set_at,
        # A modded board here means a track the game did not ship, and the
        # track is named in the row already. Listing it again as a mod would
        # say the same thing twice.
        mods=[],
        source=source,
    )


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
    if game_id in MOTOCROSS_GAMES:
        # No class is claimed for these. The profile only knows the bike
        # selected now, which says nothing about a lap set months ago.
        return [
            _from_moto(record, username, "", SOURCE_IMPORTED)
            for record in motocross.snapshot(Path(install), game=game_id).values()
            if MIN_PLAUSIBLE_SECONDS <= record.seconds <= motocross.MAX_TIME
        ]

    unapproved = reader.unapproved_archives(Path(install), game_id)
    out: list[Submission] = []
    for record in reader.snapshot(Path(install), game=game_id).values():
        board = reader.classify(record.car, unapproved, game_id)
        if board is None or not (MIN_PLAUSIBLE_SECONDS <= record.seconds <= reader.MAX_TIME):
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
        self.motocross = game_id in MOTOCROSS_GAMES
        if self.motocross:
            # No archives to judge: a Motocross mod is a track, and whether a
            # track shipped with the game is decided per record.
            self.unapproved = []
            self.mods = list(mods or [])
            self._before = motocross.snapshot(self.install, game=self.game_id)
            # The names in the rider profile before the session, so the one
            # that appears afterwards can be matched to the track that gained
            # a time. See motocross.learn_name.
            self._names_before = motocross.all_profile_names(self.install)
        else:
            # What the game will actually load, judged from the folder itself.
            # Taken now rather than at the end, so archives added mid-session
            # cannot retroactively qualify a run for the vanilla board.
            self.unapproved = reader.unapproved_archives(self.install, game_id)
            self.mods = self.unapproved or list(mods or [])
            self._before = reader.snapshot(self.install, game=self.game_id)
            self._names_before = []
        self._started = time.monotonic()
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
        if self.motocross:
            self._collect_moto()
            return

        session_seconds = time.monotonic() - self._started
        after = reader.snapshot(self.install, game=self.game_id)
        improved = reader.improvements(self._before, after)

        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        good: list[Submission] = []
        for record in improved:
            board = reader.classify(record.car, self.unapproved, self.game_id)
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

    def _collect_moto(self) -> None:
        """The same, for a game that keeps a table beside each track."""
        session_seconds = time.monotonic() - self._started
        after = motocross.snapshot(self.install, game=self.game_id)
        improved = motocross.improvements(self._before, after)

        # Read once, at the end. The class is a selection in the rider
        # profile rather than a property of the time, so this is the bike the
        # session finished on — see motocross.selected_class.
        bike_class = motocross.selected_class(self.install)

        # A track that gained a time, paired with a name that appeared in the
        # profile, is the only way the real names are obtainable. Learned
        # before the records are built so the very run that teaches us the
        # name is also published under it.
        tracks = sorted({r.track for r in improved})
        learned = motocross.learn_name(
            tracks, self._names_before, motocross.all_profile_names(self.install)
        )
        if learned:
            from . import tracknames

            tracknames.remember(*learned)

        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        good: list[Submission] = []
        for record in improved:
            entry = _from_moto(
                record, self.username, bike_class, SOURCE_LAUNCHER, stamp
            )
            ok, why = plausible(entry, session_seconds)
            if ok:
                good.append(entry)
            else:
                self.rejected.emit(f"{entry.race_name} {entry.formatted}", why)

        if good:
            self.found.emit(good)
        self.finished.emit(len(good))
