from __future__ import annotations

import json
import datetime
import os
import shutil

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QGroupBox,
    QFormLayout,
    QPlainTextEdit,
    QMessageBox,
    QFileDialog,
    QAbstractItemView,
    QComboBox,
    QProgressDialog,
)

from core.json_ops import (
    read_text_any,
    try_load_json,
    load_json_file_cached,
    dump_json_compact,
    write_text_utf16le,
    json_path_set,
    json_path_get,
)

from core.id_database import IdDatabase

_ID_KEYS: Tuple[str, ...] = ("cardId", "carId", "cardID", "carID")

_SLOT_COL_NAME = 0
_SLOT_COL_ID = 1
_SLOT_COL_LIMIT = 2


def _tokens_to_path(tokens: List[Any]) -> str:
    p = "$"
    for t in tokens:
        if isinstance(t, int):
            p += f"[{t}]"
        else:
            p += f".{t}"
    return p


def _walk_nodes(obj: Any, path: List[Any]) -> Iterable[Tuple[Any, List[Any]]]:
    """Yield (node, path_tokens) pairs with deterministic DFS order.

    Older builds materialized the entire JSON tree into a Python list before the
    caller could inspect even the first match. On large CarX blocks that made
    the Slots tab feel frozen. Yielding lets searches such as
    _find_first_key_path() stop as soon as the key is found.
    """
    stack: List[Tuple[Any, List[Any]]] = [(obj, path)]
    while stack:
        node, p = stack.pop()
        yield node, p
        if isinstance(node, dict):
            # push values in reverse for stable left-to-right traversal
            for k in list(node.keys())[::-1]:
                stack.append((node[k], p + [k]))
        elif isinstance(node, list):
            for i in range(len(node) - 1, -1, -1):
                stack.append((node[i], p + [i]))


def _raw_file_contains(path: Path, *needles: str) -> bool:
    """Cheap prefilter for extracted JSON blocks.

    Blocks are normally UTF-16LE, but a few support files can be UTF-8. Searching
    bytes for either representation avoids json.loads() for unrelated blocks.
    """
    if not needles:
        return True
    try:
        data = path.read_bytes()
    except Exception:
        return False
    for needle in needles:
        n8 = needle.encode("utf-8")
        n16 = needle.encode("utf-16le")
        if n8 not in data and n16 not in data:
            return False
    return True


def _raw_file_contains_any(path: Path, needles: Tuple[str, ...]) -> bool:
    if not needles:
        return True
    try:
        data = path.read_bytes()
    except Exception:
        return False
    for needle in needles:
        if needle.encode("utf-8") in data or needle.encode("utf-16le") in data:
            return True
    return False


def _find_first_key_path(obj: Any, key: str) -> Optional[List[Any]]:
    for node, p in _walk_nodes(obj, []):
        if isinstance(node, dict) and key in node:
            return p + [key]
    return None


def _get_by_tokens(obj: Any, tokens: List[Any]) -> Any:
    cur = obj
    for t in tokens:
        if isinstance(t, int):
            cur = cur[t]
        else:
            cur = cur[t]
    return cur


