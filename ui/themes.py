from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    name: str
    dark: bool
    window: str
    surface: str
    surface_2: str
    input: str
    text: str
    muted: str
    border: str
    hover: str
    selected: str
    accent: str
    accent_hover: str
    accent_text: str
    danger: str
    success: str
    warning: str


THEMES: Dict[str, Theme] = {
    "Midnight Drift": Theme(
        name="Midnight Drift",
        dark=True,
        window="#0f1117",
        surface="#161b24",
        surface_2="#202838",
        input="#101620",
        text="#edf2ff",
        muted="#9aa8bd",
        border="#2b3548",
        hover="#263247",
        selected="#253b66",
        accent="#7c9cff",
        accent_hover="#9ab3ff",
        accent_text="#08111f",
        danger="#fb7185",
        success="#34d399",
        warning="#fbbf24",
    ),
    "Carbon Violet": Theme(
        name="Carbon Violet",
        dark=True,
        window="#111014",
        surface="#191720",
        surface_2="#262130",
        input="#13111a",
        text="#f5f3ff",
        muted="#b7adc9",
        border="#342d42",
        hover="#312a40",
        selected="#3b2f66",
        accent="#a78bfa",
        accent_hover="#c4b5fd",
        accent_text="#10091f",
        danger="#fb7185",
        success="#4ade80",
        warning="#facc15",
    ),
    "Emerald Garage": Theme(
        name="Emerald Garage",
        dark=True,
        window="#0d1412",
        surface="#13201d",
        surface_2="#1b302b",
        input="#0e1916",
        text="#ecfdf5",
        muted="#9fc2b6",
        border="#254039",
        hover="#223b35",
        selected="#1f4f45",
        accent="#34d399",
        accent_hover="#6ee7b7",
        accent_text="#04130f",
        danger="#fb7185",
        success="#22c55e",
        warning="#f59e0b",
    ),
    "Clean Light": Theme(
        name="Clean Light",
        dark=False,
        window="#f5f7fb",
        surface="#ffffff",
        surface_2="#eef2f7",
        input="#ffffff",
        text="#111827",
        muted="#64748b",
        border="#d8e0eb",
        hover="#e8eef7",
        selected="#dce8ff",
        accent="#3266d9",
        accent_hover="#204fb3",
        accent_text="#ffffff",
        danger="#dc2626",
        success="#16a34a",
        warning="#d97706",
    ),
    "Graphite Orange": Theme(
        name="Graphite Orange",
        dark=True,
        window="#101112",
        surface="#191b1f",
        surface_2="#262a31",
        input="#11151a",
        text="#f8fafc",
        muted="#a6afbd",
        border="#303743",
        hover="#303846",
        selected="#4a3425",
        accent="#fb923c",
        accent_hover="#fdba74",
        accent_text="#1c0d03",
        danger="#f43f5e",
        success="#22c55e",
        warning="#facc15",
    ),
    "Neon Synth": Theme(
        name="Neon Synth",
        dark=True,
        window="#0b0a13",
        surface="#151326",
        surface_2="#221b3f",
        input="#100f1d",
        text="#f8f7ff",
        muted="#a9a1c7",
        border="#32295a",
        hover="#2d2750",
        selected="#18395a",
        accent="#22d3ee",
        accent_hover="#67e8f9",
        accent_text="#03161b",
        danger="#fb7185",
        success="#2dd4bf",
        warning="#fde047",
    ),
    "Ocean Blue": Theme(
        name="Ocean Blue",
        dark=True,
        window="#07111f",
        surface="#0d1b2e",
        surface_2="#132942",
        input="#091624",
        text="#eef7ff",
        muted="#93aac4",
        border="#23415f",
        hover="#193653",
        selected="#174b75",
        accent="#38bdf8",
        accent_hover="#7dd3fc",
        accent_text="#02121c",
        danger="#fb7185",
        success="#34d399",
        warning="#fbbf24",
    ),
    "Track Day Red": Theme(
        name="Track Day Red",
        dark=True,
        window="#120c0d",
        surface="#1d1416",
        surface_2="#2b1d20",
        input="#140f10",
        text="#fff1f2",
        muted="#c7a2a8",
        border="#44272d",
        hover="#3a2328",
        selected="#5a2430",
        accent="#f43f5e",
        accent_hover="#fb7185",
        accent_text="#21040a",
        danger="#ef4444",
        success="#4ade80",
        warning="#f59e0b",
    ),
    "Royal Sapphire": Theme(
        name="Royal Sapphire",
        dark=True,
        window="#0c1020",
        surface="#151a31",
        surface_2="#20284a",
        input="#10162a",
        text="#f1f5ff",
        muted="#aab7d4",
        border="#2d3a66",
        hover="#28345d",
        selected="#273d7a",
        accent="#60a5fa",
        accent_hover="#93c5fd",
        accent_text="#041126",
        danger="#fb7185",
        success="#34d399",
        warning="#fbbf24",
    ),
    "Arctic White": Theme(
        name="Arctic White",
        dark=False,
        window="#f7fafc",
        surface="#ffffff",
        surface_2="#edf4fb",
        input="#ffffff",
        text="#0f172a",
        muted="#607089",
        border="#d6e2ee",
        hover="#e9f1fb",
        selected="#d8ecff",
        accent="#0284c7",
        accent_hover="#0369a1",
        accent_text="#ffffff",
        danger="#dc2626",
        success="#16a34a",
        warning="#ca8a04",
    ),
    "Cherry Blossom": Theme(
        name="Cherry Blossom",
        dark=False,
        window="#fff7fb",
        surface="#ffffff",
        surface_2="#fdeaf3",
        input="#ffffff",
        text="#2a1420",
        muted="#8a6174",
        border="#efcfe0",
        hover="#fae0ec",
        selected="#f8cfe0",
        accent="#db2777",
        accent_hover="#be185d",
        accent_text="#ffffff",
        danger="#dc2626",
        success="#16a34a",
        warning="#d97706",
    ),
    "Solar Sand": Theme(
        name="Solar Sand",
        dark=False,
        window="#fbf6ea",
        surface="#fffaf0",
        surface_2="#f3ead7",
        input="#fffdf7",
        text="#2c2418",
        muted="#756a5a",
        border="#ddd0b7",
        hover="#eee3ce",
        selected="#ead9b6",
        accent="#b45309",
        accent_hover="#92400e",
        accent_text="#ffffff",
        danger="#dc2626",
        success="#15803d",
        warning="#b45309",
    ),
}

