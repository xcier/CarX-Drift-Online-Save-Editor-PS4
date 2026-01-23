from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple, Any
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTabWidget, QTableWidget, QTableWidgetItem, QPushButton,
    QCheckBox, QComboBox, QGroupBox, QMenu, QInputDialog
)

from core.id_database import IdDatabase
from core.observed_db import ObservedDb
from core.scan_ids import scan_extracted_dir
from core.json_ops import read_text_any, try_load_json, find_first_keys


@dataclass
class RowRef:
    id_str: str
    chk: QTableWidgetItem


class UnlockManagerTab(QWidget):
    """Power-user unlock management.

    This tab is intentionally schema-aware because CarX saves have been seen with
    unlock lists stored as either:
      - availableCars / availableTracks
      - carIds / trackIds

    The Apply payload is consumed by ActionsMixin._on_apply_garage_unlocks_requested().
    """

    applyRequested = pyqtSignal(dict)
    changed = pyqtSignal()

    _SCHEMA_AUTO = "Auto"
    _SCHEMA_AVAIL = "availableCars/availableTracks"
    _SCHEMA_IDS = "carIds/trackIds"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.id_db: Optional[IdDatabase] = None
        self.extracted_dir: Optional[Path] = None
        self.observed_db_path: Optional[Path] = None

        self._schema_mode: str = self._SCHEMA_AUTO
        self._active_car_key: str = "availableCars"
        self._active_track_key: str = "availableTracks"
        self._active_source_block: Optional[str] = None  # filename

        self._cars_rows: List[RowRef] = []
        self._tracks_rows: List[RowRef] = []

        self._build_ui()

    # ---------------------------
    # UI
    # ---------------------------

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)

        # Top controls
        top_group = QGroupBox("Filter / Schema")
        top = QHBoxLayout(top_group)

        top.addWidget(QLabel("Search:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by ID or name…")
        self.search.textChanged.connect(self._apply_filter)
        top.addWidget(self.search, 1)

        top.addWidget(QLabel("Schema:"))
        self.schema_combo = QComboBox()
        self.schema_combo.addItems([self._SCHEMA_AUTO, self._SCHEMA_AVAIL, self._SCHEMA_IDS])
        self.schema_combo.setToolTip(
            "Auto detects which unlock keys exist in the extracted blocks.\n"
            "If the save has no container for the selected schema, use 'Create container'."
        )
        self.schema_combo.currentTextChanged.connect(self._on_schema_changed)
        top.addWidget(self.schema_combo)

        self.chk_merge = QCheckBox("Merge with existing (recommended)")
        self.chk_merge.setChecked(True)
        self.chk_merge.setToolTip("When enabled, adds checked IDs to the existing list. When disabled, overwrites the list.")
        self.chk_merge.toggled.connect(lambda _=False: self.changed.emit())
        top.addWidget(self.chk_merge)

        self.chk_allow_removal = QCheckBox("Allow removal (lock content)")
        self.chk_allow_removal.setToolTip(
            "When enabled and Merge is disabled, this allows you to overwrite the list and remove entries.\n"
            "Use with caution."
        )
        self.chk_allow_removal.toggled.connect(lambda _=False: self.changed.emit())
        top.addWidget(self.chk_allow_removal)

        lay.addWidget(top_group)

        # Tabs
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        self.tbl_cars = QTableWidget(0, 5)
        self.tbl_cars.setHorizontalHeaderLabels(["Unlocked", "ID", "Name", "Status", "Observed From"])
        self.tbl_cars.verticalHeader().setVisible(False)
        self.tbl_cars.setSelectionBehavior(self.tbl_cars.SelectionBehavior.SelectRows)
        self.tbl_cars.setEditTriggers(self.tbl_cars.EditTrigger.NoEditTriggers)
        self.tbl_cars.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl_cars.customContextMenuRequested.connect(
            lambda pos: self._open_label_menu("cars", self.tbl_cars, pos)
        )
        self.tabs.addTab(self.tbl_cars, "Cars")

        self.tbl_tracks = QTableWidget(0, 5)
        self.tbl_tracks.setHorizontalHeaderLabels(["Unlocked", "ID", "Name", "Status", "Observed From"])
        self.tbl_tracks.verticalHeader().setVisible(False)
        self.tbl_tracks.setSelectionBehavior(self.tbl_tracks.SelectionBehavior.SelectRows)
        self.tbl_tracks.setEditTriggers(self.tbl_tracks.EditTrigger.NoEditTriggers)
        self.tbl_tracks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl_tracks.customContextMenuRequested.connect(
            lambda pos: self._open_label_menu("tracks", self.tbl_tracks, pos)
        )
        self.tabs.addTab(self.tbl_tracks, "Tracks")

        # Bottom actions
        bottom = QHBoxLayout()
        self.lbl_source = QLabel("Source: (not loaded)")
        self.lbl_source.setToolTip("Shows which key/schema is currently used to interpret unlock lists.")
        bottom.addWidget(self.lbl_source)

        bottom.addStretch(1)

        self.btn_reload = QPushButton("Reload")
        self.btn_reload.clicked.connect(self.refresh)
        bottom.addWidget(self.btn_reload)

        self.btn_create_container = QPushButton("Create container")
        self.btn_create_container.setToolTip("Creates the selected schema container in the most likely profile block.")
        self.btn_create_container.clicked.connect(self._emit_create_container)
        bottom.addWidget(self.btn_create_container)

        self.btn_apply = QPushButton("Apply to Extracted Save")
        self.btn_apply.clicked.connect(self._emit_apply)
        bottom.addWidget(self.btn_apply)

        lay.addLayout(bottom)

        hint = QLabel(
            "This tab edits unlock lists only. 'Owned' cars (m_cars) are detected for status but are not modified."
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)

    # ---------------------------
    # Configuration / refresh
    # ---------------------------

    def configure(self, *, id_db: IdDatabase, extracted_dir: Optional[Path], observed_db_path: Path) -> None:
        self.id_db = id_db
        self.extracted_dir = extracted_dir
        self.observed_db_path = observed_db_path
        self.refresh()

    def refresh_from_workdir(self, work_dir: Path) -> None:
        """Compatibility hook used by MainWindow/ActionsMixin after extraction."""
        self.extracted_dir = work_dir
        self.refresh()


    def _resolve_blocks_dir(self) -> Optional[Path]:
        """Resolve the directory that contains extracted JSON block files.

        Users sometimes select either:
          - the extracted root (contains a 'blocks' folder), or
          - the blocks folder itself, or
          - a root containing 'extracted/blocks'.
        """
        if not self.extracted_dir:
            return None

        ed = self.extracted_dir
        # Case 1: extracted root
        if (ed / "blocks").exists():
            return ed / "blocks"

        # Case 2: user selected the blocks folder directly
        if ed.exists() and ed.is_dir() and ed.name.lower() == "blocks":
            return ed

        # Case 3: legacy layout: <root>/extracted/blocks
        if (ed / "extracted" / "blocks").exists():
            return ed / "extracted" / "blocks"

        return None


    def _iter_blocks(self) -> List[Tuple[Path, Any]]:
        blocks_dir = self._resolve_blocks_dir()
        if blocks_dir is None or not blocks_dir.exists():
            return []
        out: List[Tuple[Path, Any]] = []
        for p in sorted(blocks_dir.glob("*")):
            try:
                root = try_load_json(read_text_any(p))
                if root is None:
                    continue
                out.append((p, root))
            except Exception:
                continue
        return out

    def _detect_schema(self, blocks: List[Tuple[Path, Any]]) -> Tuple[str, str, Optional[str]]:
        """Return (car_key, track_key, source_filename)."""
        # Explicit user choice
        mode = (self.schema_combo.currentText() or self._SCHEMA_AUTO).strip()
        if mode == self._SCHEMA_AVAIL:
            return "availableCars", "availableTracks", None
        if mode == self._SCHEMA_IDS:
            return "carIds", "trackIds", None

        # Auto: prefer availableCars/availableTracks if present, else carIds/trackIds.
        for p, obj in blocks:
            got = find_first_keys(obj, ["availableCars", "availableTracks"])
            if "availableCars" in got and "availableTracks" in got:
                return "availableCars", "availableTracks", p.name
        for p, obj in blocks:
            got = find_first_keys(obj, ["carIds", "trackIds"])
            if "carIds" in got and "trackIds" in got:
                return "carIds", "trackIds", p.name

        # Partial fallback: accept whichever pair exists
        for p, obj in blocks:
            got = find_first_keys(obj, ["availableCars", "availableTracks", "carIds", "trackIds"])
            if "availableCars" in got or "availableTracks" in got:
                return "availableCars", "availableTracks", p.name
            if "carIds" in got or "trackIds" in got:
                return "carIds", "trackIds", p.name

        return "availableCars", "availableTracks", None

    def _read_first_list(self, blocks: List[Tuple[Path, Any]], key: str) -> Tuple[List[Any], Optional[str]]:
        """Return (list_value, source_filename) for first occurrence of key."""
        for p, obj in blocks:
            got = find_first_keys(obj, [key])
            if key in got and isinstance(got.get(key), list):
                return got.get(key) or [], p.name  # type: ignore[return-value]
        return [], None

    def refresh(self) -> None:
        if self.observed_db_path is None:
            return

        obs = ObservedDb.load(self.observed_db_path)

        unlocked_cars: Set[str] = set()
        unlocked_tracks: Set[str] = set()
        owned_cars: Set[str] = set()
        sources_map: Dict[str, Set[str]] = {}

        blocks = self._iter_blocks()

        # Discover IDs from save when possible (preferred)
        if blocks:
            car_key, track_key, src = self._detect_schema(blocks)
            self._active_car_key = car_key
            self._active_track_key = track_key
            self._active_source_block = src

            raw_cars, src_c = self._read_first_list(blocks, car_key)
            raw_tracks, src_t = self._read_first_list(blocks, track_key)

            unlocked_cars = {str(x).strip() for x in raw_cars if str(x).strip()}
            unlocked_tracks = {str(x).strip() for x in raw_tracks if str(x).strip()}

            if src is None:
                self._active_source_block = src_c or src_t

        # Generic scan (fills observed IDs and owned cars)
        scan_base: Optional[Path] = None
        if self.extracted_dir is not None:
            ed = self.extracted_dir
            if (ed / "blocks").exists():
                scan_base = ed
            elif ed.exists() and ed.is_dir() and ed.name.lower() == "blocks":
                scan_base = ed.parent
            elif (ed / "extracted" / "blocks").exists():
                scan_base = ed / "extracted"

        if scan_base is not None and (scan_base / "blocks").exists():
            scan = scan_extracted_dir(scan_base)
            owned_cars = scan.owned_cars
            sources_map = scan.sources

            # If schema-based lists were empty, fall back to scan results
            if not unlocked_cars:
                unlocked_cars = scan.unlocked_cars
            if not unlocked_tracks:
                unlocked_tracks = scan.unlocked_tracks

            obs.merge_ids(cars=scan.observed_cars, tracks=scan.observed_tracks, sources=scan.sources)
            obs.save(self.observed_db_path)

        src_txt = f"{self._active_car_key}/{self._active_track_key}"
        if self._active_source_block:
            src_txt += f" in {self._active_source_block}"
        self.lbl_source.setText(f"Source: {src_txt}")

        self._populate_table(self.tbl_cars, "cars", obs.cars, unlocked_cars, owned_cars, sources_map)
        self._populate_table(self.tbl_tracks, "tracks", obs.tracks, unlocked_tracks, set(), sources_map)
        self._apply_filter(self.search.text())

    # ---------------------------
    # Context menu: label IDs
    # ---------------------------

    def _open_label_menu(self, kind: str, tbl: QTableWidget, pos) -> None:
        """Right-click menu to name car/track IDs into id_database.json."""
        try:
            if not self.id_db:
                return
            idx = tbl.indexAt(pos)
            if not idx.isValid():
                return
            row = idx.row()
            id_item = tbl.item(row, 1)
            if not id_item:
                return
            raw_id = str(id_item.text() or "").strip()
            if not raw_id:
                return

            menu = QMenu(tbl)
            if kind == "cars":
                act = QAction("Set car label in database…", tbl)

                def _do() -> None:
                    existing = self.id_db.cars.get(raw_id, "")
                    name, ok = QInputDialog.getText(
                        self,
                        "Car label",
                        f"Friendly name for car ID {raw_id}:",
                        text=existing,
                    )
                    if not ok:
                        return
                    name = name.strip()
                    if not name:
                        return
                    self.id_db.set_car_label(raw_id, name)
                    self.refresh()

                act.triggered.connect(_do)
                menu.addAction(act)
            else:
                act = QAction("Set track label in database…", tbl)

                def _do() -> None:
                    existing = self.id_db.tracks.get(raw_id, "")
                    name, ok = QInputDialog.getText(
                        self,
                        "Track label",
                        f"Friendly name for track ID {raw_id}:",
                        text=existing,
                    )
                    if not ok:
                        return
                    name = name.strip()
                    if not name:
                        return
                    self.id_db.set_track_label(raw_id, name)
                    self.refresh()

                act.triggered.connect(_do)
                menu.addAction(act)

            if menu.actions():
                menu.exec(tbl.viewport().mapToGlobal(pos))
        except Exception:
            return

    # ---------------------------
    # Table population
    # ---------------------------

    def _populate_table(
        self,
        tbl: QTableWidget,
        kind: str,
        records: Dict[str, dict],
        unlocked: Set[str],
        owned: Set[str],
        sources_map: Dict[str, Set[str]],
    ) -> None:
        tbl.setRowCount(0)
        rows: List[RowRef] = []

        def name_for(_id: str) -> str:
            if self.id_db:
                if kind == "cars":
                    return self.id_db.label_car(_id) or f"Car {_id}"
                if kind == "tracks":
                    return self.id_db.label_track(_id) or f"Track {_id}"
            return f"{kind[:-1].title()} {_id}"

        def sources_for(_id: str) -> str:
            srcs = sorted(list(sources_map.get(f"{kind}:{_id}", set())))
            if not srcs:
                rec = records.get(_id) or {}
                srcs = rec.get("sources", []) if isinstance(rec.get("sources", []), list) else []
            return ", ".join(srcs)

        def _sort_key(s: str) -> int:
            return int(s) if s.isdigit() else 10**9

        all_ids = set(records.keys()) | set(unlocked) | set(owned)
        for _id in sorted(all_ids, key=_sort_key):
            row = tbl.rowCount()
            tbl.insertRow(row)

            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Checked if _id in unlocked else Qt.CheckState.Unchecked)
            tbl.setItem(row, 0, chk_item)

            tbl.setItem(row, 1, QTableWidgetItem(_id))
            tbl.setItem(row, 2, QTableWidgetItem(name_for(_id)))

            status = "Unlocked" if _id in unlocked else "Locked"
            if _id in owned:
                status = "Owned"
            tbl.setItem(row, 3, QTableWidgetItem(status))

            tbl.setItem(row, 4, QTableWidgetItem(sources_for(_id)))

            rows.append(RowRef(_id, chk_item))

        if kind == "cars":
            self._cars_rows = rows
        else:
            self._tracks_rows = rows

        tbl.resizeColumnsToContents()

    # ---------------------------
    # Emitting actions
    # ---------------------------

    def _emit_create_container(self) -> None:
        self.applyRequested.emit({
            "op": "inject_unlock_container",
            "car_key": self._active_car_key,
            "track_key": self._active_track_key,
            "schema_mode": f"{self._active_car_key}/{self._active_track_key}",
        })

    def _emit_apply(self) -> None:
        cars_checked = [r.id_str for r in self._cars_rows if r.chk.checkState() == Qt.CheckState.Checked]
        tracks_checked = [r.id_str for r in self._tracks_rows if r.chk.checkState() == Qt.CheckState.Checked]

        payload: Dict[str, Any] = {
            "cars": cars_checked,
            "tracks": tracks_checked,
            "car_key": self._active_car_key,
            "track_key": self._active_track_key,
            "schema_mode": f"{self._active_car_key}/{self._active_track_key}",
        }

        # Only include merge flag if user changed it from default (True).
        if not self.chk_merge.isChecked():
            payload["merge"] = False

        # Only used by ActionsMixin to allow overwrite/removal semantics
        if self.chk_allow_removal.isChecked():
            payload["allow_removal"] = True

        self.applyRequested.emit(payload)
        self.changed.emit()

    # Public API used by MainWindow action buttons
    def request_apply(self) -> None:
        self._emit_apply()

    # ---------------------------
    # Filtering / schema changes
    # ---------------------------

    def _apply_filter(self, text: str) -> None:
        q = (text or "").strip().lower()

        def apply(tbl: QTableWidget) -> None:
            for r in range(tbl.rowCount()):
                _id = (tbl.item(r, 1).text() if tbl.item(r, 1) else "").lower()
                nm = (tbl.item(r, 2).text() if tbl.item(r, 2) else "").lower()
                hide = bool(q) and (q not in _id) and (q not in nm)
                tbl.setRowHidden(r, hide)

        apply(self.tbl_cars)
        apply(self.tbl_tracks)

    def _on_schema_changed(self, text: str) -> None:
        t = (text or "").strip()
        if t in (self._SCHEMA_AUTO, self._SCHEMA_AVAIL, self._SCHEMA_IDS):
            self._schema_mode = t
        self.refresh()
        self.changed.emit()
