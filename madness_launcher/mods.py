"""Mod library and installer.

Design rules, in priority order:

1. Never destroy a file the launcher did not create. Anything a mod overwrites
   is copied into the backup store first and restored on disable.
2. Never guess what to remove. Enabling writes a receipt listing exactly which
   destination paths were created and which displaced an original; disabling
   consults only that receipt.
3. Keep the payload outside the game folder until enabled, so a disabled mod
   leaves no trace and the game folder stays clean.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from . import paths
from .detect import _find_case_insensitive
from .games.base import GameDef
from .orderfile import CountedListFile

MANIFEST = "mod.json"
RECEIPT = "installed.json"
PAYLOAD = "files"


class ModError(Exception):
    """Raised for problems the user should see as a message, not a traceback."""


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return slug or "mod"


def split_priority(filename: str, prefix: str = "!") -> tuple[int, str]:
    """Read a load-order prefix off a filename.

    MM1 packs encode priority as leading '!' characters, sometimes spaced out
    (`! ! !fog.ar`). Returns the count and the bare name.
    """
    if not prefix:
        return 0, filename
    count = 0
    index = 0
    while index < len(filename) and filename[index] in (prefix, " "):
        if filename[index] == prefix:
            count += 1
        index += 1
    return count, filename[index:]


@dataclass
class Mod:
    slug: str
    name: str
    version: str = ""
    author: str = ""
    notes: str = ""
    # How many priority-prefix characters to prepend to top-level archives.
    priority: int = 0
    source: str = ""
    root: Path = field(default=Path(), compare=False, repr=False)
    # Section heading in the UI, taken from the staging folder it was found in.
    category: str = ""
    # Absolute path to a payload held outside the library. Set for mods indexed
    # in place from a distribution's staging folders, which are far too large to
    # duplicate. Empty for mods imported into the library.
    link_source: str = ""
    # Priority parsed from the payload's own filenames at index time. While the
    # user leaves priority alone, deployment reuses the original names verbatim,
    # preserving whatever load order the pack's author intended.
    detected_priority: int = 0
    # Folder inside the game this mod's files are deployed into. Used by games
    # whose content lives in named folders rather than at the root, where a
    # bare downloaded file carries no clue about where it belongs.
    dest_prefix: str = ""
    # Set by the manager so a linked folder can tell its own payload from a
    # nested variant folder that is a separate mod. Not persisted.
    archive_suffixes: tuple[str, ...] = field(default=(), compare=False, repr=False)

    @property
    def payload_dir(self) -> Path:
        return Path(self.link_source) if self.link_source else self.root / PAYLOAD

    @property
    def linked(self) -> bool:
        return bool(self.link_source)

    @property
    def receipt_file(self) -> Path:
        return self.root / RECEIPT

    @property
    def enabled(self) -> bool:
        return self.receipt_file.is_file()

    @property
    def available(self) -> bool:
        """A linked payload can vanish if the user moves the game folder."""
        return self.payload_dir.exists() if self.linked else self.payload_dir.is_dir()

    def entries(self) -> list[tuple[Path, str]]:
        """(absolute source, path relative to the game root) for every file."""
        base = self.payload_dir
        if self.linked and base.is_file():
            # A single archive parked in a staging folder.
            return [(base, base.name)]
        if not base.is_dir():
            return []

        # A subfolder that holds archives of its own is a separate mod, indexed
        # separately — its files are not part of this one. Subtrees without
        # archives (a `dev/` tree, for instance) do belong here and are kept.
        excluded: set[Path] = set()
        if self.linked and self.archive_suffixes:
            for path in base.rglob("*"):
                if path.is_dir() and any(
                    c.is_file() and c.suffix.lower() in self.archive_suffixes
                    for c in path.iterdir()
                ):
                    excluded.add(path)

        return [
            (p, str(p.relative_to(base)))
            for p in sorted(base.rglob("*"))
            if p.is_file() and not any(parent in excluded for parent in p.parents)
        ]

    def payload_files(self) -> list[Path]:
        return [Path(rel) for _, rel in self.entries()]

    def save_manifest(self) -> None:
        data = {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "notes": self.notes,
            "priority": self.priority,
            "source": self.source,
            "category": self.category,
            "link_source": self.link_source,
            "detected_priority": self.detected_priority,
            "dest_prefix": self.dest_prefix,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / MANIFEST).write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, mod_dir: Path) -> "Mod | None":
        manifest = mod_dir / MANIFEST
        if not manifest.is_file():
            return None
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return cls(
            slug=mod_dir.name,
            name=data.get("name") or mod_dir.name,
            version=data.get("version", ""),
            author=data.get("author", ""),
            notes=data.get("notes", ""),
            priority=int(data.get("priority", 0) or 0),
            source=data.get("source", ""),
            category=data.get("category", ""),
            link_source=data.get("link_source", ""),
            detected_priority=int(data.get("detected_priority", 0) or 0),
            dest_prefix=data.get("dest_prefix", ""),
            root=mod_dir,
        )


@dataclass
class ScanResult:
    """What a staging-folder scan found, including what it declined to touch."""

    added: int = 0
    already_known: int = 0
    # (category, entry name) for staged items the launcher will not manage.
    unmanaged: list[tuple[str, str]] = field(default_factory=list)


# Packaged distributions that are not drop-in mods. Something like a NuHook
# release is a framework with its own installer and README — deploying its 394
# files, documentation folders and all, into the game directory would be wrong.
PACKAGED_SUFFIXES = (".zip", ".rar", ".7z", ".exe", ".msi")


@dataclass
class PlannedFile:
    """One file an enable operation intends to write."""

    source: Path
    dest_rel: str


class ModManager:
    def __init__(self, game: GameDef, game_root: Path) -> None:
        self.game = game
        self.game_root = Path(game_root)
        self.library = paths.mod_library(game.id)
        self.backups = paths.backup_dir(game.id)

    # -- library ---------------------------------------------------------

    def list_mods(self) -> list[Mod]:
        if not self.library.is_dir():
            return []
        suffixes = self.game.mod_spec.archive_suffixes
        mods = []
        for directory in sorted(self.library.iterdir()):
            if not directory.is_dir():
                continue
            mod = Mod.load(directory)
            if mod is not None:
                mod.archive_suffixes = suffixes
                mods.append(mod)
        # Grouped by category, then highest priority first within each, which
        # is the order the engine will load them in.
        mods.sort(key=lambda m: (m.category.lower(), -m.priority, m.name.lower()))
        return mods

    def by_category(self) -> dict[str, list[Mod]]:
        """Mods grouped for display. Imported ones come first, uncategorised."""
        groups: dict[str, list[Mod]] = {}
        for mod in self.list_mods():
            groups.setdefault(mod.category, []).append(mod)
        return dict(sorted(groups.items(), key=lambda kv: (kv[0] != "", kv[0].lower())))

    def get(self, slug: str) -> Mod | None:
        mod = Mod.load(self.library / slug)
        if mod is not None:
            mod.archive_suffixes = self.game.mod_spec.archive_suffixes
        return mod

    def _unique_slug(self, name: str) -> str:
        base = slugify(name)
        slug, n = base, 2
        while (self.library / slug).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug

    # -- import ----------------------------------------------------------

    def import_path(self, source: Path, name: str = "", dest_prefix: str = "") -> Mod:
        """Bring an .ar file, a folder, or a .zip into the library."""
        source = Path(source)
        if not source.exists():
            raise ModError(f"{source} does not exist.")

        display = name or source.stem
        slug = self._unique_slug(display)
        mod_dir = self.library / slug
        payload = mod_dir / PAYLOAD
        payload.mkdir(parents=True, exist_ok=True)

        try:
            if source.is_dir():
                self._copy_tree(source, payload)
            elif source.suffix.lower() == ".zip":
                self._extract_zip(source, payload)
            else:
                shutil.copy2(source, payload / source.name)
        except Exception:
            shutil.rmtree(mod_dir, ignore_errors=True)
            raise

        mod = Mod(slug=slug, name=display, source=str(source), root=mod_dir,
                  dest_prefix=dest_prefix,
                  archive_suffixes=self.game.mod_spec.archive_suffixes)
        if not mod.payload_files():
            shutil.rmtree(mod_dir, ignore_errors=True)
            raise ModError("That archive or folder contained no files.")
        mod.save_manifest()
        return mod

    @staticmethod
    def _copy_tree(src: Path, dest: Path) -> None:
        shutil.copytree(src, dest, dirs_exist_ok=True)

    @staticmethod
    def _extract_zip(src: Path, dest: Path) -> None:
        dest = dest.resolve()
        with zipfile.ZipFile(src) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # Refuse absolute paths and ../ traversal in the archive.
                target = (dest / info.filename).resolve()
                if not target.is_relative_to(dest):
                    raise ModError(
                        f"Archive contains an unsafe path: {info.filename}"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as fh, open(target, "wb") as out:
                    shutil.copyfileobj(fh, out)

    def delete(self, mod: Mod) -> None:
        if mod.enabled:
            self.disable(mod)
        # Only the library entry goes. A linked payload belongs to the game
        # folder and is never ours to remove.
        shutil.rmtree(mod.root, ignore_errors=True)

    # -- where loose content belongs -------------------------------------

    def content_destinations(self) -> list[str]:
        """Folders inside the game that already hold content of this kind.

        Derived from what is on disk rather than hardcoded, so a copy with
        extra discipline folders offers them too. Returned as game-relative
        paths using forward slashes.
        """
        spec = self.game.mod_spec
        if not spec.content_dirs:
            return []
        found: list[str] = []
        for root_name in spec.content_dirs:
            root = _find_case_insensitive(self.game_root, root_name)
            if root is None or not root.is_dir():
                continue
            candidates = [root] + [p for p in sorted(root.iterdir()) if p.is_dir()]
            for folder in candidates:
                if self._directly_holds_archive(folder):
                    found.append(
                        folder.relative_to(self.game_root).as_posix()
                    )
        return found

    # -- indexing a distribution's staging folders -----------------------

    def _staging_roots(self) -> list[tuple[str, Path]]:
        """(category name, folder) for every subfolder holding archives.

        Discovered rather than configured, so renaming a pack's mod folders —
        which people do — does not make its mods vanish from the launcher.
        """
        excluded = self._excluded_folder_names()
        found: list[tuple[str, Path]] = []
        try:
            children = sorted(
                (c for c in self.game_root.iterdir() if c.is_dir()),
                key=lambda p: p.name.lower(),
            )
        except OSError:
            return found

        for child in children:
            if child.name.lower() in excluded or child.name.startswith("."):
                continue
            if self._archives_in(child, recursive=True):
                found.append((child.name, child))
        return found

    def _excluded_folder_names(self) -> set[str]:
        """Folders that belong to the game rather than to mods.

        The name list catches the usual suspects, but the reliable signal is the
        game's own declared data: Monster Truck Madness keeps GAME.POD and its
        siblings in `System/`, so that folder is full of archives and would
        otherwise look exactly like a mod library.
        """
        excluded = {name.lower() for name in self.game.mod_spec.staging_exclude}
        for data_file in self.game.data_files:
            parts = Path(data_file).parts
            if len(parts) > 1:
                excluded.add(parts[0].lower())
        return excluded

    def _directly_holds_archive(self, folder: Path) -> bool:
        suffixes = self.game.mod_spec.archive_suffixes
        try:
            return any(
                p.is_file() and p.suffix.lower() in suffixes for p in folder.iterdir()
            )
        except OSError:
            return False

    def _mod_dirs_within(self, category: Path) -> list[Path]:
        """Descendant folders that are themselves a mod.

        A folder counts when archives sit *directly* inside it. That splits
        variant folders — `YosemiteValley/For NuHook users` alongside
        `YosemiteValley` — into separate mods, which is what they are, while
        leaving a mod's own subtrees (a `dev/` tree, say) as part of it.
        """
        found: list[Path] = []
        try:
            for path in sorted(category.rglob("*")):
                if path.is_dir() and self._directly_holds_archive(path):
                    found.append(path)
        except OSError:
            pass
        return found

    def _archives_in(self, folder: Path, recursive: bool) -> list[Path]:
        suffixes = self.game.mod_spec.archive_suffixes
        pattern = folder.rglob("*") if recursive else folder.iterdir()
        try:
            return [
                p for p in pattern
                if p.is_file() and p.suffix.lower() in suffixes
            ]
        except OSError:
            return []

    def scan_staged(self) -> ScanResult:
        """Index mods parked in the game's staging folders.

        Payloads stay where they are; the library only records where to find
        them. Anything the launcher will not manage is reported rather than
        quietly dropped, so an untouched folder never reads as an empty one.
        """
        result = ScanResult()
        if not self.game.mod_spec.scan_staging:
            # Games without an archive format or a load-order list have no way
            # to tell stock content from an added mod, so scanning would list
            # the base game as removable. The flag is a hard gate, not just a
            # hidden button: Motocross Madness would otherwise offer its own
            # stadiums and terrain for deletion.
            return result

        known = {
            m.link_source.lower()
            for m in self.list_mods()
            if m.link_source
        }
        prefix = self.game.mod_spec.priority_prefix

        for category, folder in self._staging_roots():
            candidates: list[tuple[Path, str, int]] = []

            # Loose archives sitting directly in the category folder.
            try:
                for child in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
                    if not child.is_file():
                        continue
                    suffix = child.suffix.lower()
                    if suffix in self.game.mod_spec.archive_suffixes:
                        priority, bare = split_priority(child.name, prefix)
                        candidates.append((child, Path(bare).stem, priority))
                    elif suffix in PACKAGED_SUFFIXES:
                        result.unmanaged.append((category, child.name))
            except OSError:
                continue

            # Folders that are a mod in their own right, at any depth.
            for mod_dir in self._mod_dirs_within(folder):
                archives = [
                    p for p in mod_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in self.game.mod_spec.archive_suffixes
                ]
                priority = max(
                    (split_priority(a.name, prefix)[0] for a in archives), default=0
                )
                # Name nested variants by their path inside the category, so
                # "YosemiteValley / For NuHook users" is distinguishable.
                relative = mod_dir.relative_to(folder)
                display = " / ".join(relative.parts)
                candidates.append((mod_dir, display, priority))

            # Folders holding no archives at all: packaged releases or docs.
            try:
                for child in folder.iterdir():
                    if (
                        child.is_dir()
                        and not self._archives_in(child, recursive=True)
                        and any(child.rglob("*"))
                    ):
                        result.unmanaged.append((category, child.name))
            except OSError:
                pass

            for source, display, priority in candidates:
                if str(source).lower() in known:
                    result.already_known += 1
                    continue
                slug = self._unique_slug(display)
                mod = Mod(
                    slug=slug,
                    name=display,
                    priority=priority,
                    detected_priority=priority,
                    category=category,
                    link_source=str(source),
                    source=str(source),
                    root=self.library / slug,
                    archive_suffixes=self.game.mod_spec.archive_suffixes,
                )
                mod.save_manifest()
                known.add(str(source).lower())
                result.added += 1

        result.added += self._scan_loose_archives(known)
        result.unmanaged.extend(self._packaged_only_folders())
        return result

    def _scan_loose_archives(self, known: set[str]) -> int:
        """Index archives sitting loose in the game folder.

        Only meaningful for a game with a load-order list. Elsewhere a root
        archive is either base game data or an already-deployed mod, and there
        is no way to tell which. With a list file there is: whatever it names is
        loaded, and an archive it does not name is simply switched off.
        """
        order = self._load_order()
        if order is None:
            return 0

        declared = {Path(d).name.lower() for d in self.game.data_files}
        suffixes = self.game.mod_spec.archive_suffixes
        added = 0
        try:
            children = sorted(
                (c for c in self.game_root.iterdir() if c.is_file()),
                key=lambda p: p.name.lower(),
            )
        except OSError:
            return 0

        for child in children:
            if child.suffix.lower() not in suffixes:
                continue
            if child.name.lower() in declared or str(child).lower() in known:
                continue

            slug = self._unique_slug(child.stem)
            mod = Mod(
                slug=slug,
                name=child.stem,
                category="Game folder",
                link_source=str(child),
                source=str(child),
                root=self.library / slug,
                archive_suffixes=suffixes,
            )
            mod.save_manifest()
            known.add(str(child).lower())
            added += 1

            # If the game is already loading it, say so rather than offering to
            # "enable" something that is on.
            if order.contains(child.name):
                mod.receipt_file.write_text(
                    json.dumps(
                        {
                            "game_root": str(self.game_root),
                            "entries": [],
                            "order": [child.name],
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        return added

    def _packaged_only_folders(self) -> list[tuple[str, str]]:
        """Top-level folders holding packaged releases but no archives.

        A NuHook release is a folder of .zip framework installers with no .ar in
        sight, so it is not a staging folder and nothing above will have looked
        at it. Reporting it anyway is the point: a folder the launcher silently
        ignores is indistinguishable from one it found nothing in.
        """
        excluded = self._excluded_folder_names()
        found: list[tuple[str, str]] = []
        try:
            children = sorted(
                (c for c in self.game_root.iterdir() if c.is_dir()),
                key=lambda p: p.name.lower(),
            )
        except OSError:
            return found

        for child in children:
            if child.name.lower() in excluded or child.name.startswith("."):
                continue
            if self._archives_in(child, recursive=True):
                continue  # a staging folder; already handled
            packaged = [
                p for p in child.rglob("*")
                if p.is_file() and p.suffix.lower() in PACKAGED_SUFFIXES
            ]
            if packaged:
                found.append((child.name, f"{len(packaged)} packaged file(s)"))
        return found

    # -- planning --------------------------------------------------------

    def plan(self, mod: Mod) -> list[PlannedFile]:
        """Where each payload file will land, with priority prefixes applied.

        While the user has not touched the priority, filenames deploy exactly as
        the payload holds them. That matters for distribution packs, where the
        author has already tuned the '!' counts against each other and any
        rewriting of ours would silently reshuffle their load order.
        """
        spec = self.game.mod_spec
        rename = spec.priority_prefix and mod.priority != mod.detected_priority

        planned: list[PlannedFile] = []
        for source, rel_str in mod.entries():
            rel = Path(rel_str)
            dest = rel
            is_top_level_archive = (
                len(rel.parts) == 1 and rel.suffix.lower() in spec.archive_suffixes
            )
            if is_top_level_archive and rename:
                _, bare = split_priority(rel.name, spec.priority_prefix)
                dest = rel.with_name(spec.priority_prefix * mod.priority + bare)
            if mod.dest_prefix:
                dest = Path(mod.dest_prefix) / dest
            planned.append(PlannedFile(source=source, dest_rel=str(dest)))
        return planned

    def conflicts(self, mod: Mod) -> dict[str, str]:
        """Destination paths this mod would take over from another enabled mod.

        Maps destination path -> owning mod name.
        """
        owners: dict[str, str] = {}
        for other in self.list_mods():
            if other.slug == mod.slug or not other.enabled:
                continue
            for entry in self._read_receipt(other):
                owners[entry["dest_rel"].lower()] = other.name
        clashes: dict[str, str] = {}
        for pf in self.plan(mod):
            owner = owners.get(pf.dest_rel.lower())
            if owner:
                clashes[pf.dest_rel] = owner
        return clashes

    # -- enable / disable ------------------------------------------------

    def _read_receipt(self, mod: Mod) -> list[dict]:
        if not mod.receipt_file.is_file():
            return []
        try:
            data = json.loads(mod.receipt_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return list(data.get("entries", []))

    def _backup_path(self, mod: Mod, dest_rel: str) -> Path:
        return self.backups / mod.slug / dest_rel

    # -- load-order list -------------------------------------------------

    def _order_path(self) -> Path | None:
        name = self.game.mod_spec.order_file
        if not name:
            return None
        found = _find_case_insensitive(self.game_root, name)
        return found if found and found.is_file() else None

    def _load_order(self) -> CountedListFile | None:
        path = self._order_path()
        if path is None:
            return None
        try:
            return CountedListFile.load(path)
        except OSError:
            return None

    def _is_archive(self, name: str) -> bool:
        return Path(name).suffix.lower() in self.game.mod_spec.archive_suffixes

    def _inside_root(self, path: Path) -> Path | None:
        """The path relative to the game folder, or None if it lives outside."""
        try:
            return path.resolve().relative_to(self.game_root.resolve())
        except (ValueError, OSError):
            return None

    def enable(self, mod: Mod) -> None:
        if mod.enabled:
            return
        if not self.game_root.is_dir():
            raise ModError(f"Game folder not found: {self.game_root}")

        entries: list[dict] = []
        order = self._load_order()
        order_added: list[str] = []
        try:
            for pf in self.plan(mod):
                src = pf.source
                dest = self.game_root / pf.dest_rel

                # With a load-order list, an archive already inside the game
                # folder just needs listing — copying it would duplicate it.
                if order is not None and self._is_archive(pf.dest_rel):
                    existing = self._inside_root(src)
                    if existing is not None:
                        if order.add(str(existing)):
                            order_added.append(str(existing))
                        continue

                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.resolve() == dest.resolve():
                    # A staged payload that already sits at its destination.
                    continue

                replaced = dest.exists()
                if replaced:
                    backup = self._backup_path(mod, pf.dest_rel)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, backup)

                shutil.copy2(src, dest)
                entries.append({"dest_rel": pf.dest_rel, "replaced": replaced})

                if order is not None and self._is_archive(pf.dest_rel):
                    if order.add(pf.dest_rel):
                        order_added.append(pf.dest_rel)

            if order is not None and order_added:
                order.save()
        except Exception:
            # Roll back so a failed enable never leaves the game half-modded.
            self._unregister(order_added)
            self._revert(mod, entries)
            raise

        mod.receipt_file.write_text(
            json.dumps(
                {
                    "game_root": str(self.game_root),
                    "entries": entries,
                    "order": order_added,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def disable(self, mod: Mod) -> None:
        self._unregister(self._read_order(mod))
        entries = self._read_receipt(mod)
        self._revert(mod, entries)
        mod.receipt_file.unlink(missing_ok=True)

    def _read_order(self, mod: Mod) -> list[str]:
        if not mod.receipt_file.is_file():
            return []
        try:
            data = json.loads(mod.receipt_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return list(data.get("order", []))

    def _unregister(self, order_entries: list[str]) -> None:
        """Take entries back out of the load-order list."""
        if not order_entries:
            return
        order = self._load_order()
        if order is None:
            return
        changed = False
        for entry in order_entries:
            changed |= order.remove(entry)
        if changed:
            try:
                order.save()
            except OSError:
                pass

    def _revert(self, mod: Mod, entries: Iterable[dict]) -> None:
        """Undo the writes described by `entries`, restoring any originals."""
        for entry in entries:
            dest = self.game_root / entry["dest_rel"]
            try:
                if entry.get("replaced"):
                    backup = self._backup_path(mod, entry["dest_rel"])
                    if backup.is_file():
                        shutil.copy2(backup, dest)
                        backup.unlink(missing_ok=True)
                    else:
                        # Backup lost: leave the modded file rather than
                        # deleting a file the game needs.
                        continue
                else:
                    dest.unlink(missing_ok=True)
            except OSError:
                # Keep reverting the rest; a locked file is reported by the
                # caller's follow-up state refresh.
                continue
        self._prune_empty_dirs(mod)

    def _prune_empty_dirs(self, mod: Mod) -> None:
        base = self.backups / mod.slug
        for d in sorted(
            (p for p in base.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            base.rmdir()
        except OSError:
            pass

    def set_priority(self, mod: Mod, priority: int) -> None:
        """Priority changes the deployed filename, so re-deploy if enabled."""
        priority = max(0, min(priority, self.game.mod_spec.max_priority))
        if priority == mod.priority:
            return
        was_enabled = mod.enabled
        if was_enabled:
            self.disable(mod)
        mod.priority = priority
        mod.save_manifest()
        if was_enabled:
            self.enable(mod)

    def sync_from_config(self, enabled_slugs: list[str]) -> list[str]:
        """Reconcile on-disk state with the saved list. Returns problems."""
        problems: list[str] = []
        wanted = set(enabled_slugs)
        for mod in self.list_mods():
            try:
                if mod.slug in wanted and not mod.enabled:
                    self.enable(mod)
                elif mod.slug not in wanted and mod.enabled:
                    self.disable(mod)
            except (ModError, OSError) as exc:
                problems.append(f"{mod.name}: {exc}")
        return problems
