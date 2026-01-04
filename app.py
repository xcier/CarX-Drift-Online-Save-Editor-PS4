from __future__ import annotations
import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor

from ui.main_window import MainWindow


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(24, 24, 27))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(235, 235, 240))
    pal.setColor(QPalette.ColorRole.Base, QColor(18, 18, 20))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(28, 28, 32))
    pal.setColor(QPalette.ColorRole.Text, QColor(235, 235, 240))
    pal.setColor(QPalette.ColorRole.Button, QColor(32, 32, 36))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(235, 235, 240))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(90, 120, 255))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(140, 140, 150))

    app.setPalette(pal)

    # Small stylesheet polish (rounded + readable)
    app.setStyleSheet("""
        QGroupBox {
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 10px;
            margin-top: 12px;
            padding: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 6px;
        }
        QPushButton {
            padding: 7px 12px;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.18);
        }
        QPushButton:hover {
            border-color: rgba(255,255,255,0.35);
        }
        QLineEdit, QPlainTextEdit, QSpinBox {
            padding: 6px 8px;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.15);
            background: rgba(0,0,0,0.30);
        }
        QCheckBox {
            spacing: 8px;
        }
    """)


def main() -> int:
    app = QApplication(sys.argv)
    apply_dark_theme(app)

    w = MainWindow()
    w.resize(1200, 750)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
