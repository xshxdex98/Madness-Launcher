"""Starting a game with a hook DLL loaded into it.

The usual way to get a DLL into an old game is to drop a proxy next to the
executable under the name of something it already imports. That route is taken
here: Monster Truck Madness imports DDRAW.dll, and that file is now dgVoodoo.
Stacking a second proxy on top of a wrapper is fragile, and a proxy that shares
its name with the DLL it forwards to will happily load itself and take the host
down with it.

So the launcher injects instead. It starts the process suspended, writes the
DLL path into it, runs LoadLibraryA on a remote thread, and only then lets the
game's entry point run — which is early enough for patches to land before the
game has executed a single instruction of its own.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass
from pathlib import Path

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CREATE_SUSPENDED = 0x00000004
INFINITE = 0xFFFFFFFF
MEM_COMMIT_RESERVE = 0x1000 | 0x2000
PAGE_READWRITE = 0x04
MEM_RELEASE = 0x8000
WAIT_TIMEOUT = 0x102


class STARTUPINFOA(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("lpReserved", wt.LPSTR), ("lpDesktop", wt.LPSTR),
        ("lpTitle", wt.LPSTR), ("dwX", wt.DWORD), ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD), ("dwXCountChars", wt.DWORD),
        ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
        ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD),
    ]


class InjectionError(Exception):
    pass


@dataclass
class InjectedProcess:
    pid: int
    handle: int
    thread: int


def _fail(step: str) -> None:
    raise InjectionError(f"{step} failed: {ctypes.FormatError(ctypes.get_last_error())}")


def launch_with_dll(
    executable: Path,
    dll: Path,
    args: list[str] | None = None,
    working_dir: Path | None = None,
) -> InjectedProcess:
    """Start `executable` suspended, load `dll` into it, then let it run."""
    executable = Path(executable)
    dll = Path(dll).resolve()
    if not dll.is_file():
        raise InjectionError(f"{dll} does not exist.")

    command = " ".join([f'"{executable}"', *(args or [])])
    startup = STARTUPINFOA()
    startup.cb = ctypes.sizeof(startup)
    info = PROCESS_INFORMATION()

    created = kernel32.CreateProcessA(
        str(executable).encode(),
        ctypes.create_string_buffer(command.encode()),
        None, None, False, CREATE_SUSPENDED, None,
        str(working_dir or executable.parent).encode(),
        ctypes.byref(startup), ctypes.byref(info),
    )
    if not created:
        _fail("CreateProcess")

    try:
        _inject(info.hProcess, dll)
    except Exception:
        # Never leave a suspended process behind for the user to find in
        # Task Manager with no window and no way to close it.
        kernel32.TerminateProcess(info.hProcess, 1)
        kernel32.CloseHandle(info.hThread)
        kernel32.CloseHandle(info.hProcess)
        raise

    if kernel32.ResumeThread(info.hThread) == -1:
        _fail("ResumeThread")

    return InjectedProcess(info.dwProcessId, info.hProcess, info.hThread)


def _inject(process: int, dll: Path) -> None:
    encoded = str(dll).encode() + b"\0"

    remote = kernel32.VirtualAllocEx(
        process, None, len(encoded), MEM_COMMIT_RESERVE, PAGE_READWRITE
    )
    if not remote:
        _fail("VirtualAllocEx")

    try:
        written = ctypes.c_size_t(0)
        if not kernel32.WriteProcessMemory(
            process, ctypes.c_void_p(remote), encoded, len(encoded),
            ctypes.byref(written)
        ):
            _fail("WriteProcessMemory")

        # kernel32 sits at the same address in every process on a given boot,
        # so this process's LoadLibraryA is valid in the target too.
        load_library = kernel32.GetProcAddress(
            kernel32.GetModuleHandleA(b"kernel32.dll"), b"LoadLibraryA"
        )
        if not load_library:
            _fail("GetProcAddress(LoadLibraryA)")

        thread = kernel32.CreateRemoteThread(
            process, None, 0, ctypes.c_void_p(load_library),
            ctypes.c_void_p(remote), 0, None,
        )
        if not thread:
            _fail("CreateRemoteThread")

        try:
            # 15s is generous for a LoadLibrary; longer means something is wrong.
            if kernel32.WaitForSingleObject(thread, 15000) == WAIT_TIMEOUT:
                raise InjectionError(
                    "The hook DLL did not finish loading within 15 seconds."
                )
            module = wt.DWORD(0)
            kernel32.GetExitCodeThread(thread, ctypes.byref(module))
            if module.value == 0:
                raise InjectionError(
                    f"The game refused to load {dll.name}. It is most likely "
                    "the wrong architecture — the DLL must be 32-bit."
                )
        finally:
            kernel32.CloseHandle(thread)
    finally:
        kernel32.VirtualFreeEx(process, ctypes.c_void_p(remote), 0, MEM_RELEASE)
