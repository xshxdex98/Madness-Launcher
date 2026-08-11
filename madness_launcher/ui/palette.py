"""The launcher's colours, as data rather than as constants.

theme.py holds a palette that was written by hand and baked into the
stylesheet. This turns that palette into a value that can be edited, saved and
swapped at runtime, without giving up the tuning in the original: the default
here is exactly the colours that were there before.

Thirteen colour wells is more than anyone wants to fill in to change the look
of a launcher, so there are two ways to drive it. Three seeds — background,
text and accent — derive the other ten, using the same relationships the
hand-tuned palette already had; that is `derive()`. Or every colour can be set
individually, for someone who wants to. The seeds are how the customiser
presents it, and the individual fields are what actually gets saved, so the
two cannot disagree.

Nothing here imports Qt. It is arithmetic on hex strings, which keeps it
testable without a QApplication and keeps theme.py free to depend on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, replace

HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalise(value: str, fallback: str = "#000000") -> str:
    """A #RRGGBB string, or the fallback if it is not a colour at all."""
    value = (value or "").strip()
    if not HEX.match(value):
        return fallback
    body = value[1:]
    if len(body) == 3:
        body = "".join(c * 2 for c in body)
    return "#" + body.upper()


def _channels(value: str) -> tuple[int, int, int]:
    body = normalise(value)[1:]
    return tuple(int(body[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def mix(first: str, second: str, amount: float) -> str:
    """Blend two colours; amount 0 keeps the first, 1 gives the second."""
    a, b = _channels(first), _channels(second)
    return "#" + "".join(
        f"{round(ca + (cb - ca) * amount):02X}" for ca, cb in zip(a, b)
    )


def lighten(value: str, amount: float = 0.15) -> str:
    return mix(value, "#FFFFFF", amount)


def darken(value: str, amount: float = 0.15) -> str:
    return mix(value, "#000000", amount)


def luminance(value: str) -> float:
    """Relative luminance, as defined by WCAG."""
    out = 0.0
    for channel, weight in zip(_channels(value), (0.2126, 0.7152, 0.0722)):
        c = channel / 255
        out += weight * (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def contrast(first: str, second: str) -> float:
    """The WCAG contrast ratio between two colours, from 1 to 21."""
    a, b = luminance(first), luminance(second)
    lo, hi = sorted((a, b))
    return (hi + 0.05) / (lo + 0.05)


Amounts = tuple[float, float, float]


def _amounts(start: str, end: str, toward: str) -> Amounts:
    """Per-channel mix amounts that take `start` to `end` on the way to `toward`.

    Per channel and not averaged, because the average throws away exactly what
    makes the shipped palette worth keeping. Its greys are tinted — the
    surfaces climb faster in blue than in red — and a single number for all
    three flattens that into a neutral grey. Measured this way, feeding the
    stock background and text back through `derive` returns the stock palette
    unchanged, so nudging one colour cannot quietly restructure the rest.
    """
    a, b, t = _channels(start), _channels(end), _channels(toward)
    out = []
    for ca, cb, ct in zip(a, b, t):
        out.append((cb - ca) / (ct - ca) if ct != ca else 0.0)
    # A channel with nowhere to travel gets the average of the ones that had.
    moving = [x for x, (ca, ct) in zip(out, zip(a, t)) if ct != ca]
    if moving and len(moving) < 3:
        fill = sum(moving) / len(moving)
        out = [x if ct != ca else fill for x, ca, ct in zip(out, a, t)]
    return tuple(out)  # type: ignore[return-value]


def _mix_each(start: str, toward: str, amounts: Amounts) -> str:
    a, t = _channels(start), _channels(toward)
    return "#" + "".join(
        f"{max(0, min(255, round(ca + (ct - ca) * amt))):02X}"
        for ca, ct, amt in zip(a, t, amounts)
    )

# Text drawn on top of the accent — on a Play button, a ticked checkbox, a
# selection. Whichever of the two reads better against the accent wins, so a
# dark accent gets light text instead of the near-black that was hardcoded.
ON_ACCENT_DARK = "#14161A"
ON_ACCENT_LIGHT = "#F4F7FB"


@dataclass(frozen=True)
class Palette:
    """Every colour the interface uses.

    The defaults are Chicago at night: a navy-tinted greyscale rather than a
    neutral one, so the shell reads as part of Midtown Madness without
    resorting to 1999 chrome.
    """

    accent: str = "#E0912F"
    bg: str = "#0B0F16"
    surface: str = "#121824"
    elevated: str = "#18202E"
    hover: str = "#1F2937"
    border: str = "#222C3C"
    border_strong: str = "#2F3D51"
    text: str = "#E7ECF3"
    muted: str = "#8795AB"
    faint: str = "#5A6982"
    good: str = "#4CAF7D"
    warn: str = "#D9A441"
    bad: str = "#D9584B"

    @property
    def on_accent(self) -> str:
        if contrast(self.accent, ON_ACCENT_DARK) >= contrast(
            self.accent, ON_ACCENT_LIGHT
        ):
            return ON_ACCENT_DARK
        return ON_ACCENT_LIGHT

    def with_accent(self, accent: str) -> "Palette":
        return replace(self, accent=normalise(accent, self.accent))

    def to_dict(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def changes(self) -> dict[str, str]:
        """Only what differs from the default, which is all worth saving."""
        base = Palette()
        return {k: v for k, v in self.to_dict().items() if v != getattr(base, k)}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Palette":
        """Rebuild a palette, ignoring anything unrecognised or malformed.

        A config written by a later version, or edited by hand into nonsense,
        must not stop the launcher from starting — an unreadable colour falls
        back to the default for that field rather than raising.
        """
        base = cls()
        if not isinstance(data, dict):
            return base
        known = {f.name for f in fields(cls)}
        clean = {
            key: normalise(str(value), getattr(base, key))
            for key, value in data.items()
            if key in known and isinstance(value, str)
        }
        return replace(base, **clean) if clean else base


DEFAULT = Palette()

# How far each surface sits from the background, and each secondary text
# colour from the foreground, read straight off the palette above.
_FROM_BG = {
    name: _amounts(DEFAULT.bg, getattr(DEFAULT, name), DEFAULT.text)
    for name in ("surface", "elevated", "hover", "border", "border_strong")
}
_FROM_TEXT = {
    name: _amounts(DEFAULT.text, getattr(DEFAULT, name), DEFAULT.bg)
    for name in ("muted", "faint")
}

# The three the customiser puts in front of people. Everything else follows
# from them unless it has been set individually.
SEEDS = ("bg", "text", "accent")

# name -> (label, what it actually paints)
LABELS: dict[str, tuple[str, str]] = {
    "accent": ("Accent", "Play buttons, the selected tab, focus rings, ticks"),
    "bg": ("Background", "The window behind everything"),
    "surface": ("Surface", "Cards, the sidebar, tables"),
    "elevated": ("Raised surface", "Buttons, dropdowns, table headings"),
    "hover": ("Hover", "Whatever the pointer is over"),
    "border": ("Border", "Hairlines between panels and rows"),
    "border_strong": ("Strong border", "Button and input outlines, scrollbars"),
    "text": ("Text", "Body copy and headings"),
    "muted": ("Muted text", "Subtitles, table headings, inactive entries"),
    "faint": ("Faint text", "Captions, hints, disabled controls"),
    "good": ("Good", "An install that verified"),
    "warn": ("Warning", "An install missing something"),
    "bad": ("Bad", "An install that will not run"),
}


def derive(
    bg: str, text: str, accent: str, base: Palette | None = None
) -> Palette:
    """Build a full palette from the three seeds.

    Surfaces are mixed towards the text colour rather than towards white, so
    the same arithmetic produces a sane light theme as well as a dark one:
    on a white background the surfaces come out darker, which is what a
    raised panel on white has to be.
    """
    base = base or DEFAULT
    bg = normalise(bg, base.bg)
    text = normalise(text, base.text)
    accent = normalise(accent, base.accent)
    return Palette(
        accent=accent,
        bg=bg,
        text=text,
        **{n: _mix_each(bg, text, a) for n, a in _FROM_BG.items()},
        **{n: _mix_each(text, bg, a) for n, a in _FROM_TEXT.items()},
        # Green means verified, red means broken. Those are not decoration and
        # they do not follow the background; the advanced tier can still move
        # them for anyone who needs to.
        good=base.good,
        warn=base.warn,
        bad=base.bad,
    )


def readability(p: Palette) -> list[str]:
    """Complaints about a palette nobody could read, worst first.

    Advisory, not enforced. Somebody who wants black on black is allowed to
    have it; they should just be told before they wonder why the launcher has
    gone blank.
    """
    out: list[str] = []
    checks = (
        ("Text on the background", p.text, p.bg, 4.5),
        ("Muted text on the background", p.muted, p.bg, 3.0),
        ("Text on a card", p.text, p.surface, 4.5),
        ("Buttons against the background", p.elevated, p.bg, 1.12),
        ("The accent against the background", p.accent, p.bg, 2.0),
    )
    for label, first, second, want in checks:
        ratio = contrast(first, second)
        if ratio < want:
            out.append(f"{label}: {ratio:.1f}:1, short of the {want}:1 it wants.")
    return out


PRESETS: dict[str, Palette] = {
    "Midtown night": DEFAULT,
    "Carbon": derive("#101010", "#EDEDED", "#E0912F"),
    "Slate": derive("#151A1F", "#E4EAF0", "#4FA3D1"),
    "Deep purple": derive("#120E1C", "#EBE6F5", "#A472E8"),
    "Racing green": derive("#0A1410", "#E3EFE8", "#3FBF7F"),
    "Daylight": derive("#F4F6F9", "#161A20", "#C2661B"),
}
