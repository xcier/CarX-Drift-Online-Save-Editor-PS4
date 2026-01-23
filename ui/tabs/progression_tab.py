from __future__ import annotations

import json

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
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
    QAbstractItemView,
)

from core.json_ops import (
    read_text_any,
    try_load_json,
    dump_json_compact,
    write_text_utf16le,
    json_path_set,
)

from core.id_database import IdDatabase

_ID_KEYS: Tuple[str, ...] = ("cardId", "carId", "cardID", "carID")


def _tokens_to_path(tokens: List[Any]) -> str:
    p = "$"
    for t in tokens:
        if isinstance(t, int):
            p += f"[{t}]"
        else:
            p += f".{t}"
    return p


def _walk_nodes(obj: Any, path: List[Any]) -> List[Tuple[Any, List[Any]]]:
    """Return a flat DFS list of (node, path_tokens) pairs.

    We build a list instead of yielding to keep the implementation simple and
    deterministic (stable order for UI listing).
    """
    out: List[Tuple[Any, List[Any]]] = []
    stack: List[Tuple[Any, List[Any]]] = [(obj, path)]
    while stack:
        node, p = stack.pop()
        out.append((node, p))
        if isinstance(node, dict):
            # push values in reverse for stable left-to-right traversal
            for k in list(node.keys())[::-1]:
                stack.append((node[k], p + [k]))
        elif isinstance(node, list):
            for i in range(len(node) - 1, -1, -1):
                stack.append((node[i], p + [i]))
    return out


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

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        top.addWidget(self.btn_refresh)

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

        self.tbl_slots = QTableWidget(0, 2)
        self.tbl_slots.setHorizontalHeaderLabels(["Car ID", "Slot Limit"])
        self.tbl_slots.verticalHeader().setVisible(False)
        self.tbl_slots.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_slots.setAlternatingRowColors(True)
        self.tbl_slots.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl_slots.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
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

        self.setEnabled(False)

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
        self.set_context(root_dir)
        self.refresh()

    def refresh(self) -> None:
        self.lbl_src.setText("")
        self._load_slot_limits()
        self._load_customs()

        # Summary label
        slot_src = self._slot_src.name if self._slot_src else "not found"
        self.lbl_src.setText(f"Slot src: {slot_src} | Customs: {len(self._custom_entries)}")

    # ---------------------------
    # Slot Limits
    # ---------------------------

    def _load_slot_limits(self) -> None:
        self._slot_src = None
        self._slot_key_path = None
        self._slot_key_kind = "str"

        self._slot_updating_ui = True
        try:
            self.tbl_slots.setRowCount(0)
        finally:
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
            try:
                obj = try_load_json(read_text_any(p))
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
        try:
            for car_id_s, v in items:
                r = self.tbl_slots.rowCount()
                self.tbl_slots.insertRow(r)

                it0 = QTableWidgetItem(car_id_s)
                it0.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)

                it1 = QTableWidgetItem(str(v))
                it1.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable)
                it1.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                self.tbl_slots.setItem(r, 0, it0)
                self.tbl_slots.setItem(r, 1, it1)
        finally:
            self._slot_updating_ui = False

    def _on_slot_cell_changed(self, row: int, col: int) -> None:
        if self._slot_updating_ui:
            return
        if col != 1:
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
            car_id_s = (self.tbl_slots.item(r, 0).text() if self.tbl_slots.item(r, 0) else "").strip()
            v_s = (self.tbl_slots.item(r, 1).text() if self.tbl_slots.item(r, 1) else "").strip()
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
            obj = try_load_json(read_text_any(self._slot_src))
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
        self._custom_entries = []
        self._custom_updating_ui = True
        try:
            self.custom_list.clear()
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
        for p0 in sorted(blocks_dir.glob('*')):
            try:
                obj0 = try_load_json(read_text_any(p0))
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
        
        for p in sorted(blocks_dir.glob("*")):
            try:
                obj = try_load_json(read_text_any(p))
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
        self._rebuild_custom_list()

    def _rebuild_custom_list(self) -> None:
        if self._custom_updating_ui:
            return

        flt = (self.custom_filter.text() or "").strip().lower()

        self._custom_updating_ui = True
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
