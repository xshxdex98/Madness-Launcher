"""Entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME, paths
from .config import Config
from .ui import fonts, icons, palette, theme
from .ui.main_window import MainWindow


def main() -> int:
    paths.ensure_dirs(paths.app_root(), paths.log_dir())

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("MadnessLauncher")
    app.setFont(QFont(theme.FONT, 9))
    # The titlebar and Alt-Tab entry, which do NOT inherit the executable's
    # icon the way the taskbar button does — without this the window shows the
    # blank default. Set on the application so every window and dialog gets it.
    window_icon = paths.resource("assets", "madness_crew.ico")
    if window_icon.is_file():
        app.setWindowIcon(QIcon(str(window_icon)))
    config = Config.load()
    # The saved palette goes on before anything is painted. The glyphs are
    # drawn in it and the stylesheet points at them by path, so applying it
    # afterwards would mean painting the whole interface twice on every start.
    theme.apply(palette.Palette.from_dict(config.settings.theme))
    theme.set_icons(icons.ensure_icons())

    # Borrow the game's own display face, if a configured copy ships it.
    family = fonts.load_display_font(
        [Path(i.path) for i in config.installs.values() if i.path]
    )
    if family:
        theme.set_display_font(family)

    app.setStyleSheet(theme.stylesheet())

    window = MainWindow(config)
    window.show()
    # Asked after the window is up, so the dialog has something to sit over.
    window.prompt_first_run()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
