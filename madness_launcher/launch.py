"""Starting a game process."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .detect import _find_case_insensitive
from .games.base import GameDef, build_args


class LaunchError(Exception):
    pass


@dataclass
class LaunchPlan:
    executable: Path
    args: list[str]
    working_dir: Path
    # Set when the game is started through an injector so a mod hook loads
    # with it. The game executable stays in `executable`; these only change
    # how the process is created.
    injector: Path | None = None
    hook_dll: Path | None = None

    @property
    def hooked(self) -> bool:
        return self.injector is not None and self.hook_dll is not None

    def command(self) -> list[str]:
        if self.hooked:
            return [
                str(self.injector), str(self.executable), str(self.hook_dll),
                *self.args,
            ]
        return [str(self.executable), *self.args]

    def display_command(self) -> str:
        parts = [self.executable.name] + self.args
        rendered = " ".join(f'"{p}"' if " " in p else p for p in parts)
        if self.hooked:
            rendered += f"     (with {self.hook_dll.name})"
        return rendered


# Sentinel target id meaning "use the executable named in custom_exe".
CUSTOM_TARGET = "__custom__"


def build_plan(
    game: GameDef,
    root: Path,
    target_id: str,
    options: dict,
    extra_args: str = "",
    custom_exe: str = "",
) -> LaunchPlan:
    if target_id == CUSTOM_TARGET:
        if not custom_exe:
            raise LaunchError("No executable has been chosen for this game.")
        filename = custom_exe
    else:
        target = game.target(target_id) or game.default_target()
        filename = target.filename

    exe = _find_case_insensitive(Path(root), filename)
    if exe is None:
        raise LaunchError(
            f"{filename} was not found in {root}.\n\n"
            "Pick a different executable on the Play tab, or re-select the "
            "game folder."
        )
    # Load the game's mod hook, when both it and its injector are present.
    # Missing either is not an error: the game runs perfectly well unhooked,
    # and refusing to launch over an optional add-on would be obstructive.
    injector = hook = None
    if game.injector and game.hook_dll:
        injector = _find_case_insensitive(Path(root), game.injector)
        hook = _find_case_insensitive(Path(root), game.hook_dll)
        if not (injector and hook):
            injector = hook = None

    return LaunchPlan(
        executable=exe,
        args=build_args(game, options, extra_args),
        working_dir=Path(root),
        injector=injector,
        hook_dll=hook,
    )


def read_args_file(game: GameDef, root: Path) -> str | None:
    """Contents of the engine's own argument file, if the game uses one.

    Surfaced in the UI because those arguments apply on top of ours, and a
    stale commandline.txt is a common source of "my setting did nothing".
    """
    if not game.args_file:
        return None
    f = _find_case_insensitive(Path(root), game.args_file)
    if f is None or not f.is_file():
        return None
    try:
        return f.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def forced_on_flags(game: GameDef, root: Path) -> list[str]:
    """On-only flags that the engine's own argument file switches on.

    The engine appends the real command line *after* the contents of its
    argument file and lets the last occurrence win, so for ordinary options the
    launcher's choice takes precedence. Flags with no negation are the
    exception: once the file sets one, nothing on the command line can undo it,
    so the UI has to say so rather than pretend the checkbox works.
    """
    contents = read_args_file(game, root)
    if not contents:
        return []
    tokens = {t.lstrip("-").split("=")[0].lower() for t in contents.split()}
    return [
        spec.key
        for spec in game.options
        if spec.kind == "bool" and not spec.negatable and spec.key.lower() in tokens
    ]


def pin_to_single_core(process: subprocess.Popen) -> bool:
    """Restrict a process to one CPU.

    Games of this era time their physics against a millisecond clock and assume
    one core. Monster Truck Madness on a modern machine renders a frame in
    under a millisecond, the delta rounds to zero, and the truck will not move
    off the start line however hard you press forward. Pinning it to a single
    core slows it into a range the integrator can cope with.
    """
    try:
        import ctypes

        handle = getattr(process, "_handle", None)
        if handle is None:
            return False
        return bool(ctypes.WinDLL("kernel32").SetProcessAffinityMask(int(handle), 1))
    except Exception:
        return False


ERROR_ELEVATION_REQUIRED = 740
ERROR_CANCELLED = 1223

# Where Windows records per-executable compatibility settings.
_COMPAT_KEYS = (
    ("HKEY_CURRENT_USER", r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"),
    ("HKEY_LOCAL_MACHINE", r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"),
)


def compatibility_layers(executable: Path) -> list[str]:
    """Compatibility settings Windows has recorded for this executable.

    Worth surfacing because they explain behaviour the launcher cannot control:
    RUNASADMIN means every launch will raise a UAC prompt, and the various
    WINXP/VISTA layers change how the game sees the OS.
    """
    try:
        import winreg
    except ImportError:  # pragma: no cover - Windows only
        return []

    target = str(executable)
    for root_name, subkey in _COMPAT_KEYS:
        root = getattr(winreg, root_name)
        try:
            with winreg.OpenKey(root, subkey) as key:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    if name.lower() == target.lower():
                        # Values look like "~ RUNASADMIN WINXPSP3"; the leading
                        # token is a scope marker, not a layer.
                        return [
                            part for part in str(value).split()
                            if part not in ("~", "$")
                        ]
        except OSError:
            continue
    return []


def requires_elevation(executable: Path) -> bool:
    return "RUNASADMIN" in compatibility_layers(executable)


class ElevatedProcess:
    """The handle of a process started through the UAC prompt.

    ShellExecuteEx is the only way to start an elevated child, and it returns a
    raw handle rather than a Popen. This exposes just enough of the same shape
    for the caller to treat the two alike.
    """

    def __init__(self, handle: int, pid: int = 0):
        self._handle = handle
        self.pid = pid

    def poll(self):  # pragma: no cover - parity with Popen
        return None


def _launch_elevated(plan: "LaunchPlan"):
    """Start the game through the UAC prompt.

    Needed when the executable is marked "Run as administrator" in its
    compatibility settings. Windows then refuses a plain CreateProcess from an
    unelevated launcher with ERROR_ELEVATION_REQUIRED, and the only way to
    honour the user's own setting is to ask for elevation properly.
    """
    import ctypes
    import ctypes.wintypes as wt

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wt.HANDLE),
            ("lpVerb", wt.LPCWSTR), ("lpFile", wt.LPCWSTR),
            ("lpParameters", wt.LPCWSTR), ("lpDirectory", wt.LPCWSTR),
            ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wt.LPCWSTR),
            ("hkeyClass", wt.HKEY), ("dwHotKey", wt.DWORD),
            ("hIconOrMonitor", wt.HANDLE), ("hProcess", wt.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NOASYNC = 0x00000100

    command = plan.command()
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = command[0]
    info.lpParameters = subprocess.list2cmdline(command[1:])
    info.lpDirectory = str(plan.working_dir)
    info.nShow = 1  # SW_SHOWNORMAL

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == ERROR_CANCELLED:
            raise LaunchError(
                "Windows asked for administrator permission and it was "
                "declined, so the game was not started.\n\n"
                f"{Path(command[0]).name} is set to 'Run as administrator' in "
                "its compatibility settings. Clear that checkbox if you would "
                "rather it started without asking."
            )
        raise LaunchError(
            f"Could not start {Path(command[0]).name} with elevation: "
            f"{ctypes.FormatError(code)}"
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    pid = kernel32.GetProcessId(int(info.hProcess)) if info.hProcess else 0
    return ElevatedProcess(int(info.hProcess), pid)


def launch(plan: LaunchPlan) -> subprocess.Popen:
    """Start the game detached, so closing the launcher never kills it."""
    try:
        return subprocess.Popen(
            plan.command(),
            cwd=str(plan.working_dir),
            close_fds=True,
            # The injector is a console program; keep its window off screen.
            creationflags=subprocess.CREATE_NO_WINDOW if plan.hooked else 0,
        )
    except OSError as exc:
        # The executable is marked "Run as administrator", so an unelevated
        # CreateProcess is refused outright. Ask for elevation rather than
        # reporting a failure the user cannot act on.
        if getattr(exc, "winerror", None) == ERROR_ELEVATION_REQUIRED:
            return _launch_elevated(plan)
        raise LaunchError(f"Could not start {plan.executable.name}: {exc}") from exc
