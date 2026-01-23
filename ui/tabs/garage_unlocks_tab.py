from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import json

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QGroupBox,
    QMessageBox,
    QInputDialog,
    QSizePolicy,
    QComboBox,
    QCheckBox
)

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from core.id_database import IdDatabase
from core.apply_presets import apply_updates_to_blocks
from core.json_ops import read_text_any, try_load_json, find_first_keys


def _norm_ids(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    # tolerate single primitive
    return [str(v)]


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for x in items:
        x = str(x)
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


@dataclass
class _Dataset:
    key: str
    title: str
    ids: List[str]
    known: Set[str]


class GarageUnlocksTab(QWidget):

    """Garage & Unlocks.

    CarX Drift PS4 stores these lists in the extracted JSON blocks:
      - Cars Unlocked:    availableCars
      - Unlocked Tracks:  availableTracks
      - Favorite Cars:    m_cars

    This editor focuses on Cars/Tracks. Favorites exist in the save but are
    intentionally not exposed in the UI (more room, fewer accidental edits).

    We normalize values to strings for display, but preserve numeric IDs when
    writing back (handled by ActionsMixin when applying).
    """

    applyRequested = pyqtSignal(dict)
    changed = pyqtSignal()

    # Schema modes (how a particular save stores unlock lists)
    _SCHEMA_AUTO = "Auto"
    _SCHEMA_AVAIL = "availableCars/availableTracks"
    _SCHEMA_IDS = "carIds/trackIds"
    @staticmethod
    def _resolve_root_dir(work_dir: Path) -> Path:
        """Return the directory that actually contains the extracted 'blocks/' folder.

        Older layouts used work_dir/extracted/blocks. Newer builds write blocks directly
        under work_dir/blocks. This helper supports both.
        """
        if (work_dir / "blocks").exists():
            return work_dir
        if (work_dir / "extracted" / "blocks").exists():
            return work_dir / "extracted"
        return work_dir



    def __init__(self, parent: QWidget, *, id_db: IdDatabase, observed_db_path: Optional[Path] = None):
        super().__init__(parent)
        self._id_db = id_db
        self._observed_db_path = observed_db_path

        self._work_dir: Optional[Path] = None

        # Active schema (resolved on refresh; user can override)
        self._schema_mode: str = self._SCHEMA_AUTO
        self._active_car_key: str = "availableCars"
        self._active_track_key: str = "availableTracks"
        self._active_source_block: Optional[str] = None  # filename for display
        self._car_elem_kind: Optional[str] = None  # 'str' or 'int' (inferred)
        self._track_elem_kind: Optional[str] = None

        self._cars: List[str] = []
        self._tracks: List[str] = []
        # Favorites are intentionally not exposed in the UI.
        self._favorites: List[str] = []

        self._known_cars: Set[str] = set()
        self._known_tracks: Set[str] = set()

        # UI handles
        self._car_list: QListWidget
        self._track_list: QListWidget
        self._car_count: QLabel
        self._track_count: QLabel

        self._car_filter: QLineEdit
        self._track_filter: QLineEdit

        self._schema_combo: QComboBox
        self._btn_create_container: QPushButton

        self._build_ui()

    # -------------------------- Known IDs / observed DB -------------------------- #

    def _load_observed(self) -> Dict[str, Any]:
        if not self._observed_db_path:
            return {}
        try:
            if self._observed_db_path.exists():
                return json.loads(self._observed_db_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {}

    def _save_observed(self, obj: Dict[str, Any]) -> None:
        if not self._observed_db_path:
            return
        try:
            self._observed_db_path.parent.mkdir(parents=True, exist_ok=True)
            self._observed_db_path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            # non-fatal
            pass

    def _known_ids(self, kind: str) -> Set[str]:
        """
        kind: 'cars' or 'tracks'
        Sources:
          - id_database.json (if structured)
          - observed_db.json (auto-populated)
        """
        known: Set[str] = set()

        # Primary DB (data/id_database.json)
        try:
            if isinstance(self._id_db, IdDatabase):
                if kind == "cars":
                    known |= {str(k) for k in (self._id_db.cars or {}).keys()}
                elif kind == "tracks":
                    known |= {str(k) for k in (self._id_db.tracks or {}).keys()}
        except Exception:
            pass

        obs = self._load_observed()
        try:
            mapping = obs.get(kind)
            if isinstance(mapping, dict):
                known |= {str(k) for k in mapping.keys()}
            elif isinstance(mapping, list):
                known |= {str(x) for x in mapping}
        except Exception:
            pass

        return known

    # -------------------------- Context menus (labeling) -------------------------- #

    def _open_label_menu(self, kind: str, lw: QListWidget, pos) -> None:
        """Right-click menu to name IDs into id_database.json.

        This is the quickest way to build your database while browsing IDs.
        """
        try:
            items = lw.selectedItems()
            if not items:
                return
            if len(items) != 1:
                # Keep it simple: single selection for naming.
                return
            raw = str(items[0].data(Qt.ItemDataRole.UserRole) or "").strip()
            if not raw:
                return

            menu = QMenu(lw)
            if kind == "cars":
                act = QAction("Set car label in database…", lw)

                def _do() -> None:
                    existing = self._id_db.cars.get(raw, "")
                    name, ok = QInputDialog.getText(self, "Car label", f"Friendly name for car ID {raw}:", text=existing)
                    if not ok:
                        return
                    name = name.strip()
                    if not name:
                        return
                    self._id_db.set_car_label(raw, name)
                    self._render()

                act.triggered.connect(_do)
                menu.addAction(act)
            elif kind == "tracks":
                act = QAction("Set track label in database…", lw)

                def _do() -> None:
                    existing = self._id_db.tracks.get(raw, "")
                    name, ok = QInputDialog.getText(self, "Track label", f"Friendly name for track ID {raw}:", text=existing)
                    if not ok:
                        return
                    name = name.strip()
                    if not name:
                        return
                    self._id_db.set_track_label(raw, name)
                    self._render()

                act.triggered.connect(_do)
                menu.addAction(act)

            if menu.actions():
                menu.exec(lw.viewport().mapToGlobal(pos))
        except Exception:
            return

    # -------------------------- Extracted save scanning -------------------------- #

    def _load_state_from_blocks(self, root_dir: Path) -> Tuple[List[str], List[str], List[str]]:
        """Scan extracted blocks for garage/unlock fields.

        We select the *best* matching block based on the active schema
        (Auto / availableCars+availableTracks / carIds+trackIds).

        Returns:
          (cars, tracks, favs)

        Also sets:
          - self._active_car_key / self._active_track_key
          - self._active_source_block
          - self._car_elem_kind / self._track_elem_kind
        """

        blocks_dir = root_dir / "blocks"
        if not blocks_dir.exists():
            self._active_source_block = None
            self._car_elem_kind = None
            self._track_elem_kind = None
            return [], [], []

        def _infer_kind(v: Any) -> Optional[str]:
            if not isinstance(v, list):
                return None
            for x in v:
                if x is None:
                    continue
                return "int" if isinstance(x, int) else "str"
            return None

        def _find_best_pair(car_key: str, track_key: str) -> Optional[Tuple[Path, Any, Any]]:
            best: Optional[Tuple[int, Path, Any, Any]] = None
            for p in sorted(blocks_dir.glob("*")):
                try:
                    txt = read_text_any(p)
                    obj = try_load_json(txt)
                    if obj is None:
                        continue
                except Exception:
                    continue

                got = find_first_keys(obj, [car_key, track_key])
                if car_key not in got or track_key not in got:
                    continue
                cars_v = got.get(car_key)
                tracks_v = got.get(track_key)
                if not isinstance(cars_v, list) or not isinstance(tracks_v, list):
                    continue
                score = len(cars_v) * 1000 + len(tracks_v)
                if best is None or score > best[0]:
                    best = (score, p, cars_v, tracks_v)
            if not best:
                return None
            return best[1], best[2], best[3]

        # Resolve schema order
        wanted: List[Tuple[str, str]] = []
        if self._schema_mode == self._SCHEMA_AVAIL:
            wanted = [("availableCars", "availableTracks")]
        elif self._schema_mode == self._SCHEMA_IDS:
            wanted = [("carIds", "trackIds")]
        else:
            wanted = [("availableCars", "availableTracks"), ("carIds", "trackIds")]

        picked: Optional[Tuple[str, str, Path, Any, Any]] = None
        for ck, tk in wanted:
            got = _find_best_pair(ck, tk)
            if got:
                p, cars_v, tracks_v = got
                picked = (ck, tk, p, cars_v, tracks_v)
                break

        # Favorites are intentionally not exposed in the UI, but we still read them if present.
        favs: List[str] = []
        for p in sorted(blocks_dir.glob("*")):
            try:
                txt = read_text_any(p)
                obj = try_load_json(txt)
                if obj is None:
                    continue
            except Exception:
                continue
            got = find_first_keys(obj, ["m_cars"])
            if "m_cars" in got:
                favs.extend(_norm_ids(got.get("m_cars")))

        if not picked:
            # No container found for either schema
            # Keep the keys aligned with the current mode so the user can "Create container".
            if self._schema_mode == self._SCHEMA_IDS:
                self._active_car_key, self._active_track_key = "carIds", "trackIds"
            else:
                self._active_car_key, self._active_track_key = "availableCars", "availableTracks"
            self._active_source_block = None
            self._car_elem_kind = None
            self._track_elem_kind = None
            return [], [], _dedupe_keep_order(favs)

        car_key, track_key, src_path, cars_v, tracks_v = picked
        self._active_car_key, self._active_track_key = car_key, track_key
        self._active_source_block = src_path.name
        self._car_elem_kind = _infer_kind(cars_v)
        self._track_elem_kind = _infer_kind(tracks_v)

        cars = _dedupe_keep_order(_norm_ids(cars_v))
        tracks = _dedupe_keep_order(_norm_ids(tracks_v))
        return cars, tracks, _dedupe_keep_order(favs)

    def _render(self) -> None:
        self._fill_list(self._car_list, self._cars, kind="cars")
        self._fill_list(self._track_list, self._tracks, kind="tracks")
        self._update_counts()

        extra = []
        if self._work_dir:
            extra.append(self._work_dir.name)
        src = self._active_source_block or "<not found>"
        schema = f"{self._active_car_key}/{self._active_track_key}"
        kinds = []
        if self._car_elem_kind:
            kinds.append(f"cars:{self._car_elem_kind}")
        if self._track_elem_kind:
            kinds.append(f"tracks:{self._track_elem_kind}")
        kind_txt = (" | " + ", ".join(kinds)) if kinds else ""
        note = f"Source: {schema} in {src}{kind_txt}" + (f" ({', '.join(extra)})" if extra else "")
        if not self._active_source_block:
            note += "  —  No unlock container found. Use Schema selector and 'Create container' if needed."
        self._status.setText(note)

        # Enable create-container button when missing
        try:
            self._btn_create_container.setEnabled(bool(self._work_dir) and not bool(self._active_source_block))
        except Exception:
            pass

    def _open_label_menu(self, kind: str, lw: QListWidget, pos) -> None:
        """Right-click helper to name an ID in the shared id_database.json."""
        try:
            items = lw.selectedItems()
            if len(items) != 1:
                return
            raw_id = str(items[0].data(Qt.ItemDataRole.UserRole) or "").strip()
            if not raw_id:
                return

            menu = QMenu(lw)
            act = QAction("Set label in database…", lw)

            def _do() -> None:
                if kind == "cars":
                    existing = self._id_db.cars.get(raw_id, "")
                    txt, ok = QInputDialog.getText(self, "Car label", f"Name for car ID {raw_id}:", text=existing)
                    if ok and txt.strip():
                        self._id_db.set_car_label(raw_id, txt.strip())
                elif kind == "tracks":
                    existing = self._id_db.tracks.get(raw_id, "")
                    txt, ok = QInputDialog.getText(self, "Track label", f"Name for track ID {raw_id}:", text=existing)
                    if ok and txt.strip():
                        self._id_db.set_track_label(raw_id, txt.strip())
                try:
                    self._render()
                except Exception:
                    pass

            act.triggered.connect(_do)
            menu.addAction(act)
            menu.exec(lw.viewport().mapToGlobal(pos))
        except Exception:
            return

    def _fill_list(self, lw: QListWidget, ids: List[str], *, kind: str) -> None:
        lw.blockSignals(True)
        try:
            lw.clear()
            for raw in _dedupe_keep_order([str(x).strip() for x in ids if str(x).strip()]):
                if kind == "cars":
                    name = self._id_db.label_car(raw)
                elif kind == "tracks":
                    name = self._id_db.label_track(raw)
                else:
                    name = ""
                txt = f"{raw} - {name}" if name else raw
                it = QListWidgetItem(txt)
                # Preserve the raw ID for saving/apply logic.
                it.setData(Qt.ItemDataRole.UserRole, raw)
                lw.addItem(it)
        finally:
            lw.blockSignals(False)

    def _update_counts(self) -> None:
        self._update_count_label(self._car_count, self._collect_list(self._car_list), self._known_cars)
        self._update_count_label(self._track_count, self._collect_list(self._track_list), self._known_tracks)

    def _update_count_label(self, label: QLabel, current: List[str], known: Set[str], *, extra_note: Optional[str] = None) -> None:
        cur = len(current)
        known_n = len(known) if known else 0
        if known_n:
            missing = max(0, known_n - cur)
            txt = f"{cur} / {known_n} (missing {missing})"
        else:
            txt = f"{cur}"
        if extra_note:
            txt = f"{txt}  |  {extra_note}"
        label.setText(txt)

    # -------------------------- UI -------------------------- #

    def _build_section(self, title: str) -> Tuple[QGroupBox, QListWidget, QLineEdit, QLabel]:
        box = QGroupBox(title)
        outer = QVBoxLayout(box)

        top = QHBoxLayout()
        lbl_count = QLabel("0")
        lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_count.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        edit_filter = QLineEdit()
        edit_filter.setPlaceholderText("Filter…")
        edit_filter.setClearButtonEnabled(True)

        top.addWidget(edit_filter, 1)
        top.addWidget(lbl_count, 0)
        outer.addLayout(top)

        lw = QListWidget()
        lw.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        outer.addWidget(lw, 1)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("Add")
        btn_remove = QPushButton("Remove")
        btn_clear = QPushButton("Clear")

        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_remove)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        # wire local lambdas later (we need key)
        box._btn_add = btn_add     # type: ignore[attr-defined]
        box._btn_remove = btn_remove  # type: ignore[attr-defined]
        box._btn_clear = btn_clear # type: ignore[attr-defined]

        return box, lw, edit_filter, lbl_count

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Garage & Unlocks")
        title.setStyleSheet("font-weight: 600; font-size: 15px;")
        header.addWidget(title)

        # Schema selector (Auto / explicit pairs)
        header.addSpacing(12)
        header.addWidget(QLabel("Schema:"))
        self._schema_combo = QComboBox()
        self._schema_combo.addItems([self._SCHEMA_AUTO, self._SCHEMA_AVAIL, self._SCHEMA_IDS])
        self._schema_combo.setCurrentText(self._schema_mode)
        self._schema_combo.setToolTip(
            "How this save stores unlock lists. Auto picks the best match.\n"
            "If a save has no container, choose a schema and click 'Create container'."
        )
        header.addWidget(self._schema_combo)

        self._btn_create_container = QPushButton("Create container")
        self._btn_create_container.setEnabled(False)
        self._btn_create_container.setToolTip(
            "Creates the unlock list keys inside the extracted blocks when a save does not contain them."
        )
        header.addWidget(self._btn_create_container)

        self.chk_merge = QCheckBox("Merge with existing (add only)")
        self.chk_merge.setChecked(True)
        self.chk_merge.setToolTip("Recommended: keeps existing unlocks and only adds new IDs.\nUncheck to REPLACE the save's unlock list exactly with your current list.")
        header.addSpacing(12)
        header.addWidget(self.chk_merge)


        header.addStretch(1)

        btn_unlock_all_cars = QPushButton("Unlock ALL Cars")
        btn_unlock_all_tracks = QPushButton("Unlock ALL Tracks")

        header.addWidget(btn_unlock_all_cars)
        header.addWidget(btn_unlock_all_tracks)

        root.addLayout(header)

        # sections
        sec_row = QHBoxLayout()

        cars_box, self._car_list, self._car_filter, self._car_count = self._build_section("Cars Unlocked")
        tracks_box, self._track_list, self._track_filter, self._track_count = self._build_section("Unlocked Tracks")
        sec_row.addWidget(cars_box, 1)
        sec_row.addWidget(tracks_box, 1)
        root.addLayout(sec_row, 1)

        footer = QHBoxLayout()
        self._status = QLabel("")
        self._status.setWordWrap(True)
        btn_apply = QPushButton("Apply Garage & Unlocks")
        btn_apply.setDefault(True)

        footer.addWidget(self._status, 1)
        footer.addWidget(btn_apply, 0)
        root.addLayout(footer)

        # Filters
        self._car_filter.textChanged.connect(lambda t: self._apply_filter(self._car_list, t))
        self._track_filter.textChanged.connect(lambda t: self._apply_filter(self._track_list, t))
        # Favorites UI removed

        # Right-click naming (writes to id_database.json; reflected across all tabs)
        self._car_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._car_list.customContextMenuRequested.connect(
            lambda pos: self._open_label_menu("cars", self._car_list, pos)
        )
        self._track_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._track_list.customContextMenuRequested.connect(
            lambda pos: self._open_label_menu("tracks", self._track_list, pos)
        )

        # list actions
        cars_box._btn_add.clicked.connect(lambda: self._prompt_add(self._car_list))  # type: ignore[attr-defined]
        cars_box._btn_remove.clicked.connect(lambda: self._remove_selected(self._car_list))  # type: ignore[attr-defined]
        cars_box._btn_clear.clicked.connect(lambda: self._clear(self._car_list))  # type: ignore[attr-defined]

        tracks_box._btn_add.clicked.connect(lambda: self._prompt_add(self._track_list))  # type: ignore[attr-defined]
        tracks_box._btn_remove.clicked.connect(lambda: self._remove_selected(self._track_list))  # type: ignore[attr-defined]
        tracks_box._btn_clear.clicked.connect(lambda: self._clear(self._track_list))  # type: ignore[attr-defined]

        # presets
        btn_unlock_all_cars.clicked.connect(self._preset_unlock_all_cars)
        btn_unlock_all_tracks.clicked.connect(self._preset_unlock_all_tracks)

        # apply
        btn_apply.clicked.connect(self.request_apply)

        # schema
        self._schema_combo.currentTextChanged.connect(self._on_schema_changed)
        self._btn_create_container.clicked.connect(self._request_create_container)

    # -------------------------- Public API -------------------------- #

    def refresh_from_workdir(self, work_dir: Path) -> None:
        self._work_dir = work_dir
        root_dir = self._resolve_root_dir(work_dir)
        blocks_dir = root_dir / 'blocks'
        if not blocks_dir.exists():
            self._status.setText('Blocks directory not found. Extract first.')
            return

        self._known_cars = self._known_ids("cars")
        self._known_tracks = self._known_ids("tracks")

        self._cars, self._tracks, self._favorites = self._load_state_from_blocks(root_dir)

        # update observed db with what we have
        obs = self._load_observed()
        obs.setdefault("cars", {})
        obs.setdefault("tracks", {})
        if isinstance(obs["cars"], dict):
            for cid in self._cars:
                obs["cars"].setdefault(str(cid), "")
        if isinstance(obs["tracks"], dict):
            for tid in self._tracks:
                obs["tracks"].setdefault(str(tid), "")
        self._save_observed(obs)

        self._render()
    def get_payload(self) -> Dict[str, Any]:
        return {
            "car_key": self._active_car_key,
            "track_key": self._active_track_key,
            "cars": self._collect_list(self._car_list),
            "tracks": self._collect_list(self._track_list),
            "schema_mode": self._schema_mode,
            "merge": bool(getattr(self, "chk_merge", None) and self.chk_merge.isChecked()),
        }


    def request_apply(self) -> None:
        """Emit an apply request payload for MainWindow/ActionsMixin."""
        if not self._work_dir:
            QMessageBox.warning(self, "No project", "Open a save and extract first.")
            return
        payload = self.get_payload()
        self.applyRequested.emit(payload)
        self._update_counts()
        try:
            self._status.setText("Auto-synced changes pending…")
        except Exception:
            pass

    def _collect_list(self, lw: QListWidget) -> List[str]:
        out = []
        for i in range(lw.count()):
            it = lw.item(i)
            raw = it.data(Qt.ItemDataRole.UserRole)
            if raw is None:
                # Fallback for older items: take "ID - Name" prefix
                raw = str(it.text()).split(" - ", 1)[0].strip()
            out.append(str(raw).strip())
        return _dedupe_keep_order([x for x in out if x])

    # -------------------------- UI actions -------------------------- #

    def _apply_filter(self, lw: QListWidget, text: str) -> None:
        t = (text or "").strip().lower()
        for i in range(lw.count()):
            it = lw.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def _on_schema_changed(self, text: str) -> None:
        """User changed schema mode (Auto / explicit). Refreshes the view from current workdir."""
        t = (text or "").strip() or self._SCHEMA_AUTO
        if t not in (self._SCHEMA_AUTO, self._SCHEMA_AVAIL, self._SCHEMA_IDS):
            t = self._SCHEMA_AUTO
        self._schema_mode = t
        if self._work_dir is not None:
            # re-load from extracted blocks using the new mode
            self.refresh_from_workdir(self._work_dir)

    def _request_create_container(self) -> None:
        """Ask MainWindow/ActionsMixin to inject an unlock container into extracted blocks."""
        if not self._work_dir:
            QMessageBox.warning(self, "No project", "Open a save and extract first.")
            return
        if self._active_source_block:
            QMessageBox.information(self, "Already present", "This save already contains an unlock container.")
            return
        payload = {
            "__op": "inject_unlock_container",
            "car_key": self._active_car_key,
            "track_key": self._active_track_key,
        }
        self.applyRequested.emit(payload)

    def _prompt_add(self, lw: QListWidget) -> None:
        s, ok = QInputDialog.getText(self, "Add ID", "Enter ID (string or number):")
        if not ok:
            return
        s = str(s).strip()
        if not s:
            return
        # append and de-dupe by re-rendering
        items = self._collect_list(lw)
        items.append(s)
        # Determine kind from widget
        kind = "cars" if lw is self._car_list else "tracks"
        self._fill_list(lw, _dedupe_keep_order(items), kind=kind)
        self._update_counts()
        self._update_counts()
        self.changed.emit()


    def _remove_selected(self, lw: QListWidget) -> None:
        # QListWidget.selectedIndexes() returns QModelIndex; simplest is selectedItems().
        for it in lw.selectedItems():
            row = lw.row(it)
            lw.takeItem(row)
        self._update_counts()
        self._update_counts()
        self.changed.emit()


    def _clear(self, lw: QListWidget) -> None:
        lw.clear()
        self._update_counts()
        self._update_counts()
        self.changed.emit()


    def _preset_unlock_all_cars(self) -> None:
        known = sorted(self._known_cars, key=lambda x: int(x) if x.isdigit() else x)
        if not known:
            QMessageBox.information(self, "No ID DB", "No known car IDs available (id_database/observed_db is empty).")
            return
        self._fill_list(self._car_list, known, kind="cars")
        self._update_counts()
        self._update_counts()
        self.changed.emit()


    def _preset_unlock_all_tracks(self) -> None:
        known = sorted(self._known_tracks, key=lambda x: int(x) if x.isdigit() else x)
        if not known:
            QMessageBox.information(self, "No ID DB", "No known track IDs available (id_database/observed_db is empty).")
            return
        self._fill_list(self._track_list, known, kind="tracks")
        self._update_counts()
        self._update_counts()
        self.changed.emit()


