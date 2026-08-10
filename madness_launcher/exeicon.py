"""Pull a game's own icon out of its executable.

Every one of these games ships icons in its PE resources — up to 48x48, and
32-bit for the later ones. That is the most authentic per-game artwork
available, it is already on disk wherever the launcher is pointed, and it costs
nothing to read. Better than anything painted, and unlike textures pulled out of
archives it is present on every install rather than only on modded ones.

The resource directory is walked directly rather than through a PE library: the
launcher ships as a frozen executable and adding a dependency for a hundred
lines of struct parsing is a poor trade.

Nothing here trusts the file. A malformed or truncated exe must return None, not
raise — the caller is drawing a sidebar, not loading a game.
"""

from __future__ import annotations

import struct
from pathlib import Path

# Resource types we care about.
RT_ICON = 3
RT_GROUP_ICON = 14

# A resource directory entry pointing at a subdirectory has the top bit set.
SUBDIR_FLAG = 0x80000000


class _Image:
    """Just enough of the PE layout to map RVAs onto file offsets."""

    def __init__(self, data: bytes):
        self.data = data
        self.sections: list[tuple[int, int, int, int]] = []
        self.resource_root: int | None = None
        self._parse()

    def _parse(self) -> None:
        data = self.data
        if len(data) < 0x40 or data[:2] != b"MZ":
            raise ValueError("not a PE image")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if pe + 24 > len(data) or data[pe : pe + 4] != b"PE\0\0":
            raise ValueError("no PE signature")

        section_count = struct.unpack_from("<H", data, pe + 6)[0]
        optional_size = struct.unpack_from("<H", data, pe + 20)[0]
        optional = pe + 24
        magic = struct.unpack_from("<H", data, optional)[0]
        if magic == 0x10B:  # PE32
            directories = optional + 96
        elif magic == 0x20B:  # PE32+
            directories = optional + 112
        else:
            raise ValueError("unknown optional header")

        table = optional + optional_size
        for index in range(section_count):
            entry = table + index * 40
            if entry + 40 > len(data):
                break
            virtual_size, virtual_addr, raw_size, raw_addr = struct.unpack_from(
                "<IIII", data, entry + 8
            )
            self.sections.append((virtual_addr, virtual_size, raw_addr, raw_size))

        # Directory 2 is the resource table.
        resource_rva = struct.unpack_from("<I", data, directories + 2 * 8)[0]
        self.resource_root = self.offset_of(resource_rva) if resource_rva else None

    def offset_of(self, rva: int) -> int | None:
        for virtual_addr, virtual_size, raw_addr, raw_size in self.sections:
            span = max(virtual_size, raw_size)
            if virtual_addr <= rva < virtual_addr + span:
                offset = raw_addr + (rva - virtual_addr)
                return offset if 0 <= offset < len(self.data) else None
        return None

    def resources(self) -> dict[int, dict[int, bytes]]:
        """{type_id: {resource_id: data}} — first language of each resource."""
        found: dict[int, dict[int, bytes]] = {}
        if self.resource_root is None:
            return found
        self._walk(0, [], found)
        return found

    def _walk(self, offset: int, path: list[int], found: dict) -> None:
        # Three levels: type, name/id, language. Deeper than that is malformed.
        if len(path) > 3:
            return
        base = self.resource_root
        header = base + offset
        if header + 16 > len(self.data):
            return
        named, by_id = struct.unpack_from("<HH", self.data, header + 12)
        total = named + by_id
        # A directory claiming thousands of entries is corrupt, not ambitious.
        if total > 8192:
            return

        for index in range(total):
            entry = header + 16 + index * 8
            if entry + 8 > len(self.data):
                return
            name, child = struct.unpack_from("<II", self.data, entry)
            identifier = name & 0x7FFFFFFF

            if child & SUBDIR_FLAG:
                self._walk(child & 0x7FFFFFFF, path + [identifier], found)
                continue

            leaf = base + child
            if leaf + 8 > len(self.data):
                continue
            data_rva, size = struct.unpack_from("<II", self.data, leaf)
            start = self.offset_of(data_rva)
            if start is None or size <= 0 or start + size > len(self.data):
                continue
            if len(path) < 2:
                continue
            type_id, resource_id = path[0], path[1]
            # First language wins; they are the same artwork.
            found.setdefault(type_id, {}).setdefault(
                resource_id, self.data[start : start + size]
            )


