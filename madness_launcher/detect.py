"""Identifying a game folder from whatever the user points us at."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .games.base import ExeTarget, GameDef
from .games.registry import GAMES


@dataclass
class DetectionResult:
    game: GameDef
    root: Path
    # Executables that actually exist on disk, in the game's preferred order.
    found_targets: list[ExeTarget] = field(default_factory=list)
    # Declared data files that are missing.
    missing_data: list[str] = field(default_factory=list)
    # True when only the data archives identified the game, meaning the folder
    # is the right game but ships an executable under a name we do not know.
    identified_by_data_only: bool = False
    # A launch target the user nominated by hand, for exactly that case.
    custom_exe: str = ""
    # Targets whose executable is gone but whose leftovers are still present.
    absent_with_residue: list[ExeTarget] = field(default_factory=list)

    def residue_evidence(self, target: ExeTarget) -> list[str]:
        return [r for r in target.residue_files if has_file(self.root, r)]

    @property
    def ok(self) -> bool:
        return self.playable and not self.missing_data

    @property
    def playable(self) -> bool:
        return bool(self.found_targets) or bool(self.custom_exe)

    def executables(self) -> list[str]:
        """Every .exe in the folder, for letting the user pick a renamed one."""
        try:
            return sorted(
                (p.name for p in self.root.iterdir()
                 if p.is_file() and p.suffix.lower() == ".exe"),
                key=str.lower,
            )
        except OSError:
            return []

    def summary(self) -> str:
        if not self.playable:
            return "Game data found, but no known executable"
        if self.missing_data:
            missing = ", ".join(self.missing_data)
            return f"Playable, but missing data files: {missing}"
        if self.custom_exe:
            return f"Verified · launching {self.custom_exe}"
        if self.absent_with_residue:
            return f"Playable · {self.absent_with_residue[0].filename} missing"
        return "Verified"


def _find_case_insensitive(root: Path, name: str) -> Path | None:
    """Windows is case-insensitive but the code should not rely on it.

    Game folders are frequently copied off CDs or out of archives with
    inconsistent casing (MIDTOWN.EXE vs Midtown.exe), so match either way.
    Accepts a multi-segment relative path — Monster Truck Madness keeps both its
    settings and its core archives under `System/` — and resolves each segment
    independently, since the casing can differ at every level.
    """
    direct = root / name
    if direct.exists():
        return direct

    current = root
    for segment in Path(name).parts:
        candidate = current / segment
        if candidate.exists():
            current = candidate
            continue
        lowered = segment.lower()
        try:
            match = next(
                (c for c in current.iterdir() if c.name.lower() == lowered), None
            )
        except OSError:
            return None
        if match is None:
            return None
        current = match
    return current


def has_file(root: Path, name: str) -> bool:
    return _find_case_insensitive(root, name) is not None


def resolve_root(selection: Path) -> Path:
    """Accept either the game folder or an executable inside it."""
    return selection.parent if selection.is_file() else selection


def inspect(root: Path, game: GameDef) -> DetectionResult | None:
    """Check one folder against one game definition.

    A folder counts as the game if it has a known executable *or* the full set
    of data files. The second route matters for repacks and self-contained
    bundles, which often rename or wrap the executable but always ship the
    game's data archives under their original names.
    """
    if not root.is_dir():
        return None

    missing = [d for d in game.data_files if not has_file(root, d)]
    by_exe = any(has_file(root, sig) for sig in game.signature_files)
    by_data = bool(game.data_files) and not missing
    if not (by_exe or by_data):
        return None

    found = [t for t in game.exe_targets if has_file(root, t.filename)]
    absent = [
        t
        for t in game.exe_targets
        if t not in found
        and t.residue_files
        and any(has_file(root, r) for r in t.residue_files)
    ]
    return DetectionResult(
        game=game,
        root=root,
        found_targets=found,
        missing_data=missing,
        identified_by_data_only=by_data and not by_exe,
        absent_with_residue=absent,
    )


def identify(selection: Path) -> DetectionResult | None:
    """Work out which known game lives at this path, if any.

    Returns the strongest match: a folder containing both Open1560.exe and the
    full archive set beats one with only a stray executable.
    """
    root = resolve_root(selection)
    candidates = [r for r in (inspect(root, g) for g in GAMES) if r is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r.ok, r.playable, len(r.found_targets)), reverse=True)
    return candidates[0]


def identify_as(selection: Path, game: GameDef) -> DetectionResult | None:
    """Check a path against one specific game, for 'add this game' flows."""
    return inspect(resolve_root(selection), game)
