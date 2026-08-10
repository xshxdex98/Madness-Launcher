"""Checks for the sidebar's live launcher count.

Deliberately offline: the connection itself is exercised by running two real
launchers against each other, but the state machine around it — what the label
says, when it retries, when it must not connect at all — has to be testable
without a network, or it will only ever be tested by accident.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="madness-presence-"))
os.environ["MADNESS_LAUNCHER_HOME"] = str(SANDBOX)

from PySide6.QtWidgets import QApplication  # noqa: E402

from madness_launcher.chat import IrcClient  # noqa: E402
from madness_launcher.config import Config  # noqa: E402
from madness_launcher.ui import theme  # noqa: E402
from madness_launcher.ui.main_window import MainWindow  # noqa: E402
from madness_launcher.ui.presence import MAX_NICK_ATTEMPTS, Presence  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


app = QApplication.instance() or QApplication(sys.argv)
app.setStyleSheet(theme.stylesheet())


def fresh(username: str = "Tester", enabled: bool = True) -> Config:
    config = Config()
    config.settings.username = username
    config.settings.show_online_count = enabled
    # Somewhere that cannot resolve, so nothing in this file dials out even if
    # a connection attempt slips through.
    config.settings.chat_host = "invalid.test"
    return config


print("the setting is honoured")
off = Presence(fresh(enabled=False))
off.start()
check("disabled: no connection is attempted", not off.client.online)
check("disabled: state says so", off.state == "disabled", off.state)
check("disabled: count is zero", off.count == 0)

print("\na name is required before announcing anything")
anon = Presence(fresh(username=""))
anon.start()
check("no username: stays offline", anon.state == "offline", anon.state)
check("no username: no connection", not anon.client.online)

print("\nthe label reads correctly")
config = fresh()
window = MainWindow(config)

cases = {
    ("disabled", 0): "Count is off",
    ("connecting", 0): "Counting…",
    ("online", 1): "1 launcher open",
    ("online", 2): "2 launchers open",
    ("online", 17): "17 launchers open",
    ("offline", 0): "Offline",
}
for (state, count), expected in cases.items():
    window.presence._state = state
    window.presence._count = count
    window._refresh_presence()
    check(
        f"{state}/{count} reads {expected!r}",
        window.presence_label.text() == expected,
        repr(window.presence_label.text()),
    )

# Singular vs plural is the sort of thing that silently reads wrong forever.
window.presence._state = "online"
window.presence._count = 1
window._refresh_presence()
check("one is singular", "1 launcher open" == window.presence_label.text())
check("tooltip is singular too", "person is" in window.presence_label.toolTip())
window.presence._count = 3
window._refresh_presence()
check("three is plural", "3 launchers open" == window.presence_label.text())
check("tooltip is plural too", "people are" in window.presence_label.toolTip())

print("\nwithout a username the label says what to do")
window.config.settings.username = ""
window.presence._state = "offline"
window.presence._count = 0
window._refresh_presence()
check(
    "prompts for a username rather than saying Offline",
    window.presence_label.text() == "Set a username",
    window.presence_label.text(),
)
window.config.settings.username = "Tester"

print("\nthe dot tracks the state")
for state, expected in (
    ("online", "good"),
    ("connecting", "warn"),
    ("offline", "bad"),
    ("disabled", "idle"),
):
    window.presence._state = state
    window.presence._count = 1 if state == "online" else 0
    window._refresh_presence()
    check(f"{state} dot is {expected}", window.presence_dot.state == expected,
          window.presence_dot.state)

print("\na taken nickname is retried, not surrendered")
retry = Presence(fresh(username="Taken"))
attempts: list[str] = []
retry._connect_now = lambda nick: attempts.append(nick)  # type: ignore[assignment]
for _ in range(MAX_NICK_ATTEMPTS + 2):
    retry._on_nick_rejected("Taken", "in use")
check(
    "it gives up rather than looping forever",
    retry._attempt <= MAX_NICK_ATTEMPTS,
    str(retry._attempt),
)
check("and ends up offline", retry.state == "offline", retry.state)

print("\nthe chat page must not open a second connection")
chat = window._chat_page()
check("chat reuses the presence client", chat.client is window.presence.client)
check("chat knows it is shared", chat.shares_client)
check(
    "presence client is a real IRC client",
    isinstance(window.presence.client, IrcClient),
)

print("\nreleasing the chat page leaves the count alone")
before = window.presence.client
chat.release()
check("the shared client survives release()", window.presence.client is before)

print("\nthe user taking over suppresses automatic retries")
held = Presence(fresh())
held.note_user_connected()
held._on_connected_changed(False)
check(
    "no retry is scheduled while the user holds the connection",
    not held._retry.isActive(),
)
held.note_user_disconnected()
check("leaving chat clears the count", held.count == 0)
check("and reports offline", held.state == "offline", held.state)

print("\nan unexpected drop does schedule a retry")
dropped = Presence(fresh())
dropped._on_connected_changed(False)
check("a retry is queued", dropped._retry.isActive())
check("count is cleared", dropped.count == 0)
dropped._retry.stop()

print("\nturning the setting off disconnects")
window.config.settings.show_online_count = True
window._set_online_count_enabled(False)
check("setting is saved", window.config.settings.show_online_count is False)
check("presence reports disabled", window.presence.state == "disabled",
      window.presence.state)
check("label follows", window.presence_label.text() == "Count is off",
      window.presence_label.text())

print("\nclosing the window closes the socket")
window.close()
check("presence is not left connected", not window.presence.client.online)

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all presence checks passed")