def _describe(payload: bytes) -> tuple[int, int, int] | None:
    """(width, height, bit depth) read from the image itself.

    The directory entry in the resource is not trustworthy: Midtown Madness
    stores the doubled DIB height there (64 for a 32x32 icon), and Qt rejects
    the resulting file. The image always knows its own shape, so it is the
    better source. A width or height of 256 is written as 0 in an ICO.
    """
    if payload[:8] == b"\x89PNG\r\n\x1a\n":
        # Vista-era PNG-compressed icon: dimensions live in the IHDR.
        if len(payload) < 24:
            return None
        width, height = struct.unpack_from(">II", payload, 16)
        return (width, height, 32)

    if len(payload) < 16:
        return None
    header_size = struct.unpack_from("<I", payload, 0)[0]
    if header_size < 40:
        return None
    width, height = struct.unpack_from("<ii", payload, 4)
    depth = struct.unpack_from("<H", payload, 14)[0]
    # A DIB inside an icon stacks the colour image on top of the AND mask, so
    # its stated height is twice the real one.
    height //= 2
    if not (0 < width <= 256 and 0 < height <= 256):
        return None
    return (width, height, depth)


def _build_ico(group: bytes, images: dict[int, bytes]) -> bytes | None:
    """Turn a RT_GROUP_ICON directory plus its RT_ICONs back into a .ico file.

    The two formats differ only in the last field of each entry: the resource
    group stores a 2-byte resource id where the file stores a 4-byte offset. Qt
    decodes .ico properly — including the AND mask — so rebuilding the container
    is far better than trying to decode the DIBs here.
    """
    if len(group) < 6:
        return None
    reserved, kind, count = struct.unpack_from("<HHH", group, 0)
    if reserved != 0 or kind != 1 or not (0 < count <= 64):
        return None
    if len(group) < 6 + count * 14:
        return None

    entries: list[tuple[bytes, bytes]] = []
    for index in range(count):
        raw = group[6 + index * 14 : 6 + (index + 1) * 14]
        resource_id = struct.unpack_from("<H", raw, 12)[0]
        payload = images.get(resource_id)
        if not payload:
            continue
        shape = _describe(payload)
        if shape is None:
            continue
        width, height, depth = shape
        planes = struct.unpack_from("<H", raw, 4)[0] or 1
        fixed = struct.pack(
            "<BBBBHHI",
            width % 256,   # 256 is written as 0
            height % 256,
            0,             # colour count: 0 means "use the bit depth"
            0,
            planes,
            depth,
            len(payload),
        )
        entries.append((fixed, payload))
    if not entries:
        return None

    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(header) + len(entries) * 16
    directory = bytearray()
    body = bytearray()
    for fixed, payload in entries:
        directory += fixed + struct.pack("<I", offset)
        body += payload
        offset += len(payload)
    return bytes(header) + bytes(directory) + bytes(body)


def extract_ico(exe: Path) -> bytes | None:
    """The application icon from a PE file, as .ico bytes. None if unavailable."""
    try:
        data = Path(exe).read_bytes()
    except OSError:
        return None
    try:
        image = _Image(data)
        resources = image.resources()
    except (ValueError, struct.error):
        return None

    groups = resources.get(RT_GROUP_ICON) or {}
    icons = resources.get(RT_ICON) or {}
    if not groups or not icons:
        return None

    # The lowest group id is the application icon by convention — it is what
    # Explorer shows for the file.
    for resource_id in sorted(groups):
        try:
            built = _build_ico(groups[resource_id], icons)
        except struct.error:
            continue
        if built:
            return built
    return None