DEFAULT_THEME = "Midnight Drift"
THEME_NAMES = tuple(THEMES.keys())


def _qcolor(value: str) -> QColor:
    return QColor(value)


def is_dark_theme(name: str) -> bool:
    return THEMES.get(name, THEMES[DEFAULT_THEME]).dark


def _palette(theme: Theme) -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, _qcolor(theme.window))
    pal.setColor(QPalette.ColorRole.WindowText, _qcolor(theme.text))
    pal.setColor(QPalette.ColorRole.Base, _qcolor(theme.input))
    pal.setColor(QPalette.ColorRole.AlternateBase, _qcolor(theme.surface_2))
    pal.setColor(QPalette.ColorRole.ToolTipBase, _qcolor(theme.surface))
    pal.setColor(QPalette.ColorRole.ToolTipText, _qcolor(theme.text))
    pal.setColor(QPalette.ColorRole.Text, _qcolor(theme.text))
    pal.setColor(QPalette.ColorRole.Button, _qcolor(theme.surface_2))
    pal.setColor(QPalette.ColorRole.ButtonText, _qcolor(theme.text))
    pal.setColor(QPalette.ColorRole.BrightText, _qcolor(theme.danger))
    pal.setColor(QPalette.ColorRole.Highlight, _qcolor(theme.accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, _qcolor(theme.accent_text))
    pal.setColor(QPalette.ColorRole.PlaceholderText, _qcolor(theme.muted))
    return pal


def build_stylesheet(theme: Theme) -> str:
    return f"""
    * {{
        font-family: "Segoe UI", "Inter", "Arial";
        font-size: 10pt;
        color: {theme.text};
        selection-background-color: {theme.accent};
        selection-color: {theme.accent_text};
    }}

    QWidget {{
        background-color: {theme.window};
    }}

    QMainWindow, QDialog {{
        background-color: {theme.window};
    }}

    QFrame#HeroCard {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 {theme.surface}, stop:1 {theme.surface_2});
        border: none;
        border-radius: 18px;
    }}

    QLabel#AppTitle {{
        background: transparent;
        color: {theme.text};
        font-size: 22pt;
        font-weight: 800;
        letter-spacing: 0.4px;
    }}

    QLabel#AppSubtitle {{
        background: transparent;
        color: {theme.muted};
        font-size: 10.5pt;
        font-weight: 500;
    }}

    QLabel#AuthorBadge {{
        background-color: {theme.window};
        color: {theme.muted};
        border: 1px solid {theme.border};
        border-radius: 12px;
        padding: 6px 12px;
        font-weight: 600;
    }}

    QLabel#SyncPill {{
        border-radius: 10px;
        padding: 4px 10px;
        font-weight: 700;
    }}

    QLabel#SyncPill[state="synced"] {{
        background-color: {theme.surface_2};
        color: {theme.success};
    }}

    QLabel#SyncPill[state="dirty"] {{
        background-color: {theme.surface_2};
        color: {theme.warning};
    }}

    QGroupBox {{
        background-color: {theme.surface};
        border: none;
        border-radius: 16px;
        margin-top: 20px;
        padding: 20px 14px 14px 14px;
        font-weight: 650;
    }}

    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 14px;
        top: 6px;
        padding: 0 8px;
        color: {theme.muted};
        background-color: transparent;
    }}

    QLabel {{
        background-color: transparent;
    }}

    QLineEdit,
    QTextEdit,
    QPlainTextEdit,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox {{
        background-color: {theme.input};
        border: 1px solid {theme.border};
        border-radius: 10px;
        padding: 7px 10px;
        min-height: 22px;
    }}

    QLineEdit:focus,
    QTextEdit:focus,
    QPlainTextEdit:focus,
    QSpinBox:focus,
    QDoubleSpinBox:focus,
    QComboBox:focus {{
        border: 1px solid {theme.accent};
        background-color: {theme.surface};
    }}

    QLineEdit:disabled,
    QTextEdit:disabled,
    QPlainTextEdit:disabled,
    QSpinBox:disabled,
    QDoubleSpinBox:disabled,
    QComboBox:disabled {{
        color: {theme.muted};
        background-color: {theme.surface_2};
    }}

    QComboBox::drop-down {{
        border: none;
        width: 28px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {theme.surface};
        border: 1px solid {theme.border};
        border-radius: 10px;
        outline: 0;
        selection-background-color: {theme.selected};
        selection-color: {theme.text};
    }}

    QPushButton,
    QToolButton {{
        background-color: {theme.surface_2};
        border: none;
        border-radius: 10px;
        padding: 8px 14px;
        font-weight: 650;
        min-height: 22px;
    }}

    QPushButton:hover,
    QToolButton:hover {{
        background-color: {theme.hover};
    }}

    QPushButton:pressed,
    QToolButton:pressed {{
        background-color: {theme.selected};
    }}

    QPushButton[variant="primary"],
    QToolButton[variant="primary"] {{
        background-color: {theme.accent};
        color: {theme.accent_text};
    }}

    QPushButton[variant="primary"]:hover,
    QToolButton[variant="primary"]:hover {{
        background-color: {theme.accent_hover};
        color: {theme.accent_text};
    }}

    QPushButton[variant="danger"] {{
        background-color: {theme.danger};
        color: #ffffff;
    }}

    QPushButton:disabled,
    QToolButton:disabled {{
        background-color: {theme.surface_2};
        color: {theme.muted};
    }}

    QCheckBox {{
        spacing: 9px;
        background-color: transparent;
    }}

    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 6px;
        border: 1px solid {theme.border};
        background-color: {theme.input};
    }}

    QCheckBox::indicator:checked {{
        background-color: {theme.accent};
        border: 1px solid {theme.accent};
    }}

    QTabWidget::pane {{
        border: 0px;
        background-color: {theme.window};
        top: 0px;
    }}

    QTabWidget#MainTabs::pane {{
        border: 0px;
        background-color: {theme.window};
    }}

    QTabWidget::tab-bar {{
        alignment: left;
        left: 0px;
        top: 0px;
    }}

    QTabBar {{
        background: transparent;
        border: none;
    }}

    QTabBar::base {{
        height: 0px;
        border: 0px;
        background: transparent;
    }}

    QTabBar#MainTabBar {{
        background: transparent;
        border: none;
    }}

    QTabBar::tab:top {{
        background-color: {theme.surface};
        border: none;
        border-radius: 11px;
        margin: 0 6px 8px 0;
        padding: 9px 14px;
        color: {theme.muted};
        font-weight: 650;
    }}

    QTabBar::tab:top:selected {{
        background-color: {theme.selected};
        color: {theme.text};
    }}

    QTabBar::tab:top:hover {{
        background-color: {theme.hover};
        color: {theme.text};
    }}

    QTabBar#MainTabBar::tab:left {{
        background-color: {theme.surface};
        border: none;
        border-radius: 12px;
        margin: 4px 10px 4px 0;
        padding: 11px 18px;
        min-width: 190px;
        min-height: 28px;
        color: {theme.muted};
        font-weight: 700;
        text-align: left;
    }}

    QTabBar#MainTabBar::tab:left:selected {{
        background-color: {theme.selected};
        color: {theme.text};
    }}

    QTabBar#MainTabBar::tab:left:hover {{
        background-color: {theme.hover};
        color: {theme.text};
    }}

    QTableWidget,
    QTreeWidget,
    QListWidget {{
        background-color: {theme.input};
        alternate-background-color: {theme.surface_2};
        border: none;
        border-radius: 12px;
        outline: 0;
        gridline-color: {theme.border};
    }}

    QTableWidget::item,
    QTreeWidget::item,
    QListWidget::item {{
        padding: 6px;
        border: none;
    }}

    QTableWidget::item:selected,
    QTreeWidget::item:selected,
    QListWidget::item:selected {{
        background-color: {theme.selected};
        color: {theme.text};
    }}

    QHeaderView::section {{
        background-color: {theme.surface_2};
        color: {theme.muted};
        border: none;
        border-right: 1px solid {theme.border};
        padding: 7px 8px;
        font-weight: 750;
    }}

    QToolBar {{
        background-color: {theme.surface};
        border: none;
        border-radius: 14px;
        padding: 6px;
        spacing: 6px;
    }}

    QToolBar::separator {{
        background-color: {theme.border};
        width: 1px;
        margin: 5px 8px;
    }}

    QStatusBar {{
        background-color: {theme.surface};
        border-top: 1px solid {theme.border};
    }}

    QStatusBar QLabel {{
        background-color: transparent;
    }}

    QScrollBar:vertical {{
        background-color: transparent;
        width: 12px;
        margin: 2px;
    }}

    QScrollBar::handle:vertical {{
        background-color: {theme.border};
        border-radius: 6px;
        min-height: 26px;
    }}

    QScrollBar::handle:vertical:hover {{
        background-color: {theme.muted};
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: transparent;
        border: none;
        height: 0px;
    }}

    QScrollBar:horizontal {{
        background-color: transparent;
        height: 12px;
        margin: 2px;
    }}

    QScrollBar::handle:horizontal {{
        background-color: {theme.border};
        border-radius: 6px;
        min-width: 26px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background-color: {theme.muted};
    }}

    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: transparent;
        border: none;
        width: 0px;
    }}

    QSplitter::handle {{
        background-color: {theme.border};
        border-radius: 3px;
    }}
    """


def apply_app_theme(app: QApplication, name: str = DEFAULT_THEME) -> None:
    theme = THEMES.get(name, THEMES[DEFAULT_THEME])
    app.setStyle("Fusion")
    app.setPalette(_palette(theme))
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(build_stylesheet(theme))