class ProgressionTab(QWidget):
    """Car Slots + Custom car captions.

    - Slot Limits: edit `m_slotLimitPerCar` and write back to the extracted block.
    - Customs: list every object that contains a `caption` field (and an id field),
      displayed as `carId/cardId - caption`, and allow editing the caption.
    """

    changed = pyqtSignal()

    def __init__(self, parent=None, *, id_db: Optional[IdDatabase] = None):
        super().__init__(parent)
        self.extracted_dir: Optional[Path] = None

        self._id_db: Optional[IdDatabase] = id_db
        self._work_dir: Optional[Path] = None

        # Cached slot limits by car id (string)
        self._slot_limits_by_id: Dict[str, int] = {}

        # Slot-limit backing state
        self._slot_src: Optional[Path] = None
        self._slot_key_path: Optional[str] = None
        self._slot_key_kind: str = "str"  # "str" | "int"
        self._slot_updating_ui = False

        # Customs backing state
        self._custom_entries: List[Dict[str, Any]] = []
        self._custom_updating_ui = False

        # Inner-page lazy state. The main window already lazy-loads the whole
        # Car Slots tab; this keeps the expensive Customs scan from running when
        # the user only wants Slot Limits.
        self._slot_limits_loaded = False
        self._customs_loaded = False
        self._refreshing = False

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        top.addWidget(self.btn_refresh)

        self.cmb_import_policy = QComboBox()
        self.cmb_import_policy.addItems([
            "Overwrite existing",
            "Only add missing",
            "Overwrite slots; keep existing captions",
        ])
        self.cmb_import_policy.setToolTip("Controls how imports merge into the current extracted save")
        top.addWidget(QLabel("Import policy:"))
        top.addWidget(self.cmb_import_policy)

        self.btn_export_bundle = QPushButton("Export Slots/Customs…")
        self.btn_export_bundle.clicked.connect(self._export_bundle_dialog)
        top.addWidget(self.btn_export_bundle)

        self.btn_import_bundle = QPushButton("Import Slots/Customs…")
        self.btn_import_bundle.clicked.connect(self._import_bundle_dialog)
        top.addWidget(self.btn_import_bundle)

        self.btn_bulk_import_bundle = QPushButton("Bulk Import…")
        self.btn_bulk_import_bundle.clicked.connect(self._bulk_import_bundle_dialog)
        top.addWidget(self.btn_bulk_import_bundle)

        self.btn_bulk_export_bundle = QPushButton("Bulk Export…")
        self.btn_bulk_export_bundle.clicked.connect(self._bulk_export_bundle_dialog)
        top.addWidget(self.btn_bulk_export_bundle)


        self.lbl_src = QLabel("")
        self.lbl_src.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.lbl_src, 1)

        root.addLayout(top)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # -----------------
        # Slot Limits page
        # -----------------
        slot_page = QWidget()
        slot_lay = QVBoxLayout(slot_page)

        slot_actions = QHBoxLayout()
        self.btn_apply_slots = QPushButton("Apply slot limits")
        self.btn_apply_slots.clicked.connect(lambda: self.apply_slot_limits(silent=False, reload_ui=True))
        slot_actions.addStretch(1)
        slot_actions.addWidget(self.btn_apply_slots)
        slot_lay.addLayout(slot_actions)

        self.tbl_slots = QTableWidget(0, 3)
        self.tbl_slots.setHorizontalHeaderLabels(["Car Name", "Car ID", "Slot Limit"])
        self.tbl_slots.verticalHeader().setVisible(False)
        self.tbl_slots.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_slots.setAlternatingRowColors(True)
        self.tbl_slots.horizontalHeader().setSectionResizeMode(_SLOT_COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.tbl_slots.horizontalHeader().setSectionResizeMode(_SLOT_COL_ID, QHeaderView.ResizeMode.Fixed)
        self.tbl_slots.horizontalHeader().setSectionResizeMode(_SLOT_COL_LIMIT, QHeaderView.ResizeMode.Fixed)
        self.tbl_slots.setColumnWidth(_SLOT_COL_ID, 110)
        self.tbl_slots.setColumnWidth(_SLOT_COL_LIMIT, 130)
        self.tbl_slots.cellChanged.connect(self._on_slot_cell_changed)
        slot_lay.addWidget(self.tbl_slots, 1)

        self.tabs.addTab(slot_page, "Slot Limits")

        # -----------------
        # Customs page
        # -----------------
        customs_page = QWidget()
        c_lay = QVBoxLayout(customs_page)

        self.custom_filter = QLineEdit()
        self.custom_filter.setPlaceholderText("Filter (carId/cardId or caption)…")
        self.custom_filter.textChanged.connect(self._rebuild_custom_list)
        c_lay.addWidget(self.custom_filter)

        split = QSplitter()
        split.setOrientation(Qt.Orientation.Horizontal)

        self.custom_list = QListWidget()
        self.custom_list.currentItemChanged.connect(self._on_custom_selected)
        split.addWidget(self.custom_list)

        right = QWidget()
        rlay = QVBoxLayout(right)

        box = QGroupBox("Selected custom")
        form = QFormLayout(box)
        self.lbl_custom_block = QLabel("")
        self.lbl_custom_id = QLabel("")
        self.lbl_custom_name = QLabel("")
        self.lbl_custom_slot = QLabel("")
        self.lbl_custom_unlocked = QLabel("")
        self.lbl_custom_path = QLabel("")
        self.edit_custom_caption = QLineEdit()
        self.meta_view = QPlainTextEdit()
        self.meta_view.setReadOnly(True)
        self.meta_view.document().setMaximumBlockCount(300)
        self.meta_view.setPlaceholderText("Selected custom metadata (read-only)")
        form.addRow("Block:", self.lbl_custom_block)
        form.addRow("Car ID:", self.lbl_custom_id)
        form.addRow("Car Name:", self.lbl_custom_name)
        form.addRow("Slot Limit:", self.lbl_custom_slot)
        form.addRow("Unlocked:", self.lbl_custom_unlocked)
        form.addRow("JSON Path:", self.lbl_custom_path)
        form.addRow("Caption:", self.edit_custom_caption)
        rlay.addWidget(box)
        rlay.addWidget(self.meta_view, 1)

        btnrow = QHBoxLayout()
        btnrow.addStretch(1)
        self.btn_apply_caption = QPushButton("Apply caption")
        self.btn_apply_caption.clicked.connect(self.apply_caption)
        btnrow.addWidget(self.btn_apply_caption)
        rlay.addLayout(btnrow)

        rlay.addStretch(1)

        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)

        c_lay.addWidget(split, 1)

        self.tabs.addTab(customs_page, "Customs")
        try:
            self.tabs.currentChanged.connect(self._on_inner_tab_changed)
        except Exception:
            pass

        self.setEnabled(False)

    def _car_name_for_id(self, car_id: Any) -> str:
        """Return the best display name from the shared car database."""
        try:
            if self._id_db is not None:
                return self._id_db.label_car(car_id)
        except Exception:
            pass
        return f"Car {car_id}"

    @staticmethod
    def _resolve_root_dir(work_dir: Path) -> Path:
        """Return the directory that actually contains the extracted blocks/ folder.

        Supports layouts:
          - <work_dir>/blocks
          - <work_dir>/extracted/blocks
          - <work_root>/<save_stem>/blocks (rare/older)
        """
        if (work_dir / "blocks").exists():
            return work_dir
        if (work_dir / "extracted" / "blocks").exists():
            return work_dir / "extracted"
        try:
            for child in sorted(work_dir.iterdir()):
                if not child.is_dir():
                    continue
                if (child / "blocks").exists():
                    return child
                if (child / "extracted" / "blocks").exists():
                    return child / "extracted"
        except Exception:
            pass
        return work_dir

    # ---------------------------
    # Context / refresh
    # ---------------------------

    def set_context(self, extracted_dir: Path) -> None:
        self.extracted_dir = extracted_dir
        self.setEnabled(True)

    def refresh_from_workdir(self, work_dir: Path) -> None:
        """Compatibility hook used by MainWindow/ActionsMixin after extraction."""
        self._work_dir = work_dir
        root_dir = self._resolve_root_dir(work_dir)
        old_dir = self.extracted_dir
        self.set_context(root_dir)
        if old_dir != root_dir:
            self._slot_limits_loaded = False
            self._customs_loaded = False
            self._custom_entries = []
        self.refresh()

    def refresh(self) -> None:
        self.lbl_src.setText("")
        self._refreshing = True
        try:
            # Always keep Slot Limits cheap/ready. Customs is much heavier, so
            # refresh it only when the inner Customs page is visible.
            self._load_slot_limits()
            if self.tabs.currentIndex() == 1:
                self._load_customs()
            elif not self._customs_loaded:
                self._custom_updating_ui = True
                try:
                    self.custom_list.clear()
                    self.meta_view.setPlainText("Open the Customs sub-tab to load custom captions.")
                    self.edit_custom_caption.setEnabled(False)
                    self.btn_apply_caption.setEnabled(False)
                finally:
                    self._custom_updating_ui = False
        finally:
            self._refreshing = False

        self._update_summary_label()

    def _update_summary_label(self) -> None:
        slot_src = self._slot_src.name if self._slot_src else "not found"
        customs = str(len(self._custom_entries)) if self._customs_loaded else "deferred"
        self.lbl_src.setText(f"Slot src: {slot_src} | Customs: {customs}")

    def _on_inner_tab_changed(self, index: int) -> None:
        if self._refreshing:
            return
        if index == 1 and not self._customs_loaded:
            # Let the tab switch paint first, then do the heavier scan.
            QTimer.singleShot(0, self._load_customs_if_visible)

    def _load_customs_if_visible(self) -> None:
        if self.tabs.currentIndex() != 1:
            return
        if self._customs_loaded:
            return
        # Customs detail uses slot limits; load them first if needed.
        if not self._slot_limits_loaded:
            self._load_slot_limits()
        self._load_customs()
        self._update_summary_label()

    # ---------------------------
    # Slot Limits
    # ---------------------------

    def _load_slot_limits(self) -> None:
        self._slot_limits_loaded = False
        self._slot_src = None
        self._slot_key_path = None
        self._slot_key_kind = "str"
        self._slot_limits_by_id = {}

        self._slot_updating_ui = True
        self.tbl_slots.setUpdatesEnabled(False)
        self.tbl_slots.blockSignals(True)
        try:
            self.tbl_slots.setRowCount(0)
        finally:
            self.tbl_slots.blockSignals(False)
            self.tbl_slots.setUpdatesEnabled(True)
            self._slot_updating_ui = False

        if self.extracted_dir is None:
            return

        blocks_dir = self.extracted_dir / "blocks"
        if not blocks_dir.exists():
            return

        found_obj: Any = None
        found_path: Optional[Path] = None
        found_key_tokens: Optional[List[Any]] = None

        for p in sorted(blocks_dir.glob("*")):
            if not _raw_file_contains(p, '"m_slotLimitPerCar"'):
                continue
            try:
                obj = load_json_file_cached(p)
            except Exception:
                continue
            kt = _find_first_key_path(obj, "m_slotLimitPerCar")
            if kt is None:
                continue
            try:
                slots = _get_by_tokens(obj, kt)
                if isinstance(slots, dict):
                    found_obj = obj
                    found_path = p
                    found_key_tokens = kt
                    break
            except Exception:
                continue

        if found_path is None or found_key_tokens is None or found_obj is None:
            return

        self._slot_src = found_path
        self._slot_key_path = _tokens_to_path(found_key_tokens)

        slots_dict = _get_by_tokens(found_obj, found_key_tokens)
        if not isinstance(slots_dict, dict):
            return

        # Infer key kind (int vs str)
        for k in slots_dict.keys():
            if isinstance(k, int):
                self._slot_key_kind = "int"
            else:
                self._slot_key_kind = "str"
            break

        # Populate table
        items: List[Tuple[str, Any]] = [(str(k), v) for k, v in slots_dict.items()]

        # Cache for Customs detail panel
        self._slot_limits_by_id = {}
        for k, v in slots_dict.items():
            try:
                self._slot_limits_by_id[str(k)] = int(float(v))
            except Exception:
                continue

        def _sort_key(t: Tuple[str, Any]) -> Tuple[int, str]:
            s = t[0]
            if s.isdigit():
                return (0, f"{int(s):09d}")
            return (1, s)

        items.sort(key=_sort_key)

        self._slot_updating_ui = True
        self.tbl_slots.setUpdatesEnabled(False)
        self.tbl_slots.blockSignals(True)
        try:
            self.tbl_slots.setRowCount(len(items))
            for r, (car_id_s, v) in enumerate(items):
                car_name = self._car_name_for_id(car_id_s)

                it_name = QTableWidgetItem(car_name)
                it_name.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                it_name.setToolTip(f"Database name: {car_name}\nCar ID: {car_id_s}")

                it_id = QTableWidgetItem(car_id_s)
                it_id.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                it_id.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it_id.setToolTip(f"Car ID: {car_id_s}")

                it_limit = QTableWidgetItem(str(v))
                it_limit.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable)
                it_limit.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                self.tbl_slots.setItem(r, _SLOT_COL_NAME, it_name)
                self.tbl_slots.setItem(r, _SLOT_COL_ID, it_id)
                self.tbl_slots.setItem(r, _SLOT_COL_LIMIT, it_limit)
        finally:
            self.tbl_slots.blockSignals(False)
            self.tbl_slots.setUpdatesEnabled(True)
            self._slot_updating_ui = False

        self._slot_limits_loaded = True

    def _on_slot_cell_changed(self, row: int, col: int) -> None:
        if self._slot_updating_ui:
            return
        if col != _SLOT_COL_LIMIT:
            return
        # Mark as dirty for auto-apply + status
        try:
            self.changed.emit()
        except Exception:
            pass
        try:
            parent = self.parent()
            if parent is not None and hasattr(parent, "mark_unsynced"):
                parent.mark_unsynced("Car Slots")
        except Exception:
            pass

    def apply_slot_limits(self, *, silent: bool = False, reload_ui: bool = True) -> None:
        if self.extracted_dir is None:
            return
        if self._slot_src is None or not self._slot_src.exists() or not self._slot_key_path:
            return

        # Build updated mapping
        new_map: Dict[Any, Any] = {}
        for r in range(self.tbl_slots.rowCount()):
            car_id_s = (self.tbl_slots.item(r, _SLOT_COL_ID).text() if self.tbl_slots.item(r, _SLOT_COL_ID) else "").strip()
            v_s = (self.tbl_slots.item(r, _SLOT_COL_LIMIT).text() if self.tbl_slots.item(r, _SLOT_COL_LIMIT) else "").strip()
            if not car_id_s:
                continue
            try:
                v_i = int(float(v_s)) if v_s else 0
            except Exception:
                continue

            key: Any = car_id_s
            if self._slot_key_kind == "int" and car_id_s.isdigit():
                key = int(car_id_s)
            new_map[key] = v_i

        try:
            obj = load_json_file_cached(self._slot_src, copy_obj=True)
            json_path_set(obj, self._slot_key_path, new_map)
            write_text_utf16le(self._slot_src, dump_json_compact(obj))

            try:
                parent = self.parent()
                if parent is not None and hasattr(parent, "mark_unsynced"):
                    parent.mark_unsynced("Car Slots")
            except Exception:
                pass

            if not silent:
                try:
                    parent = self.parent()
                    if parent is not None and hasattr(parent, "_msg"):
                        parent._msg(f"[CarSlots] Applied {len(new_map)} slot limit entries to {self._slot_src.name}.")
                except Exception:
                    pass
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Apply failed", str(e))
            return

        if reload_ui:
            self.refresh()

    # ---------------------------
    # Customs (captions)
    # ---------------------------

    def _load_customs(self) -> None:
        self._customs_loaded = False
        self._custom_entries = []
        self._custom_updating_ui = True
        try:
            self.custom_list.clear()
            self.meta_view.setPlainText("Loading custom captions…")
            self.edit_custom_caption.setEnabled(False)
            self.btn_apply_caption.setEnabled(False)
        finally:
            self._custom_updating_ui = False

        if self.extracted_dir is None:
            return
        blocks_dir = self.extracted_dir / "blocks"
        if not blocks_dir.exists():
            return

        entries: List[Dict[str, Any]] = []

        # Best-effort: detect unlocked cars so Customs can show extra context
        unlocked_ids: set[str] = set()
        unlock_keys = ('"availableCars"', '"carIds"', '"m_cars"')
        for p0 in sorted(blocks_dir.glob('*')):
            if not _raw_file_contains_any(p0, unlock_keys):
                continue
            try:
                obj0 = load_json_file_cached(p0)
            except Exception:
                continue
            for node0, _pt0 in _walk_nodes(obj0, []):
                if not isinstance(node0, dict):
                    continue
                for key in ("availableCars", "carIds", "m_cars"):
                    v0 = node0.get(key)
                    if isinstance(v0, list):
                        for x in v0:
                            try:
                                unlocked_ids.add(str(x))
                            except Exception:
                                pass
        
        id_needles = tuple(f'"{k}"' for k in _ID_KEYS)
        for p in sorted(blocks_dir.glob("*")):
            if not _raw_file_contains(p, '"caption"'):
                continue
            if not _raw_file_contains_any(p, id_needles):
                continue
            try:
                obj = load_json_file_cached(p)
            except Exception:
                continue

            # Walk dict nodes and collect caption entries
            for node, path_tokens in _walk_nodes(obj, []):
                if not isinstance(node, dict):
                    continue
                if "caption" not in node:
                    continue
                cap = node.get("caption")
                if not isinstance(cap, str):
                    continue

                id_key = None
                id_val: Any = None
                for k in _ID_KEYS:
                    if k in node:
                        id_key = k
                        id_val = node.get(k)
                        break
                if id_key is None:
                    continue

                caption_path = _tokens_to_path(path_tokens + ["caption"])

                car_id_s = str(id_val)
                car_name = self._id_db.label_car(id_val) if self._id_db else ""
                slot_limit = self._slot_limits_by_id.get(car_id_s) if hasattr(self, "_slot_limits_by_id") else None

                unlocked = car_id_s in unlocked_ids

                meta_keys = ("version", "profileId", "pid", "pid1", "visual", "format", "cardId", "carId", "customId")
                meta = {k: node.get(k) for k in meta_keys if k in node}

                entries.append(
                    {
                        "file": p,
                        "id": id_val,
                        "id_key": id_key,
                        "car_name": car_name,
                        "slot_limit": slot_limit,
                        "unlocked": unlocked,
                        "caption": cap,
                        "caption_path": caption_path,
                        "meta": meta,
                    }
                )

        self._custom_entries = entries
        self._customs_loaded = True
        self._rebuild_custom_list()

    def _rebuild_custom_list(self) -> None:
        if self._custom_updating_ui:
            return

        flt = (self.custom_filter.text() or "").strip().lower()

        self._custom_updating_ui = True
        self.custom_list.setUpdatesEnabled(False)
        self.custom_list.blockSignals(True)
        try:
            self.custom_list.clear()
            for ent in self._custom_entries:
                car_id_s = str(ent.get("id", ""))
                cap = str(ent.get("caption", ""))
                car_name = str(ent.get("car_name", ""))
                label = f"{car_id_s} - {car_name} - {cap}" if car_name else f"{car_id_s} - {cap}"

                if flt:
                    if (flt not in car_id_s.lower() and flt not in cap.lower() and flt not in car_name.lower()):
                        continue

                it = QListWidgetItem(label)
                it.setData(Qt.ItemDataRole.UserRole, ent)
                self.custom_list.addItem(it)
        finally:
            self.custom_list.blockSignals(False)
            self.custom_list.setUpdatesEnabled(True)
            self._custom_updating_ui = False

        # Clear selection panel if list is empty
        if self.custom_list.count() == 0:
            self._set_custom_detail(None)

    def _on_custom_selected(self, cur: Optional[QListWidgetItem], prev: Optional[QListWidgetItem]) -> None:
        if self._custom_updating_ui:
            return
        ent = cur.data(Qt.ItemDataRole.UserRole) if cur is not None else None
        if not isinstance(ent, dict):
            ent = None
        self._set_custom_detail(ent)

    def _set_custom_detail(self, ent: Optional[Dict[str, Any]]) -> None:
        self._custom_updating_ui = True
        try:
            if ent is None:
                self.lbl_custom_block.setText("")
                self.lbl_custom_id.setText("")
                self.lbl_custom_name.setText("")
                self.lbl_custom_slot.setText("")
                self.lbl_custom_unlocked.setText("")
                self.lbl_custom_path.setText("")
                self.meta_view.setPlainText("")
                self.edit_custom_caption.setText("")
                self.edit_custom_caption.setEnabled(False)
                self.btn_apply_caption.setEnabled(False)
                return

            p = ent.get("file")
            self.lbl_custom_block.setText(p.name if isinstance(p, Path) else str(p))
            self.lbl_custom_id.setText(str(ent.get("id", "")))
            self.lbl_custom_name.setText(str(ent.get("car_name", "")))
            sl = ent.get("slot_limit", None)
            self.lbl_custom_slot.setText("" if sl is None else str(sl))
            self.lbl_custom_unlocked.setText("Yes" if ent.get("unlocked") else "No")
            self.lbl_custom_path.setText(str(ent.get("caption_path", "")))
            try:
                meta = ent.get("meta", {})
                self.meta_view.setPlainText(json.dumps(meta, indent=2, ensure_ascii=False))
            except Exception:
                self.meta_view.setPlainText("")
            self.edit_custom_caption.setEnabled(True)
            self.btn_apply_caption.setEnabled(True)
            self.edit_custom_caption.setText(str(ent.get("caption", "")))
        finally:
            self._custom_updating_ui = False

    def apply_caption(self) -> None:
        cur = self.custom_list.currentItem()
        if cur is None:
            return
        ent = cur.data(Qt.ItemDataRole.UserRole)
        if not isinstance(ent, dict):
            return

        p = ent.get("file")
        caption_path = ent.get("caption_path")
        if not isinstance(p, Path) or not isinstance(caption_path, str):
            return

        new_caption = self.edit_custom_caption.text()
        try:
            obj = try_load_json(read_text_any(p))
            json_path_set(obj, caption_path, new_caption)
            write_text_utf16le(p, dump_json_compact(obj))

            ent["caption"] = new_caption
            car_name = str(ent.get("car_name", ""))
            cur.setText(f"{str(ent.get('id', ''))} - {car_name} - {new_caption}" if car_name else f"{str(ent.get('id', ''))} - {new_caption}")

            try:
                self.changed.emit()
            except Exception:
                pass

            try:
                parent = self.parent()
                if parent is not None and hasattr(parent, "mark_unsynced"):
                    parent.mark_unsynced("Customs")
            except Exception:
                pass

            try:
                parent = self.parent()
                if parent is not None and hasattr(parent, "_msg"):
                    parent._msg(f"[Customs] Updated caption for {ent.get('id')} in {p.name}.")
            except Exception:
                pass

        except Exception as e:
            QMessageBox.critical(self, "Apply failed", str(e))

    # ---------------------------
    # Export / Import bundle
    # ---------------------------

    def _make_bundle(self, *, car_ids: Optional[List[str]] = None, include_limits: bool = True, include_captions: bool = True) -> Dict[str, Any]:
        """Create an export bundle from the currently extracted state."""

        # Export is an explicit user action, so it is allowed to pay the Customs
        # scan cost. This preserves the old behavior: Slots/Customs exports
        # include captions even if the user has not opened the Customs sub-tab.
        if include_captions and not self._customs_loaded:
            if not self._slot_limits_loaded:
                self._load_slot_limits()
            self._load_customs()

        slot_limits: Dict[str, int] = {}

        # Prefer the authoritative data in the extracted json (if present)
        if self._slot_src is not None and self._slot_src.exists() and self._slot_key_path:
            try:
                obj = load_json_file_cached(self._slot_src, copy_obj=True)
                slots_obj = json_path_get(obj, self._slot_key_path)
                if isinstance(slots_obj, dict):
                    for k, v in slots_obj.items():
                        try:
                            slot_limits[str(k)] = int(float(v))
                        except Exception:
                            continue
            except Exception:
                pass

        # Fallback to UI table if for some reason we couldn't read from source
        if not slot_limits:
            for r in range(self.tbl_slots.rowCount()):
                car_id_s = (self.tbl_slots.item(r, _SLOT_COL_ID).text() if self.tbl_slots.item(r, _SLOT_COL_ID) else "").strip()
                v_s = (self.tbl_slots.item(r, _SLOT_COL_LIMIT).text() if self.tbl_slots.item(r, _SLOT_COL_LIMIT) else "").strip()
                if not car_id_s:
                    continue
                try:
                    slot_limits[car_id_s] = int(float(v_s)) if v_s else 0
                except Exception:
                    continue

        # Optional filtering
        if car_ids is not None:
            wanted = {str(x) for x in car_ids}
            slot_limits = {k: v for (k, v) in slot_limits.items() if k in wanted}

        captions: Dict[str, str] = {}
        for ent in self._custom_entries:
            try:
                cid = str(ent.get("id", "")).strip()
                cap = ent.get("caption", "")
                if cid and isinstance(cap, str):
                    captions[cid] = cap
            except Exception:
                continue

        if car_ids is not None:
            wanted = {str(x) for x in car_ids}
            captions = {k: v for (k, v) in captions.items() if k in wanted}

        return {
            "schema": "carx_slots_customs_bundle",
            "schema_version": 1,
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "slot_limits": slot_limits if include_limits else {},
            "captions": captions if include_captions else {},
        }

    
    # ---------------------------
    # Bundle helpers
    # ---------------------------

    def _get_import_policy(self) -> str:
        try:
            txt = self.cmb_import_policy.currentText().strip()
        except Exception:
            txt = "Overwrite existing"
        return txt or "Overwrite existing"

    def _normalize_bundle(self, obj: Any) -> Dict[str, Any]:
        """Accept older bundle shapes and normalize to the current in-memory form."""
        if not isinstance(obj, dict):
            raise ValueError("Bundle must be a JSON object.")
        # Multi bundle wrapper
        if obj.get("type") == "carx_slots_multi_bundle" and isinstance(obj.get("bundles"), list):
            # Caller should handle iterating; keep as-is
            return obj

        # Legacy keys
        slot_limits = obj.get("slot_limits") or obj.get("slots") or {}
        captions = obj.get("captions") or obj.get("customs") or {}

        out = {
            "schema": obj.get("schema") or obj.get("type") or "carx_slots_customs_bundle",
            "schema_version": int(obj.get("schema_version") or obj.get("version") or 1),
            "exported_at": obj.get("exported_at") or obj.get("created_utc") or "",
            "slot_limits": slot_limits,
            "captions": captions,
        }
        return out

    def _validate_bundle(self, b: Dict[str, Any]) -> None:
        if not isinstance(b, dict):
            raise ValueError("Bundle must be an object.")
        # allow multi wrapper
        if b.get("type") == "carx_slots_multi_bundle":
            if not isinstance(b.get("bundles"), list):
                raise ValueError("Multi bundle missing 'bundles' list.")
            return

        sl = b.get("slot_limits", {})
        cp = b.get("captions", {})
        if not isinstance(sl, dict):
            raise ValueError("'slot_limits' must be an object/dict.")
        if not isinstance(cp, dict):
            raise ValueError("'captions' must be an object/dict.")
        # Type coercion checks (don’t be too strict; just ensure keys are strings)
        for k, v in list(sl.items())[:5000]:
            if k is None:
                raise ValueError("slot_limits contains a null key.")
            try:
                int(float(v))
            except Exception:
                raise ValueError(f"slot_limits[{k!r}] is not a number.")
        for k, v in list(cp.items())[:5000]:
            if k is None:
                raise ValueError("captions contains a null key.")
            if not isinstance(v, str):
                raise ValueError(f"captions[{k!r}] is not a string.")

    def _summarize_bundle_diff(self, incoming: Dict[str, Any]) -> str:
        """Return a human-readable summary of what would change."""
        cur = self._make_bundle()
        in_sl = incoming.get("slot_limits", {}) if isinstance(incoming.get("slot_limits"), dict) else {}
        in_cp = incoming.get("captions", {}) if isinstance(incoming.get("captions"), dict) else {}

        cur_sl = cur.get("slot_limits", {}) if isinstance(cur.get("slot_limits"), dict) else {}
        cur_cp = cur.get("captions", {}) if isinstance(cur.get("captions"), dict) else {}

        add_sl = sum(1 for k in in_sl.keys() if str(k) not in cur_sl)
        chg_sl = 0
        for k, v in in_sl.items():
            ks = str(k)
            try:
                nv = int(float(v))
            except Exception:
                continue
            if ks in cur_sl and int(cur_sl.get(ks, 0)) != nv:
                chg_sl += 1

        add_cp = sum(1 for k in in_cp.keys() if str(k) not in cur_cp)
        chg_cp = 0
        for k, v in in_cp.items():
            ks = str(k)
            if ks in cur_cp and str(cur_cp.get(ks, "")) != str(v):
                chg_cp += 1

        return (
            f"Slot limits: +{add_sl} new, {chg_sl} changed\n"
            f"Captions: +{add_cp} new, {chg_cp} changed"
        )

    def _backup_affected_files(self) -> Optional[Path]:
        """Backup the JSON block files we may modify. Returns backup dir path."""
        if self.extracted_dir is None:
            return None
        backup_root = self.extracted_dir / "_backups"
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = backup_root / f"backup_{ts}"
        out_dir.mkdir(parents=True, exist_ok=True)

        paths: List[Path] = []
        if self._slot_src is not None and self._slot_src.exists():
            paths.append(self._slot_src)

        for ent in self._custom_entries:
            p = ent.get("file")
            if p:
                try:
                    pp = Path(p)
                    if pp.exists():
                        paths.append(pp)
                except Exception:
                    pass

        # de-dupe
        uniq: List[Path] = []
        seen = set()
        for p in paths:
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            uniq.append(p)

        manifest = {"files": []}
        for p in uniq:
            try:
                dest = out_dir / p.name
                shutil.copy2(p, dest)
                manifest["files"].append({"src": str(p), "dst": str(dest)})
            except Exception:
                continue

        try:
            (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass
        return out_dir

    def _apply_multi_bundles(self, bundles: List[Dict[str, Any]], *, silent: bool = False) -> None:
        """Apply a list of normalized bundles in order. If not silent, confirm + backup once."""
        if self.extracted_dir is None:
            return
        # Validate all upfront
        normed: List[Dict[str, Any]] = []
        for b in bundles:
            nb = self._normalize_bundle(b)
            self._validate_bundle(nb)
            normed.append(nb)

        if not silent:
            # Summarize combined diff (roughly)
            sum_lines = []
            for i, nb in enumerate(normed, 1):
                sum_lines.append(f"File #{i}:\n" + self._summarize_bundle_diff(nb))
            summary = "\n\n".join(sum_lines)
            resp = QMessageBox.question(
                self,
                "Confirm Bulk Import",
                summary + "\n\nProceed with bulk import? (A backup will be created.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
            self._backup_affected_files()

        # Apply in order without additional prompts/backups
        for nb in normed:
            self._apply_bundle(nb, silent=True)

        if not silent:
            QMessageBox.information(self, "Bulk Import", f"Applied {len(normed)} bundle(s).")

    def _export_bundle_dialog(self) -> None:
        if self.extracted_dir is None:
            return
        default_name = f"carx_slots_customs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        fn, _ = QFileDialog.getSaveFileName(
            self,
            "Export Slots/Customs Bundle",
            str((self.extracted_dir or Path('.')).resolve() / default_name),
            "JSON Files (*.json);;All Files (*.*)",
        )
        if not fn:
            return
        try:
            bundle = self._make_bundle()
            Path(fn).write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
            try:
                parent = self.parent()
                if parent is not None and hasattr(parent, "_msg"):
                    parent._msg(f"[Bundle] Exported slots/customs to {Path(fn).name}.")
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def _apply_bundle(self, bundle: Dict[str, Any], *, silent: bool = False) -> None:
        if self.extracted_dir is None:
            return

        # Normalize + validate
        bundle = self._normalize_bundle(bundle)
        self._validate_bundle(bundle)

        # Preview + backup (unless silent)
        if not silent:
            summary = self._summarize_bundle_diff(bundle)
            resp = QMessageBox.question(
                self,
                "Confirm Import",
                summary + "\n\nProceed with import? (A backup will be created.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
            self._backup_affected_files()

        policy = self._get_import_policy()

        slot_limits = bundle.get("slot_limits")
        captions = bundle.get("captions")

        if not isinstance(slot_limits, dict) and not isinstance(captions, dict):
            if not silent:
                QMessageBox.warning(self, "Invalid bundle", "Bundle does not contain slot_limits or captions.")
            return

        # ---- Apply slot limits (merge) ----
        slot_applied = 0
        if isinstance(slot_limits, dict) and self._slot_src is not None and self._slot_src.exists() and self._slot_key_path:
            try:
                obj = load_json_file_cached(self._slot_src, copy_obj=True)
                slots_obj = json_path_get(obj, self._slot_key_path)
                if isinstance(slots_obj, dict):
                    key_kind = "str"
                    for k in slots_obj.keys():
                        key_kind = "int" if isinstance(k, int) else "str"
                        break

                    for k, v in slot_limits.items():
                        try:
                            v_i = int(float(v))
                        except Exception:
                            continue
                        kk: Any = str(k)
                        if key_kind == "int" and str(k).isdigit():
                            kk = int(str(k))

                        # Policy: only add missing (don't overwrite)
                        if policy == "Only add missing" and kk in slots_obj:
                            continue

                        slots_obj[kk] = v_i
                        slot_applied += 1

                    json_path_set(obj, self._slot_key_path, slots_obj)
                    write_text_utf16le(self._slot_src, dump_json_compact(obj))
            except Exception as e:
                if not silent:
                    QMessageBox.critical(self, "Import failed", f"Failed applying slot limits: {e}")
                return

        # ---- Apply captions ----
        cap_applied = 0
        if isinstance(captions, dict):
            # Group edits by source file to avoid repeated loads/writes
            edits_by_file: Dict[Path, List[Tuple[str, str, Dict[str, Any]]]] = {}
            for ent in self._custom_entries:
                try:
                    cid = str(ent.get("id", "")).strip()
                    if not cid or cid not in captions:
                        continue

                    p = ent.get("file")
                    caption_path = ent.get("caption_path")
                    if not isinstance(p, Path) or not isinstance(caption_path, str):
                        continue

                    new_caption = captions.get(cid)
                    if not isinstance(new_caption, str):
                        continue

                    # Policy: keep existing captions
                    if policy in ("Only add missing", "Overwrite slots; keep existing captions"):
                        cur_cap = ent.get("caption")
                        if isinstance(cur_cap, str) and cur_cap.strip():
                            continue

                    edits_by_file.setdefault(p, []).append((caption_path, new_caption, ent))
                except Exception:
                    continue

            for p, edits in edits_by_file.items():
                try:
                    obj = load_json_file_cached(p, copy_obj=True)
                    changed_any = False
                    for caption_path, new_caption, ent in edits:
                        json_path_set(obj, caption_path, new_caption)
                        ent["caption"] = new_caption
                        cap_applied += 1
                        changed_any = True
                    if changed_any:
                        write_text_utf16le(p, dump_json_compact(obj))
                except Exception:
                    continue

        try:
            parent = self.parent()
            if parent is not None and hasattr(parent, "mark_unsynced"):
                parent.mark_unsynced("Car Slots")
                parent.mark_unsynced("Customs")
        except Exception:
            pass

        if not silent:
            try:
                parent = self.parent()
                if parent is not None and hasattr(parent, "_msg"):
                    parent._msg(f"[Bundle] Imported: {slot_applied} slot entries, {cap_applied} caption writes.")
            except Exception:
                pass

        self.refresh()

    def _import_bundle_dialog(self) -> None:
        if self.extracted_dir is None:
            return
        fn, _ = QFileDialog.getOpenFileName(
            self,
            "Import Slots/Customs Bundle",
            str((self.extracted_dir or Path('.')).resolve()),
            "JSON Files (*.json);;All Files (*.*)",
        )
        if not fn:
            return
        try:
            bundle = json.loads(Path(fn).read_text(encoding="utf-8"))
            if isinstance(bundle, dict) and bundle.get("type") == "carx_slots_multi_bundle" and isinstance(bundle.get("bundles"), list):
                self._apply_multi_bundles(bundle["bundles"], silent=False)
            else:
                if not isinstance(bundle, dict):
                    raise ValueError("Bundle root is not an object")
                self._apply_bundle(bundle, silent=False)
        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))

    def _bulk_import_bundle_dialog(self) -> None:
        if self.extracted_dir is None:
            return
        fns, _ = QFileDialog.getOpenFileNames(
            self,
            "Bulk Import Bundles",
            str((self.extracted_dir or Path('.')).resolve()),
            "JSON Files (*.json);;All Files (*.*)",
        )
        if not fns:
            return

        # Load all bundles first (so we can confirm once)
        bundles: List[Dict[str, Any]] = []
        fail_files: List[str] = []

        prog = QProgressDialog("Loading bundles…", "Cancel", 0, len(fns), self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)

        for i, fn in enumerate(fns, 1):
            prog.setValue(i - 1)
            if prog.wasCanceled():
                return
            try:
                obj = json.loads(Path(fn).read_text(encoding="utf-8"))
                if isinstance(obj, dict) and obj.get("type") == "carx_slots_multi_bundle" and isinstance(obj.get("bundles"), list):
                    for b in obj["bundles"]:
                        if isinstance(b, dict):
                            bundles.append(b)
                elif isinstance(obj, dict):
                    bundles.append(obj)
                else:
                    raise ValueError("Bundle root is not an object")
            except Exception:
                fail_files.append(Path(fn).name)

        prog.setValue(len(fns))

        if not bundles:
            QMessageBox.warning(self, "Bulk Import", "No valid bundles found.")
            return

        # Apply with single confirmation/backup
        self._apply_multi_bundles(bundles, silent=False)

        self.refresh()
        if fail_files:
            QMessageBox.information(self, "Bulk Import", f"Applied {len(bundles)} bundle(s).\nSkipped: {len(fail_files)} file(s).")


    def _selected_car_ids(self) -> List[str]:
        # Selected rows in slot table; if none selected, return all visible rows.
        ids: List[str] = []
        sel = self.tbl_slots.selectionModel().selectedRows() if self.tbl_slots.model() else []
        if sel:
            for mi in sel:
                try:
                    car_id_s = (self.tbl_slots.item(mi.row(), _SLOT_COL_ID).text() if self.tbl_slots.item(mi.row(), _SLOT_COL_ID) else "").strip()
                    if car_id_s:
                        ids.append(car_id_s)
                except Exception:
                    continue
        else:
            for r in range(self.tbl_slots.rowCount()):
                try:
                    car_id_s = (self.tbl_slots.item(r, _SLOT_COL_ID).text() if self.tbl_slots.item(r, _SLOT_COL_ID) else "").strip()
                    if car_id_s:
                        ids.append(car_id_s)
                except Exception:
                    continue
        # de-dupe preserving order
        out: List[str] = []
        seen = set()
        for x in ids:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    def _bulk_export_bundle_dialog(self) -> None:
        if self.extracted_dir is None:
            return

        car_ids = self._selected_car_ids()
        if not car_ids:
            QMessageBox.information(self, "Bulk Export", "No car IDs found to export.")
            return

        mode = QMessageBox.question(
            self,
            "Bulk Export",
            f"Export {len(car_ids)} selection(s) as ONE combined JSON file?\n\nYes = single file\nNo = one file per car",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
        )
        if mode == QMessageBox.StandardButton.Cancel:
            return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if mode == QMessageBox.StandardButton.Yes:
            default_name = f"carx_slots_multi_{ts}.json"
            fn, _ = QFileDialog.getSaveFileName(
                self,
                "Save Combined Bulk Export",
                str((self.extracted_dir or Path('.')).resolve() / default_name),
                "JSON Files (*.json);;All Files (*.*)",
            )
            if not fn:
                return

            multi = {
                "type": "carx_slots_multi_bundle",
                "version": 1,
                "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "bundles": [],
            }
            for cid in car_ids:
                b = self._make_bundle(car_ids=[cid])
                b["car_id"] = cid
                multi["bundles"].append(b)

            try:
                Path(fn).write_text(json.dumps(multi, indent=2, ensure_ascii=False), encoding="utf-8")
                QMessageBox.information(self, "Bulk Export", f"Exported {len(car_ids)} selection(s).")
            except Exception as e:
                QMessageBox.critical(self, "Bulk Export failed", str(e))
            return

        folder = QFileDialog.getExistingDirectory(self, "Choose Export Folder")
        if not folder:
            return
        folder_p = Path(folder)

        ok = 0
        for cid in car_ids:
            try:
                b = self._make_bundle(car_ids=[cid])
                out = folder_p / f"carx_slots_{cid}_{ts}.json"
                out.write_text(json.dumps(b, indent=2, ensure_ascii=False), encoding="utf-8")
                ok += 1
            except Exception:
                continue

        QMessageBox.information(self, "Bulk Export", f"Exported {ok}/{len(car_ids)} file(s).")
