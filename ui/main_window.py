from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Optional, Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QColor, QAction
from PyQt6.QtWidgets import (
    QApplication,
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit, QPushButton,
    QFileDialog, QPlainTextEdit, QMessageBox, QCheckBox, QFormLayout, QSpinBox,
    QTabWidget, QSplitter, QComboBox, QStackedWidget, QTreeWidget, QTreeWidgetItem, QMenu
)

from core.extract import extract
from core.json_ops import read_text_any, try_load_json, find_first_keys
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
        self.tabs.addTab(self._build_browser_tab(), "Data Browser")
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

        self.btn_load_values = QPushButton("Load values from extracted save")
        self.btn_load_values.clicked.connect(self.on_load_values)

        self.btn_currency = QPushButton("2) Apply: Currency")
        self.btn_currency.clicked.connect(self.on_apply_currency)

        self.btn_unlock = QPushButton("2) Apply: Unlock All Cars/Tracks")
        self.btn_unlock.clicked.connect(self.on_apply_unlocks)

        self.btn_stats = QPushButton("2) Apply: Stats/Cups/Points")
        self.btn_stats.clicked.connect(self.on_apply_stats)

        self.btn_repack = QPushButton("3) Repack → memory.dat")
        self.btn_repack.clicked.connect(self.on_repack)

        r3.addWidget(self.btn_extract)
        r3.addWidget(self.btn_load_values)
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

    
    def on_load_values(self) -> None:
        if not self._ensure_extracted():
            return
        self._populate_fields_from_save(show_summary=True)

    def _populate_fields_from_save(self, show_summary: bool = False) -> None:
        """Scan extracted JSON blocks and populate UI fields with current save values."""
        if not self._ensure_extracted():
            return

        keys = [
            # Currency
            "coins", "ratingPoints", "playerExp",
            # Stats
            "timeInGame", "racesPlayed", "driftRacesPlayed", "timeAttackRacesPlayed", "MPRacesPlayed",
            "maxPointsPerDrift", "maxPointsPerRace", "averagePointsPerRace",
            "cups1", "cups2", "cups3",
        ]

        found: Dict[str, Any] = {}
        blocks_dir = self.work_dir / "blocks"
        for p in sorted(blocks_dir.glob("*.json")):
            try:
                txt = read_text_any(p)
                obj = try_load_json(txt)
                if obj is None:
                    continue
                got = find_first_keys(obj, keys)
                for k, v in got.items():
                    if k not in found:
                        found[k] = v
                if len(found) == len(keys):
                    break
            except Exception:
                continue

        # Apply to widgets with reasonable type coercion
        def _set_line(le: QLineEdit, v: Any) -> None:
            if v is None:
                return
            le.setText(str(v))

        def _set_spin(sb: QSpinBox, v: Any) -> None:
            try:
                if isinstance(v, str):
                    v = int(float(v)) if any(c in v for c in ".eE") else int(v)
                sb.setValue(int(v))
            except Exception:
                pass

        if "coins" in found:
            _set_spin(self.coins_spin, found["coins"])
        if "ratingPoints" in found:
            _set_line(self.rating_edit, found["ratingPoints"])
        if "playerExp" in found:
            _set_line(self.player_exp_edit, found["playerExp"])

        if "timeInGame" in found:
            _set_spin(self.time_seconds, found["timeInGame"])
            self._refresh_time_labels()

        if "racesPlayed" in found:
            _set_line(self.races_played_edit, found["racesPlayed"])
        if "driftRacesPlayed" in found:
            _set_line(self.drift_races_played_edit, found["driftRacesPlayed"])
        if "timeAttackRacesPlayed" in found:
            _set_line(self.time_attack_races_played_edit, found["timeAttackRacesPlayed"])
        if "MPRacesPlayed" in found:
            _set_line(self.mp_races_played_edit, found["MPRacesPlayed"])

        if "maxPointsPerDrift" in found:
            _set_line(self.max_points_per_drift_edit, found["maxPointsPerDrift"])
        if "maxPointsPerRace" in found:
            _set_line(self.max_points_per_race_edit, found["maxPointsPerRace"])
        if "averagePointsPerRace" in found:
            _set_line(self.avg_points_per_race_edit, found["averagePointsPerRace"])

        if "cups1" in found:
            _set_line(self.cups1_edit, found["cups1"])
        if "cups2" in found:
            _set_line(self.cups2_edit, found["cups2"])
        if "cups3" in found:
            _set_line(self.cups3_edit, found["cups3"])

        if show_summary:
            missing = [k for k in keys if k not in found]
            if missing:
                QMessageBox.information(
                    self,
                    "Loaded values (partial)",
                    "Loaded some values from the extracted save.\n\n"
                    f"Missing keys (not found in first matching JSON blocks):\n- " + "\n- ".join(missing)
                )
            else:
                QMessageBox.information(self, "Loaded values", "Loaded current values from the extracted save.")

    # ---------------------------
    # Data browser tab
    # ---------------------------

    def _build_browser_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)

        top = QHBoxLayout()

        self.browser_refresh_btn = QPushButton("Refresh")
        self.browser_refresh_btn.clicked.connect(self._browser_refresh)

        self.browser_load_btn = QPushButton("Load values into forms")
        self.browser_load_btn.clicked.connect(self.on_load_values)

        self.browser_show_all = QCheckBox("Show all blocks (may be large)")
        self.browser_show_all.setChecked(False)
        self.browser_show_all.toggled.connect(self._browser_refresh)

        self.browser_rank = QCheckBox("Rank blocks by player keys")
        self.browser_rank.setChecked(True)
        self.browser_rank.toggled.connect(self._browser_refresh)

        self.browser_view_mode = QComboBox()
        self.browser_view_mode.addItems([
            "Tree (JSON)",
            "Pretty JSON",
            "Raw text",
            "Hex (binary preview)",
        ])
        self.browser_view_mode.currentIndexChanged.connect(self._browser_open_selected)

        top.addWidget(self.browser_refresh_btn)
        top.addWidget(self.browser_load_btn)
        top.addStretch(1)
        top.addWidget(self.browser_rank)
        top.addWidget(self.browser_show_all)
        top.addWidget(QLabel("View:"))
        top.addWidget(self.browser_view_mode)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.browser_list = QTreeWidget()
        self.browser_list.setHeaderLabels(["Block", "Score"])
        self.browser_list.setColumnWidth(0, 420)
        self.browser_list.itemSelectionChanged.connect(self._browser_open_selected)

        # Right: a tree viewer + text viewer (stacked)
        self.browser_json_tree = QTreeWidget()
        self.browser_json_tree.setHeaderLabels(["Key / Index", "Value preview"])
        self.browser_json_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.browser_json_tree.customContextMenuRequested.connect(self._on_json_tree_menu)

        self.browser_text = QPlainTextEdit()
        self.browser_text.setReadOnly(True)

        self.browser_right = QStackedWidget()
        self.browser_right.addWidget(self.browser_json_tree)  # index 0
        self.browser_right.addWidget(self.browser_text)       # index 1

        splitter.addWidget(self.browser_list)
        splitter.addWidget(self.browser_right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        root.addWidget(splitter, 1)

        self.browser_text.setPlainText("Run Extract first, then click Refresh to browse extracted blocks.")
        self.browser_right.setCurrentIndex(1)
        return w

    def _browser_player_keys(self) -> List[str]:
        # Keys that typically live in the “player-ish” chunks.
        return [
            "coins", "ratingPoints", "playerExp",
            "timeInGame", "racesPlayed", "driftRacesPlayed", "timeAttackRacesPlayed", "MPRacesPlayed",
            "maxPointsPerDrift", "maxPointsPerRace", "averagePointsPerRace",
            "cups1", "cups2", "cups3",
        ]

    def _browser_refresh(self) -> None:
        if not hasattr(self, "browser_list"):
            return

        self.browser_list.clear()
        self.browser_json_tree.clear()

        if not self._ensure_extracted():
            return

        manifest_path = self.work_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            blocks = manifest.get("blocks", [])
        except Exception as e:
            self.browser_text.setPlainText(f"Failed to read manifest.json: {e}")
            self.browser_right.setCurrentIndex(1)
            return

        limit = None if self.browser_show_all.isChecked() else 20
        shown = blocks if limit is None else blocks[:limit]

        ranked = []
        keys = self._browser_player_keys()
        for b in shown:
            out_name = b.get("out_name", "")
            p = (self.work_dir / out_name) if out_name else None
            score = 0
            found_keys = []
            if self.browser_rank.isChecked() and p and p.exists() and p.suffix.lower() == ".json":
                try:
                    txt = read_text_any(p)
                    obj = try_load_json(txt)
                    if obj is not None:
                        found = self._find_keys_in_obj(obj, keys)
                        found_keys = sorted(found)
                        score = len(found)
                except Exception:
                    pass
            ranked.append((score, found_keys, b))

        if self.browser_rank.isChecked():
            ranked.sort(key=lambda t: (t[0], t[2].get("index", -1)), reverse=True)

        for score, found_keys, b in ranked:
            idx = b.get("index", -1)
            out_name = b.get("out_name", "")
            kind = b.get("kind", "")
            note = b.get("note", "")
            label = f"{idx:03d}  {Path(out_name).name}  [{kind}]"
            if note:
                label += f"  – {note}"
            if found_keys:
                label += f"  {{" + ", ".join(found_keys[:6]) + ("…" if len(found_keys) > 6 else "") + "}}"

            it = QTreeWidgetItem([label, str(score)])
            it.setData(0, Qt.ItemDataRole.UserRole, out_name)
            self.browser_list.addTopLevelItem(it)

        if self.browser_list.topLevelItemCount() == 0:
            self.browser_text.setPlainText("No blocks listed in manifest.json.")
            self.browser_right.setCurrentIndex(1)
        else:
            self.browser_list.setCurrentItem(self.browser_list.topLevelItem(0))

    def _browser_open_selected(self) -> None:
        if not hasattr(self, "browser_list"):
            return
        items = self.browser_list.selectedItems()
        if not items:
            return
        it = items[0]
        out_name = it.data(0, Qt.ItemDataRole.UserRole)
        if not out_name:
            return

        p = self.work_dir / out_name
        if not p.exists():
            self.browser_text.setPlainText(f"Missing file: {p}")
            self.browser_right.setCurrentIndex(1)
            return

        mode = self.browser_view_mode.currentText()

        try:
            if p.suffix.lower() == ".json":
                txt = read_text_any(p)
                obj = try_load_json(txt)

                if mode == "Raw text" or obj is None:
                    self.browser_text.setPlainText(txt)
                    self.browser_right.setCurrentIndex(1)
                    return

                if mode == "Pretty JSON":
                    self.browser_text.setPlainText(json.dumps(obj, indent=2, ensure_ascii=False))
                    self.browser_right.setCurrentIndex(1)
                    return

                # Tree (JSON)
                self.browser_json_tree.clear()
                root_item = QTreeWidgetItem(["$", ""])
                root_item.setData(0, Qt.ItemDataRole.UserRole, "$")
                self.browser_json_tree.addTopLevelItem(root_item)
                self._populate_json_tree(root_item, obj, "$")
                root_item.setExpanded(True)
                self.browser_right.setCurrentIndex(0)
                return

            # Binary / other
            b = p.read_bytes()
            head = b[:4096]
            if mode == "Hex (binary preview)":
                hex_dump = " ".join(f"{x:02X}" for x in head)
                self.browser_text.setPlainText(
                    f"{p.name} (binary)\nSize: {len(b)} bytes\n\nFirst 4096 bytes (hex):\n{hex_dump}"
                )
            else:
                self.browser_text.setPlainText(f"{p.name} (binary)\nSize: {len(b)} bytes\n\nSelect 'Hex (binary preview)' to view bytes.")
            self.browser_right.setCurrentIndex(1)

        except Exception as e:
            self.browser_text.setPlainText(f"Failed to open {p}: {e}")
            self.browser_right.setCurrentIndex(1)

    def _find_keys_in_obj(self, obj: Any, keys: List[str]) -> set:
        keyset = set(keys)
        found = set()
        stack = [obj]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                for k, v in cur.items():
                    if k in keyset:
                        found.add(k)
                    stack.append(v)
            elif isinstance(cur, list):
                stack.extend(cur)
        return found

    def _populate_json_tree(self, parent: QTreeWidgetItem, obj: Any, path: str) -> None:
        # Keep this snappy: limit children per node to prevent UI lockups.
        MAX_CHILDREN = 500

        def preview(v: Any) -> str:
            if isinstance(v, (dict, list)):
                if isinstance(v, dict):
                    return f"{{...}} ({len(v)})"
                return f"[...] ({len(v)})"
            s = str(v)
            if len(s) > 120:
                s = s[:117] + "..."
            return s

        if isinstance(obj, dict):
            for i, (k, v) in enumerate(obj.items()):
                if i >= MAX_CHILDREN:
                    QTreeWidgetItem(parent, ["…", f"truncated at {MAX_CHILDREN} children"]).setData(0, Qt.ItemDataRole.UserRole, path)
                    break
                child_path = f"{path}.{k}" if path != "$" else f"$.{k}"
                item = QTreeWidgetItem([str(k), preview(v)])
                item.setData(0, Qt.ItemDataRole.UserRole, child_path)
                parent.addChild(item)
                if isinstance(v, (dict, list)):
                    self._populate_json_tree(item, v, child_path)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                if i >= MAX_CHILDREN:
                    QTreeWidgetItem(parent, ["…", f"truncated at {MAX_CHILDREN} children"]).setData(0, Qt.ItemDataRole.UserRole, path)
                    break
                child_path = f"{path}[{i}]"
                item = QTreeWidgetItem([f"[{i}]", preview(v)])
                item.setData(0, Qt.ItemDataRole.UserRole, child_path)
                parent.addChild(item)
                if isinstance(v, (dict, list)):
                    self._populate_json_tree(item, v, child_path)

    def _on_json_tree_menu(self, pos) -> None:
        item = self.browser_json_tree.itemAt(pos)
        if item is None:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole) or ""
        menu = QMenu(self.browser_json_tree)

        act_copy_path = QAction("Copy JSON path", self.browser_json_tree)
        act_copy_path.triggered.connect(lambda: QApplication.clipboard().setText(str(path)))
        menu.addAction(act_copy_path)

        # Copy value preview (column 1)
        act_copy_value = QAction("Copy value preview", self.browser_json_tree)
        act_copy_value.triggered.connect(lambda: QApplication.clipboard().setText(item.text(1)))
        menu.addAction(act_copy_value)

        menu.exec(self.browser_json_tree.viewport().mapToGlobal(pos))

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
            # Populate form fields from the extracted save data
            self._populate_fields_from_save(show_summary=False)
            # Refresh browser list if the tab is initialized
            if hasattr(self, "browser_list"):
                self._browser_refresh()
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
