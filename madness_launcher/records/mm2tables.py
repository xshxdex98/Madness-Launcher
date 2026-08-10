"""Midtown Madness 2's races, in the order the game numbers its slots.

MM1 publishes its race order as plaintext inside ui.ar, so the launcher
reads it from whichever install it is looking at. MM2 keeps the
equivalent inside a compressed DAVE archive that could not be read
reliably, so the order was established by experiment instead: snapshot
the save, drive one named race, see which slot moved.

Two independent probes fixed it, and it is NOT the order MM1 uses:

    the first Blitz in the menu  -> slot group 22
    the second Circuit, Hang Time -> slot group 13

which forces Checkpoint 0-11, Circuit 12-21, Blitz 22-31. Checkpoint is
the only twelve-race category, so the twelve-slot block at the start can
only be Checkpoint. MM1 runs Blitz, Circuit, Checkpoint — the reverse —
and assuming MM2 matched it would have mislabelled all 64 races.

Names come from speedrun.com's level list, which is also what the
world-record lookup matches against, so the two agree by construction.
Crash Course is deliberately absent: it has thirteen races per city and
the save's 320 slots leave no room for it, so the game evidently keeps
those elsewhere.
"""

from __future__ import annotations

# city -> ordered (kind, name), index in this tuple is the race index.
RACES: dict[str, tuple[tuple[str, str], ...]] = {
    "sf": (
        ("Checkpoint", "Racing 101"),
        ("Checkpoint", "Deck The Hall"),
        ("Checkpoint", "Golden Hour"),
        ("Checkpoint", "City Tour"),
        ("Checkpoint", "Foggy Memory"),
        ("Checkpoint", "Park & Ride"),
        ("Checkpoint", "The Hills Are Alive"),
        ("Checkpoint", "Lookout!"),
        ("Checkpoint", "Wanted!"),
        ("Checkpoint", "After Hours"),
        ("Checkpoint", "Full Speed Ahead"),
        ("Checkpoint", "Panoz Pressure"),
        ("Circuit", "Take It Easy"),
        ("Circuit", "Hang Time"),
        ("Circuit", "Gimme SOMA"),
        ("Circuit", "Wind It Up"),
        ("Circuit", "Midtown Mayhem"),
        ("Circuit", "Chinatown"),
        ("Circuit", "Presidio!"),
        ("Circuit", "Square Dancing"),
        ("Circuit", "Circuit Breaker"),
        ("Circuit", "Floor It!"),
        ("Blitz", "Ignorance Is Blitz"),
        ("Blitz", "Hold On Tight"),
        ("Blitz", "Wrong Way!"),
        ("Blitz", "Golden Race"),
        ("Blitz", "Presidio Push"),
        ("Blitz", "Amazing Grace"),
        ("Blitz", "Lombard Lunacy"),
        ("Blitz", "Embarca-dare-o"),
        ("Blitz", "Telegraph Turnaround"),
        ("Blitz", "Coit Nightmare"),
    ),
    "london": (
        ("Checkpoint", "Top Of The Morning"),
        ("Checkpoint", "Bridge Bash"),
        ("Checkpoint", "Through The Park"),
        ("Checkpoint", "V & A Visit"),
        ("Checkpoint", "South Bank Brawl"),
        ("Checkpoint", "River Thames Run"),
        ("Checkpoint", "Circuit Within"),
        ("Checkpoint", "Check This!"),
        ("Checkpoint", "Splish Splash"),
        ("Checkpoint", "Cut It Short"),
        ("Checkpoint", "Dizzy Driving"),
        ("Checkpoint", "Foggy, Foggy Night"),
        ("Circuit", "Mini Race"),
        ("Circuit", "Round Westminster"),
        ("Circuit", "View From Two Bridges"),
        ("Circuit", "Parks But No Parking"),
        ("Circuit", "City Circuit"),
        ("Circuit", "Underground"),
        ("Circuit", "London Run"),
        ("Circuit", "Gimme Some Royalties"),
        ("Circuit", "Soho Mojo"),
        ("Circuit", "Zany Zigzag"),
        ("Blitz", "London's Calling"),
        ("Blitz", "Embank On It"),
        ("Blitz", "Tower Tour"),
        ("Blitz", "Hyde And Go Seek"),
        ("Blitz", "Going Underground"),
        ("Blitz", "Battle of Trafalgar"),
        ("Blitz", "Crosstown Sprint"),
        ("Blitz", "Alley Cats"),
        ("Blitz", "Midnight Mash"),
        ("Blitz", "Five-Ring Circus"),
    ),
}

# What the game calls each city folder under players/.
CITY_NAMES = {"sf": "San Francisco", "london": "London"}
