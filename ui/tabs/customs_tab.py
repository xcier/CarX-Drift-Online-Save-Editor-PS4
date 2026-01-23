from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QGroupBox,
    QFormLayout,
    QMessageBox,
)

from core.json_ops import read_text_any, try_load_json, dump_json_compact, write_text_utf16le, set_first_keys


def _deep_find(obj: Any, key: str):
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if key in cur:
                return cur[key]
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


@dataclass
class CustomCarEntry:
    path: Path
    car_id: str
    caption: str

    @property
    def display(self) -> str:
        cap = (self.caption or "").strip()
        return f"{self.car_id} - {cap}" if cap else f"{self.car_id} - <no caption>"


class CustomsTab(QWidget):
    """Browse/edit custom car captions.

    We scan extracted JSON blocks and keep any block containing a `caption` key.
    Entries are displayed as `carId - caption`.
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.extracted_dir: Optional[Path] = None
        self._entries: list[CustomCarEntry] = []
        self._loading = False

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        top.addWidget(self.btn_refresh)

        self.lbl_src = QLabel("")
        self.lbl_src.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.lbl_src, 1)
        root.addLayout(top)

        self.split = QSplitter()
        root.addWidget(self.split, 1)

        # Left: filter + list
        left = QWidget()
        ll = QVBoxLayout(left)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter (carId or caption)…")
        self.filter_edit.textChanged.connect(self._refilter)
        ll.addWidget(self.filter_edit)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_selected)
        ll.addWidget(self.list, 1)
        self.split.addWidget(left)

        # Right: detail editor
        right = QWidget()
        rl = QVBoxLayout(right)

        box = QGroupBox("Selected custom")
        form = QFormLayout(box)

        self.lbl_block = QLabel("")
        self.lbl_block.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_car_id = QLabel("")
        self.lbl_car_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.caption_edit = QLineEdit()
        self.caption_edit.textEdited.connect(self._on_caption_edited)

        form.addRow("Block:", self.lbl_block)
        form.addRow("Car ID:", self.lbl_car_id)
        form.addRow("Caption:", self.caption_edit)
        rl.addWidget(box)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_apply = QPushButton("Apply caption")
        self.btn_apply.clicked.connect(self.apply_caption)
        btn_row.addWidget(self.btn_apply)
        rl.addLayout(btn_row)
        rl.addStretch(1)

        self.split.addWidget(right)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 2)

        self.setEnabled(False)

    # ---------------------------
    # Lifecycle
    # ---------------------------

    def set_context(self, extracted_dir: Path) -> None:
        self.extracted_dir = extracted_dir
        self.setEnabled(True)

    def refresh_from_workdir(self, work_dir: Path) -> None:
        self.set_context(work_dir)
        self.refresh()

    # ---------------------------
    # Data
    # ---------------------------

    def refresh(self) -> None:
        self._entries.clear()
        self.list.clear()
        self.lbl_src.setText("")
        self._loading = True
        try:
            self.caption_edit.setText("")
            self.lbl_block.setText("")
            self.lbl_car_id.setText("")
        finally:
            self._loading = False

        if self.extracted_dir is None:
            return
        blocks_dir = self.extracted_dir / "blocks"
        if not blocks_dir.exists():
            return

        found = 0
        for p in sorted(blocks_dir.glob("*")):
            try:
                o = try_load_json(read_text_any(p))
            except Exception:
                continue

            cap = _deep_find(o, "caption")
            if cap is None:
                continue

            car_id = _deep_find(o, "carId")
            if car_id is None:
                # Some blocks may not include carId; still show, but keep stable.
                car_id_s = "?"
            else:
                car_id_s = str(car_id)

            entry = CustomCarEntry(path=p, car_id=car_id_s, caption=str(cap))
            self._entries.append(entry)
            found += 1

        # Stable sorting by numeric car id, then caption
        def _sort_key(e: CustomCarEntry):
            try:
                return (0, int(e.car_id), e.caption.lower())
            except Exception:
                return (1, e.car_id, e.caption.lower())

        self._entries.sort(key=_sort_key)
        self.lbl_src.setText(f"Found {found} caption block(s)")
        self._refilter()

    def _refilter(self) -> None:
        q = (self.filter_edit.text() or "").strip().lower()
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for e in self._entries:
                hay = f"{e.car_id} {e.caption}".lower()
                if q and q not in hay:
                    continue
                it = QListWidgetItem(e.display)
                it.setData(Qt.ItemDataRole.UserRole, e)
                self.list.addItem(it)
        finally:
            self.list.blockSignals(False)

        # Keep selection reasonable
        if self.list.count() > 0 and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

    def _current_entry(self) -> Optional[CustomCarEntry]:
        it = self.list.currentItem()
        if it is None:
            return None
        e = it.data(Qt.ItemDataRole.UserRole)
        return e if isinstance(e, CustomCarEntry) else None

    # ---------------------------
    # UI handlers
    # ---------------------------

    def _on_selected(self, cur: QListWidgetItem, prev: QListWidgetItem) -> None:  # type: ignore[override]
        _ = prev
        e = cur.data(Qt.ItemDataRole.UserRole) if cur is not None else None
        if not isinstance(e, CustomCarEntry):
            return
        self._loading = True
        try:
            self.lbl_block.setText(e.path.name)
            self.lbl_car_id.setText(e.car_id)
            self.caption_edit.setText(e.caption)
        finally:
            self._loading = False

    def _on_caption_edited(self, _text: str) -> None:
        if self._loading:
            return
        self.changed.emit()

    def apply_caption(self) -> None:
        if self.extracted_dir is None:
            return
        e = self._current_entry()
        if e is None:
            return

        new_caption = (self.caption_edit.text() or "").strip()
        try:
            obj = try_load_json(read_text_any(e.path))
        except Exception as ex:
            QMessageBox.critical(self, "Read failed", str(ex))
            return

        try:
            n = set_first_keys(obj, {"caption": new_caption})
            if n <= 0:
                QMessageBox.warning(self, "Not applied", "Could not find a caption field to update in this block.")
                return
            write_text_utf16le(e.path, dump_json_compact(obj))
        except Exception as ex:
            QMessageBox.critical(self, "Apply failed", str(ex))
            return

        # Update cached entry + list label
        e.caption = new_caption
        it = self.list.currentItem()
        if it is not None:
            it.setText(e.display)

        # Mark main window unsynced if available (pending repack)
        try:
            mw = self.window()
            if hasattr(mw, "mark_unsynced"):
                mw.mark_unsynced("customs")  # type: ignore[attr-defined]
        except Exception:
            pass
