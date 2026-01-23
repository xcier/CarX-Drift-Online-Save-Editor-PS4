from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QGroupBox,
    QTabWidget,
    QFormLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QMessageBox,
)

from core.id_database import IdDatabase
from core.favorites_db import FavoritesDb
from core.json_ops import try_load_json


def _safe_int(s: str) -> int:
    try:
        return int(s)
    except Exception:
        return 10**18


class DatabaseTab(QWidget):
    """Database-focused labeling workflow.

    Split cars and tracks into separate sub-tabs so the user can name IDs quickly.
    This tab reads:
      - current car identifiers (carId + lastCarId) from extracted blocks
      - in-game "quick lists" (availableCars/availableTracks) from extracted blocks
      - user labels from IdDatabase (data/id_database.json)
    """

    def __init__(self, parent: Optional[QWidget] = None, *, id_db: IdDatabase, favorites_db: FavoritesDb):
        super().__init__(parent)
        self._id_db = id_db
        self._fav_db = favorites_db

        self._work_dir: Optional[Path] = None

        # current ids
        self._active_car_id: Optional[str] = None
        self._last_car_id: Optional[str] = None
        self._cur_car_id: Optional[str] = None

        # in-game quick lists
        self._ingame_cars: List[str] = []
        self._ingame_tracks: List[str] = []

        # current selection (for edit boxes)
        self._sel_car_id: Optional[str] = None  # selected row in Cars DB list
        self._sel_track_id: Optional[str] = None

        self._build_ui()
        self._reload_all()

    # -------------------- Public API --------------------

    def refresh_from_workdir(self, work_dir: Path) -> None:
        self._work_dir = work_dir
        self._load_from_blocks()
        self._reload_all()

    # -------------------- UI --------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.subtabs = QTabWidget()
        self.subtabs.addTab(self._build_cars_page(), "Cars")
        self.subtabs.addTab(self._build_tracks_page(), "Tracks")
        root.addWidget(self.subtabs)

    # ---------- Cars page ----------

    def _build_cars_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # Current car (for quick labeling)
        gb_cur = QGroupBox("Current car (for labeling)")
        form = QFormLayout(gb_cur)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.lbl_active_car = QLabel("—")
        self.lbl_active_car.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.lbl_last_car = QLabel("—")
        self.lbl_last_car.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.cmb_current_source = QComboBox()
        self.cmb_current_source.addItems(["Last selected (lastCarId)", "Active (carId)"])
        self.cmb_current_source.currentIndexChanged.connect(self._apply_current_source)

        self.ed_cur_car_name = QLineEdit()
        self.ed_cur_car_name.setPlaceholderText("Name to store in id_database.json (cars)")
        self.ed_cur_car_name.textChanged.connect(self._update_car_buttons_state)

        form.addRow("Active carId:", self.lbl_active_car)
        form.addRow("Last selected carId:", self.lbl_last_car)
        form.addRow("Use for naming:", self.cmb_current_source)
        form.addRow("DB name:", self.ed_cur_car_name)

        btn_row = QHBoxLayout()
        self.btn_save_cur_car = QPushButton("Save name for current ID")
        self.btn_save_cur_car.clicked.connect(self._save_current_car_name)
        btn_row.addWidget(self.btn_save_cur_car)

        self.btn_copy_cur_car = QPushButton("Copy current ID")
        self.btn_copy_cur_car.clicked.connect(self._copy_current_car_id)
        btn_row.addWidget(self.btn_copy_cur_car)

        self.btn_fav_cur_car = QPushButton("Add current ID to Favorites")
        self.btn_fav_cur_car.clicked.connect(self._favorite_current_car)
        btn_row.addWidget(self.btn_fav_cur_car)

        btn_row.addStretch(1)
        form.addRow("", btn_row)

        v.addWidget(gb_cur)

        # Cars database list
        gb_db = QGroupBox("Cars database (id_database.json)")
        vb2 = QVBoxLayout(gb_db)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.ed_car_search = QLineEdit()
        self.ed_car_search.setPlaceholderText("Filter by ID or name…")
        self.ed_car_search.textChanged.connect(self._reload_car_db_table)
        search_row.addWidget(self.ed_car_search, 1)
        vb2.addLayout(search_row)

        self.tbl_car_db = QTableWidget(0, 2)
        self.tbl_car_db.setHorizontalHeaderLabels(["ID", "Name"])
        self.tbl_car_db.verticalHeader().setVisible(False)
        self.tbl_car_db.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_car_db.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_car_db.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_car_db.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_car_db.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tbl_car_db.itemSelectionChanged.connect(self._on_car_db_selected)
        vb2.addWidget(self.tbl_car_db)

        edit_row = QHBoxLayout()
        self.lbl_sel_car = QLabel("Selected ID: —")
        self.lbl_sel_car.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        edit_row.addWidget(self.lbl_sel_car)

        self.ed_sel_car_name = QLineEdit()
        self.ed_sel_car_name.setPlaceholderText("Name for selected car ID…")
        self.ed_sel_car_name.textChanged.connect(self._update_car_buttons_state)
        edit_row.addWidget(self.ed_sel_car_name, 1)

        self.btn_save_sel_car = QPushButton("Save")
        self.btn_save_sel_car.clicked.connect(self._save_selected_car_name)
        edit_row.addWidget(self.btn_save_sel_car)

        self.btn_copy_sel_car = QPushButton("Copy ID")
        self.btn_copy_sel_car.clicked.connect(self._copy_selected_car_id)
        edit_row.addWidget(self.btn_copy_sel_car)

        self.btn_fav_sel_car = QPushButton("Add to Favorites")
        self.btn_fav_sel_car.clicked.connect(self._favorite_selected_car)
        edit_row.addWidget(self.btn_fav_sel_car)

        vb2.addLayout(edit_row)

        v.addWidget(gb_db)
        v.addStretch(1)

        # Init disabled state
        self._update_car_buttons_state()

        return page

    # ---------- Tracks page ----------

    def _build_tracks_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        gb_ingame = QGroupBox("In-game track quick list (availableTracks)")
        vb = QVBoxLayout(gb_ingame)

        self.tbl_ingame_tracks = QTableWidget(0, 3)
        self.tbl_ingame_tracks.setHorizontalHeaderLabels(["ID", "Name", "Source"])
        self.tbl_ingame_tracks.verticalHeader().setVisible(False)
        self.tbl_ingame_tracks.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_ingame_tracks.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_ingame_tracks.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_ingame_tracks.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_ingame_tracks.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tbl_ingame_tracks.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_ingame_tracks.itemSelectionChanged.connect(self._on_ingame_track_selected)

        vb.addWidget(self.tbl_ingame_tracks)

        btn_row = QHBoxLayout()
        self.btn_name_from_ingame_track = QPushButton("Use selected ID for naming")
        self.btn_name_from_ingame_track.clicked.connect(self._use_selected_ingame_track)
        btn_row.addWidget(self.btn_name_from_ingame_track)

        self.btn_add_ingame_track_to_favs = QPushButton("Add selected to Favorites")
        self.btn_add_ingame_track_to_favs.clicked.connect(self._favorite_selected_ingame_track)
        btn_row.addWidget(self.btn_add_ingame_track_to_favs)

        self.btn_copy_ingame_track = QPushButton("Copy selected ID")
        self.btn_copy_ingame_track.clicked.connect(self._copy_selected_ingame_track)
        btn_row.addWidget(self.btn_copy_ingame_track)

        btn_row.addStretch(1)
        vb.addLayout(btn_row)

        v.addWidget(gb_ingame)

        gb_db = QGroupBox("Tracks database (id_database.json)")
        vb2 = QVBoxLayout(gb_db)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.ed_track_search = QLineEdit()
        self.ed_track_search.setPlaceholderText("Filter by ID or name…")
        self.ed_track_search.textChanged.connect(self._reload_track_db_table)
        search_row.addWidget(self.ed_track_search, 1)
        vb2.addLayout(search_row)

        self.tbl_track_db = QTableWidget(0, 2)
        self.tbl_track_db.setHorizontalHeaderLabels(["ID", "Name"])
        self.tbl_track_db.verticalHeader().setVisible(False)
        self.tbl_track_db.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_track_db.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_track_db.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_track_db.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_track_db.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tbl_track_db.itemSelectionChanged.connect(self._on_track_db_selected)
        vb2.addWidget(self.tbl_track_db)

        edit_row = QHBoxLayout()
        self.lbl_sel_track = QLabel("Selected ID: —")
        self.lbl_sel_track.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        edit_row.addWidget(self.lbl_sel_track)

        self.ed_sel_track_name = QLineEdit()
        self.ed_sel_track_name.setPlaceholderText("Name for selected track ID…")
        self.ed_sel_track_name.textChanged.connect(self._update_track_buttons_state)
        edit_row.addWidget(self.ed_sel_track_name, 1)

        self.btn_save_sel_track = QPushButton("Save")
        self.btn_save_sel_track.clicked.connect(self._save_selected_track_name)
        edit_row.addWidget(self.btn_save_sel_track)

        self.btn_copy_sel_track = QPushButton("Copy ID")
        self.btn_copy_sel_track.clicked.connect(self._copy_selected_track_id)
        edit_row.addWidget(self.btn_copy_sel_track)

        self.btn_fav_sel_track = QPushButton("Add to Favorites")
        self.btn_fav_sel_track.clicked.connect(self._favorite_selected_track)
        edit_row.addWidget(self.btn_fav_sel_track)

        vb2.addLayout(edit_row)

        v.addWidget(gb_db)
        v.addStretch(1)

        self._update_track_buttons_state()
        self._update_ingame_track_buttons_state()

        return page

    # -------------------- Load from blocks --------------------

    def _resolve_blocks_dir(self) -> Optional[Path]:
        if not self._work_dir:
            return None
        wd = self._work_dir
        if wd.name.lower() == "blocks" and wd.exists():
            return wd
        cand = wd / "blocks"
        if cand.exists():
            return cand
        cand2 = wd / "extracted" / "blocks"
        if cand2.exists():
            return cand2
        return None

    def _load_from_blocks(self) -> None:
        """Load current ids + in-game lists from extracted JSON blocks."""
        self._active_car_id = None
        self._last_car_id = None
        self._ingame_cars = []
        self._ingame_tracks = []

        blocks_dir = self._resolve_blocks_dir()
        if not blocks_dir:
            self._update_current_car_labels()
            return

        # Fast heuristic: only parse blocks that contain our keys
        for p in sorted(blocks_dir.glob("*.json")):
            obj = try_load_json(p)
            if not isinstance(obj, dict):
                continue

            if self._active_car_id is None and "carId" in obj:
                v = obj.get("carId")
                if v is not None:
                    self._active_car_id = str(v)

            if self._last_car_id is None and "lastCarId" in obj:
                v = obj.get("lastCarId")
                if v is not None:
                    self._last_car_id = str(v)
            # NOTE: We intentionally do NOT import unlocked car lists into the Database tab.
            # Cars are labeled from Garage Unlocks / Advanced Unlocks; the Database tab stays focused.

            if not self._ingame_tracks and "availableTracks" in obj and isinstance(obj.get("availableTracks"), list):
                self._ingame_tracks = [str(x) for x in (obj.get("availableTracks") or []) if x is not None]

            if self._active_car_id and self._last_car_id and self._ingame_tracks:
                break

        self._update_current_car_labels()

    # -------------------- Reload helpers --------------------

    def _reload_all(self) -> None:
        self._apply_current_source()
        self._reload_ingame_track_table()
        self._reload_car_db_table()
        self._reload_track_db_table()

    def _update_current_car_labels(self) -> None:
        if hasattr(self, "lbl_active_car"):
            self.lbl_active_car.setText(self._fmt_car(self._active_car_id))
        if hasattr(self, "lbl_last_car"):
            self.lbl_last_car.setText(self._fmt_car(self._last_car_id))

    def _fmt_car(self, car_id: Optional[str]) -> str:
        if not car_id:
            return "—"
        # Prefer blank if not labeled? show helpful fallback
        name = self._id_db.cars.get(str(car_id), "")
        if name:
            return f"{car_id} — {name}"
        return f"{car_id} — {self._id_db.label_car(car_id)}"

    # -------------------- Current car source --------------------

    def _apply_current_source(self) -> None:
        # 0 = lastCarId, 1 = carId
        if getattr(self, "cmb_current_source", None) is None:
            return
        use_last = self.cmb_current_source.currentIndex() == 0
        self._cur_car_id = (self._last_car_id if use_last else self._active_car_id) or None

        # Set edit box to existing label if present
        if hasattr(self, "ed_cur_car_name"):
            if self._cur_car_id:
                self.ed_cur_car_name.setText(self._id_db.cars.get(str(self._cur_car_id), ""))
            else:
                self.ed_cur_car_name.setText("")
        self._update_car_buttons_state()

    # -------------------- Cars DB table --------------------

    def _reload_car_db_table(self) -> None:
        if not hasattr(self, "tbl_car_db"):
            return

        # Build union of known labeled IDs + in-game list + current ids
        ids = set(str(k) for k in (self._id_db.cars or {}).keys())
        if self._active_car_id:
            ids.add(str(self._active_car_id))
        if self._last_car_id:
            ids.add(str(self._last_car_id))

        filt = (self.ed_car_search.text() or "").strip().lower() if hasattr(self, "ed_car_search") else ""
        ordered = sorted(ids, key=_safe_int)

        self.tbl_car_db.setSortingEnabled(False)
        self.tbl_car_db.setRowCount(0)
        for cid in ordered:
            name = self._id_db.cars.get(str(cid), "")
            if filt and (filt not in str(cid).lower() and filt not in (name or "").lower()):
                continue
            r = self.tbl_car_db.rowCount()
            self.tbl_car_db.insertRow(r)
            self.tbl_car_db.setItem(r, 0, QTableWidgetItem(str(cid)))
            self.tbl_car_db.setItem(r, 1, QTableWidgetItem(name))
        self.tbl_car_db.setSortingEnabled(True)

        self._update_car_buttons_state()

    def _on_car_db_selected(self) -> None:
        if not hasattr(self, "tbl_car_db"):
            return
        r = self.tbl_car_db.currentRow()
        if r < 0:
            self._sel_car_id = None
            self.lbl_sel_car.setText("Selected ID: —")
            self.ed_sel_car_name.setText("")
            self._update_car_buttons_state()
            return
        cid = self.tbl_car_db.item(r, 0).text()
        self._sel_car_id = cid
        self.lbl_sel_car.setText(f"Selected ID: {cid}")
        self.ed_sel_car_name.setText(self._id_db.cars.get(str(cid), ""))
        self._update_car_buttons_state()

    def _save_selected_car_name(self) -> None:
        if not self._sel_car_id:
            return
        name = (self.ed_sel_car_name.text() or "").strip()
        if not name:
            QMessageBox.information(self, "Cars", "Please enter a name before saving.")
            return
        self._id_db.set_car_label(self._sel_car_id, name)
        self._reload_car_db_table()
        self._notify_labels_changed()

    def _copy_selected_car_id(self) -> None:
        if not self._sel_car_id:
            return
        QGuiApplication.clipboard().setText(str(self._sel_car_id))

    def _favorite_selected_car(self) -> None:
        if not self._sel_car_id:
            return
        self._fav_db.add("cars", self._sel_car_id, name=self._id_db.cars.get(str(self._sel_car_id), ""))
        QMessageBox.information(self, "Favorites", f"Added car {self._sel_car_id} to Favorites.")

    def _update_car_buttons_state(self) -> None:
        # current car buttons
        cur_id = self._cur_car_id if hasattr(self, "cmb_current_source") else None
        cur_name = (self.ed_cur_car_name.text() or "").strip() if hasattr(self, "ed_cur_car_name") else ""
        if hasattr(self, "btn_save_cur_car"):
            self.btn_save_cur_car.setEnabled(bool(cur_id) and bool(cur_name))
        if hasattr(self, "btn_copy_cur_car"):
            self.btn_copy_cur_car.setEnabled(bool(cur_id))
        if hasattr(self, "btn_fav_cur_car"):
            self.btn_fav_cur_car.setEnabled(bool(cur_id))

        # selected car db buttons
        sel_id = bool(self._sel_car_id)
        sel_name = (self.ed_sel_car_name.text() or "").strip() if hasattr(self, "ed_sel_car_name") else ""
        if hasattr(self, "btn_save_sel_car"):
            self.btn_save_sel_car.setEnabled(sel_id and bool(sel_name))
        if hasattr(self, "btn_copy_sel_car"):
            self.btn_copy_sel_car.setEnabled(sel_id)
        if hasattr(self, "btn_fav_sel_car"):
            self.btn_fav_sel_car.setEnabled(sel_id)

    # Current car save/copy/fav

    def _current_car_id(self) -> Optional[str]:
        return self._cur_car_id

    def _save_current_car_name(self) -> None:
        cid = self._current_car_id()
        if not cid:
            return
        name = (self.ed_cur_car_name.text() or "").strip()
        if not name:
            QMessageBox.information(self, "Current car", "Please enter a name before saving.")
            return
        self._id_db.set_car_label(cid, name)
        self._update_current_car_labels()
        self._reload_car_db_table()
        self._notify_labels_changed()

    def _copy_current_car_id(self) -> None:
        cid = self._current_car_id()
        if not cid:
            return
        QGuiApplication.clipboard().setText(str(cid))

    def _favorite_current_car(self) -> None:
        cid = self._current_car_id()
        if not cid:
            return
        self._fav_db.add("cars", cid, name=self._id_db.cars.get(str(cid), ""))
        QMessageBox.information(self, "Favorites", f"Added car {cid} to Favorites.")

    # -------------------- In-game tracks table --------------------

    def _reload_ingame_track_table(self) -> None:
        if not hasattr(self, "tbl_ingame_tracks"):
            return
        rows: List[Tuple[str, str]] = []
        for tid in self._ingame_tracks:
            rows.append((tid, "availableTracks"))

        self.tbl_ingame_tracks.setSortingEnabled(False)
        self.tbl_ingame_tracks.setRowCount(0)
        for tid, src in rows:
            r = self.tbl_ingame_tracks.rowCount()
            self.tbl_ingame_tracks.insertRow(r)
            name = self._id_db.tracks.get(str(tid), "")
            if not name:
                name = self._id_db.label_track(tid)
            self.tbl_ingame_tracks.setItem(r, 0, QTableWidgetItem(str(tid)))
            self.tbl_ingame_tracks.setItem(r, 1, QTableWidgetItem(name))
            self.tbl_ingame_tracks.setItem(r, 2, QTableWidgetItem(src))
        self.tbl_ingame_tracks.setSortingEnabled(True)

        self._update_ingame_track_buttons_state()

    def _on_ingame_track_selected(self) -> None:
        self._update_ingame_track_buttons_state()

    def _selected_ingame_track_id(self) -> Optional[str]:
        if not hasattr(self, "tbl_ingame_tracks"):
            return None
        r = self.tbl_ingame_tracks.currentRow()
        if r < 0:
            return None
        it = self.tbl_ingame_tracks.item(r, 0)
        return (it.text() if it else None)

    def _use_selected_ingame_track(self) -> None:
        tid = self._selected_ingame_track_id()
        if not tid:
            return
        self._sel_track_id = tid
        self.lbl_sel_track.setText(f"Selected ID: {tid}")
        self.ed_sel_track_name.setText(self._id_db.tracks.get(str(tid), ""))
        self._update_track_buttons_state()

    def _favorite_selected_ingame_track(self) -> None:
        tid = self._selected_ingame_track_id()
        if not tid:
            return
        self._fav_db.add("tracks", tid, name=self._id_db.tracks.get(str(tid), ""))
        QMessageBox.information(self, "Favorites", f"Added track {tid} to Favorites.")

    def _copy_selected_ingame_track(self) -> None:
        tid = self._selected_ingame_track_id()
        if not tid:
            return
        QGuiApplication.clipboard().setText(str(tid))

    def _update_ingame_track_buttons_state(self) -> None:
        has = bool(self._selected_ingame_track_id())
        for attr in ("btn_name_from_ingame_track", "btn_add_ingame_track_to_favs", "btn_copy_ingame_track"):
            if hasattr(self, attr):
                getattr(self, attr).setEnabled(has)

    # -------------------- Tracks DB table --------------------

    def _reload_track_db_table(self) -> None:
        if not hasattr(self, "tbl_track_db"):
            return

        ids = set(str(k) for k in (self._id_db.tracks or {}).keys())
        ids.update(str(x) for x in self._ingame_tracks)

        filt = (self.ed_track_search.text() or "").strip().lower() if hasattr(self, "ed_track_search") else ""
        ordered = sorted(ids, key=_safe_int)

        self.tbl_track_db.setSortingEnabled(False)
        self.tbl_track_db.setRowCount(0)
        for tid in ordered:
            name = self._id_db.tracks.get(str(tid), "")
            if filt and (filt not in str(tid).lower() and filt not in (name or "").lower()):
                continue
            r = self.tbl_track_db.rowCount()
            self.tbl_track_db.insertRow(r)
            self.tbl_track_db.setItem(r, 0, QTableWidgetItem(str(tid)))
            self.tbl_track_db.setItem(r, 1, QTableWidgetItem(name))
        self.tbl_track_db.setSortingEnabled(True)

        self._update_track_buttons_state()

    def _on_track_db_selected(self) -> None:
        if not hasattr(self, "tbl_track_db"):
            return
        r = self.tbl_track_db.currentRow()
        if r < 0:
            self._sel_track_id = None
            self.lbl_sel_track.setText("Selected ID: —")
            self.ed_sel_track_name.setText("")
            self._update_track_buttons_state()
            return
        tid = self.tbl_track_db.item(r, 0).text()
        self._sel_track_id = tid
        self.lbl_sel_track.setText(f"Selected ID: {tid}")
        self.ed_sel_track_name.setText(self._id_db.tracks.get(str(tid), ""))
        self._update_track_buttons_state()

    def _save_selected_track_name(self) -> None:
        if not self._sel_track_id:
            return
        name = (self.ed_sel_track_name.text() or "").strip()
        if not name:
            QMessageBox.information(self, "Tracks", "Please enter a name before saving.")
            return
        self._id_db.set_track_label(self._sel_track_id, name)
        self._reload_ingame_track_table()
        self._reload_track_db_table()
        self._notify_labels_changed()

    def _copy_selected_track_id(self) -> None:
        if not self._sel_track_id:
            return
        QGuiApplication.clipboard().setText(str(self._sel_track_id))

    def _favorite_selected_track(self) -> None:
        if not self._sel_track_id:
            return
        self._fav_db.add("tracks", self._sel_track_id, name=self._id_db.tracks.get(str(self._sel_track_id), ""))
        QMessageBox.information(self, "Favorites", f"Added track {self._sel_track_id} to Favorites.")

    def _update_track_buttons_state(self) -> None:
        sel_id = bool(self._sel_track_id)
        sel_name = (self.ed_sel_track_name.text() or "").strip() if hasattr(self, "ed_sel_track_name") else ""
        if hasattr(self, "btn_save_sel_track"):
            self.btn_save_sel_track.setEnabled(sel_id and bool(sel_name))
        if hasattr(self, "btn_copy_sel_track"):
            self.btn_copy_sel_track.setEnabled(sel_id)
        if hasattr(self, "btn_fav_sel_track"):
            self.btn_fav_sel_track.setEnabled(sel_id)

    # -------------------- Misc --------------------

    def _notify_labels_changed(self) -> None:
        """Best-effort: ask other tabs to repaint names immediately."""
        p = self.parent()
        # This is intentionally loose coupling; if attributes don't exist, ignore.
        for attr in ("garage_unlocks_tab", "unlock_manager_tab", "favorites_tab"):
            try:
                tab = getattr(p, attr, None)
                if tab and hasattr(tab, "refresh"):
                    tab.refresh()  # type: ignore[call-arg]
            except Exception:
                pass
        # Some tabs might have a different refresh API.
        try:
            if p and hasattr(p, "mark_unsynced"):
                p.mark_unsynced()  # type: ignore[call-arg]
        except Exception:
            pass
