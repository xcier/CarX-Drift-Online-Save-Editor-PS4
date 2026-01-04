from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit, QPushButton,
    QFileDialog, QPlainTextEdit, QMessageBox, QCheckBox, QFormLayout, QSpinBox,
    QTabWidget
)

from core.extract import extract
from core.apply_presets import apply_updates_to_blocks
from core.repack import repack

# Optional: unlock lists if your project includes them
try:
    from core.presets import AVAILABLE_CARS, AVAILABLE_TRACKS
except Exception:
    AVAILABLE_CARS = []
    AVAILABLE_TRACKS = []


def _seconds_to_duration_str(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class MainWindow(QWidget):
    """
    Main GUI for:
      - Extracting memory*.dat into blocks/
      - Applying editable presets (currency + stats + unlocks)
      - Repacking offset-safely back into a new memory.dat

    Includes Dark/Light mode toggle.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CarX Drift PS4 - Presets (Extract / Apply / Repack)")

        self.base_dat: Optional[Path] = None
        self.work_dir: Optional[Path] = None

        self._dark_enabled = True
        self._build_ui()
        self.apply_dark_theme()  # default

    # ---------------------------
    # Theme
    # ---------------------------

    def apply_dark_theme(self) -> None:
        app = QApplication.instance()
        if not app:
            return
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
            QTabWidget::pane {
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
                top: -1px;
            }
            QTabBar::tab {
                padding: 8px 12px;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                border: 1px solid rgba(255,255,255,0.12);
                margin-right: 6px;
                background: rgba(0,0,0,0.15);
            }
            QTabBar::tab:selected {
                background: rgba(0,0,0,0.35);
                border-color: rgba(255,255,255,0.22);
            }
        """)

    def apply_light_theme(self) -> None:
        app = QApplication.instance()
        if not app:
            return
        app.setStyle("Fusion")
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet("")

    def on_dark_mode_toggled(self, enabled: bool) -> None:
        self._dark_enabled = enabled
        if enabled:
            self.apply_dark_theme()
        else:
            self.apply_light_theme()

    # ---------------------------
    # UI
    # ---------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        # ---- Header ----
        header = QLabel("Created by ProtoBuffers")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("font-size: 18px; font-weight: 600; letter-spacing: 1px;")
        root.addWidget(header)


        # ---- Project ----
        proj = QGroupBox("Project")
        pl = QVBoxLayout(proj)

        r1 = QHBoxLayout()
        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("Base memory*.dat (e.g., memory1.dat)")
        b1 = QPushButton("Browse")
        b1.clicked.connect(self.pick_base)
        r1.addWidget(QLabel("Base:"))
        r1.addWidget(self.base_edit, 1)
        r1.addWidget(b1)
        pl.addLayout(r1)

        r2 = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("Working folder (manifest.json / blocks/)")
        b2 = QPushButton("Browse")
        b2.clicked.connect(self.pick_dir)
        r2.addWidget(QLabel("Folder:"))
        r2.addWidget(self.dir_edit, 1)
        r2.addWidget(b2)
        pl.addLayout(r2)

        root.addWidget(proj)

        # ---- Preset Values (Tabbed) ----
        vals = QGroupBox("Editable Values")
        vl = QVBoxLayout(vals)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_currency_tab(), "Coins / Rating / XP")
        self.tabs.addTab(self._build_stats_tab(), "Time / Races / Cups / Points")
        vl.addWidget(self.tabs)

        root.addWidget(vals)

        # ---- Actions ----
        actions = QGroupBox("Actions")
        al = QVBoxLayout(actions)

        top = QHBoxLayout()
        self.chk_dark_mode = QCheckBox("Dark mode")
        self.chk_dark_mode.setChecked(True)
        self.chk_dark_mode.toggled.connect(self.on_dark_mode_toggled)

        self.chk_apply_all = QCheckBox("Apply ALL (Currency + Unlocks + Stats) when clicking Repack")
        self.chk_apply_all.setChecked(True)

        top.addWidget(self.chk_dark_mode)
        top.addStretch(1)
        top.addWidget(self.chk_apply_all)
        al.addLayout(top)

        r3 = QHBoxLayout()
        self.btn_extract = QPushButton("1) Extract")
        self.btn_extract.clicked.connect(self.on_extract)

        self.btn_currency = QPushButton("2) Apply: Currency")
        self.btn_currency.clicked.connect(self.on_apply_currency)

        self.btn_unlock = QPushButton("2) Apply: Unlock All Cars/Tracks")
        self.btn_unlock.clicked.connect(self.on_apply_unlocks)

        self.btn_stats = QPushButton("2) Apply: Stats/Cups/Points")
        self.btn_stats.clicked.connect(self.on_apply_stats)

        self.btn_repack = QPushButton("3) Repack → memory.dat")
        self.btn_repack.clicked.connect(self.on_repack)

        r3.addWidget(self.btn_extract)
        r3.addWidget(self.btn_currency)
        r3.addWidget(self.btn_unlock)
        r3.addWidget(self.btn_stats)
        r3.addWidget(self.btn_repack)
        al.addLayout(r3)

        root.addWidget(actions)

        # ---- Log (small) ----
        logbox = QGroupBox("Log")
        ll = QVBoxLayout(logbox)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        # Keep log short
        self.log.document().setMaximumBlockCount(120)
        ll.addWidget(self.log)
        root.addWidget(logbox, 1)

    def _build_currency_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.coins_spin = QSpinBox()
        self.coins_spin.setRange(0, 2_000_000_000)
        self.coins_spin.setValue(999_999_999)

        self.rating_edit = QLineEdit("999999999")
        self.player_exp_edit = QLineEdit("9999999")

        form.addRow("Coins (int)", self.coins_spin)
        form.addRow("ratingPoints (string)", self.rating_edit)
        form.addRow("playerExp (string)", self.player_exp_edit)

        return w

    def _build_stats_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        # timeInGame: editable seconds, show human-readable duration
        self.time_seconds = QSpinBox()
        self.time_seconds.setRange(0, 2_000_000_000)
        self.time_seconds.setValue(1_000_000_140)
        self.time_seconds.valueChanged.connect(self._refresh_time_labels)

        self.time_human = QLabel("")
        self.time_human.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # Races / cups (string)
        self.races_played_edit = QLineEdit("999999999")
        self.drift_races_played_edit = QLineEdit("999999999")
        self.time_attack_races_played_edit = QLineEdit("999999999")
        self.mp_races_played_edit = QLineEdit("999999999")

        self.cups1_edit = QLineEdit("999999999")
        self.cups2_edit = QLineEdit("999999999")
        self.cups3_edit = QLineEdit("999999999")

        # Points
        self.max_points_per_drift_edit = QLineEdit("1E+09")
        self.max_points_per_race_edit = QLineEdit("1E+09")
        self.avg_points_per_race_edit = QLineEdit("27986.85")

        form.addRow("timeInGame (seconds)", self.time_seconds)
        form.addRow("timeInGame (readable)", self.time_human)

        form.addRow("racesPlayed", self.races_played_edit)
        form.addRow("driftRacesPlayed", self.drift_races_played_edit)
        form.addRow("timeAttackRacesPlayed", self.time_attack_races_played_edit)
        form.addRow("MPRacesPlayed", self.mp_races_played_edit)

        form.addRow("cups1", self.cups1_edit)
        form.addRow("cups2", self.cups2_edit)
        form.addRow("cups3", self.cups3_edit)

        form.addRow("maxPointsPerDrift", self.max_points_per_drift_edit)
        form.addRow("maxPointsPerRace", self.max_points_per_race_edit)
        form.addRow("averagePointsPerRace", self.avg_points_per_race_edit)

        self._refresh_time_labels()
        return w

    def _refresh_time_labels(self) -> None:
        secs = int(self.time_seconds.value())
        self.time_human.setText(_seconds_to_duration_str(secs))

    # ---------------------------
    # Logging
    # ---------------------------

    def _msg(self, s: str):
        self.log.appendPlainText(s)

    # ---------------------------
    # File pickers / checks
    # ---------------------------

    def pick_base(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select base memory*.dat", "", "DAT files (*.dat);;All files (*.*)")
        if not p:
            return
        self.base_dat = Path(p)
        self.base_edit.setText(str(self.base_dat))
        self._msg(f"Base set: {self.base_dat}")

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select working folder")
        if not d:
            return
        self.work_dir = Path(d)
        self.dir_edit.setText(str(self.work_dir))
        self._msg(f"Folder set: {self.work_dir}")

    def _ensure_ready(self) -> bool:
        if not self.base_dat or not self.base_dat.exists():
            QMessageBox.warning(self, "Missing base", "Pick a valid base memory*.dat")
            return False
        if not self.work_dir:
            QMessageBox.warning(self, "Missing folder", "Pick a working folder")
            return False
        self.work_dir.mkdir(parents=True, exist_ok=True)
        return True

    def _ensure_extracted(self) -> bool:
        if not self.work_dir:
            return False
        if not (self.work_dir / "manifest.json").exists() or not (self.work_dir / "blocks").exists():
            QMessageBox.warning(self, "Not extracted", "Run Extract first (need manifest.json and blocks/).")
            return False
        return True

    # ---------------------------
    # Update dict builders
    # ---------------------------

    def _currency_updates(self) -> dict:
        return {
            "coins": int(self.coins_spin.value()),
            "ratingPoints": self.rating_edit.text().strip(),
            "playerExp": self.player_exp_edit.text().strip(),
        }

    def _unlock_updates(self) -> dict:
        return {
            "availableCars": AVAILABLE_CARS,
            "availableTracks": AVAILABLE_TRACKS,
        }

    def _stats_updates(self) -> dict:
        # NOTE: purchasesCount intentionally omitted per your request
        return {
            "timeInGame": str(int(self.time_seconds.value())),
            "racesPlayed": self.races_played_edit.text().strip(),
            "driftRacesPlayed": self.drift_races_played_edit.text().strip(),
            "timeAttackRacesPlayed": self.time_attack_races_played_edit.text().strip(),
            "MPRacesPlayed": self.mp_races_played_edit.text().strip(),
            "cups1": self.cups1_edit.text().strip(),
            "cups2": self.cups2_edit.text().strip(),
            "cups3": self.cups3_edit.text().strip(),
            "maxPointsPerDrift": self.max_points_per_drift_edit.text().strip(),
            "maxPointsPerRace": self.max_points_per_race_edit.text().strip(),
            "averagePointsPerRace": self.avg_points_per_race_edit.text().strip(),
        }

    def _apply_updates(self, name: str, updates: dict):
        try:
            self._msg(f"Applying: {name}")
            n, warnings = apply_updates_to_blocks(self.work_dir, updates)
            self._msg(f"Assignments: {n}")
            # Keep warnings brief
            for w in warnings[:5]:
                self._msg(f"WARNING: {w}")
            if len(warnings) > 5:
                self._msg(f"WARNING: (+{len(warnings) - 5} more)")
        except Exception as e:
            QMessageBox.critical(self, "Apply failed", str(e))
            self._msg(f"ERROR: {e}")

    # ---------------------------
    # Actions
    # ---------------------------

    def on_extract(self):
        if not self._ensure_ready():
            return
        try:
            self._msg("Extracting...")
            manifest = extract(self.base_dat, self.work_dir)
            self._msg(f"Extract complete: {manifest}")
        except Exception as e:
            QMessageBox.critical(self, "Extract failed", str(e))
            self._msg(f"ERROR: {e}")

    def on_apply_currency(self):
        if not self._ensure_extracted():
            return
        self._apply_updates("Currency", self._currency_updates())

    def on_apply_unlocks(self):
        if not self._ensure_extracted():
            return
        if not AVAILABLE_CARS or not AVAILABLE_TRACKS:
            QMessageBox.warning(self, "Unlock lists missing",
                                "AVAILABLE_CARS/TRACKS not found in core.presets. "
                                "Add them there or paste lists into the project.")
            return
        self._apply_updates("Unlock All Cars/Tracks", self._unlock_updates())

    def on_apply_stats(self):
        if not self._ensure_extracted():
            return
        self._apply_updates("Stats/Cups/Points", self._stats_updates())

    def on_repack(self):
        if not self._ensure_ready():
            return
        if not self._ensure_extracted():
            return

        out_path_str, _ = QFileDialog.getSaveFileName(self, "Save rebuilt memory.dat", "", "DAT files (*.dat);;All files (*.*)")
        if not out_path_str:
            return
        out_path = Path(out_path_str)

        try:
            if self.chk_apply_all.isChecked():
                self._msg("Applying ALL presets before repack...")
                self._apply_updates("Currency", self._currency_updates())

                if AVAILABLE_CARS and AVAILABLE_TRACKS:
                    self._apply_updates("Unlock All Cars/Tracks", self._unlock_updates())
                else:
                    self._msg("WARNING: Unlock lists missing; skipping unlock preset.")

                self._apply_updates("Stats/Cups/Points", self._stats_updates())

            self._msg("Repacking (offset-safe)...")
            ok, fail, warnings, report = repack(self.base_dat, self.work_dir, out_path)

            self._msg(f"Repack done. OK={ok}, FAIL={fail}")
            self._msg(f"Report: {report}")

            if fail:
                QMessageBox.warning(
                    self,
                    "Repack completed with failures",
                    "Some blocks became too large for their fixed slots.\n"
                    "Use a base save with larger slots or reduce edits.\n"
                    "Open the report file for details."
                )
            else:
                QMessageBox.information(self, "Success", f"Saved: {out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Repack failed", str(e))
            self._msg(f"ERROR: {e}")
