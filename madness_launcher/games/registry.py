"""The catalogue of games the launcher knows about.

Placeholder entries carry `available=False` until their definitions are filled
in; the library shows them greyed out so the roadmap is visible in the UI.
"""

from __future__ import annotations

from .base import GameDef
from .mcm1 import MCM1
from .mcm2 import MCM2
from .mm1 import MM1
from .mm2 import MM2
from .mtm1 import MTM1
from .mtm2 import MTM2

# Games with a complete definition, in display order.
GAMES: tuple[GameDef, ...] = (MM1, MM2, MTM1, MTM2, MCM1, MCM2)

# Titles planned but not yet defined. Shown as inactive cards in the library.
PLANNED: tuple[tuple[str, str, str], ...] = ()


def by_id(game_id: str) -> GameDef | None:
    for g in GAMES:
        if g.id == game_id:
            return g
    return None
