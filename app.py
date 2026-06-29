from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.themes import DEFAULT_THEME, apply_app_theme


def apply_dark_theme(app: QApplication) -> None:
    # Backwards-compatible helper for older entry points/imports.
    apply_app_theme(app, DEFAULT_THEME)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("CarX Drift Save Editor")
    app.setOrganizationName("ProtoBuffers")
    apply_app_theme(app, DEFAULT_THEME)

    w = MainWindow()
    w.resize(1280, 820)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
