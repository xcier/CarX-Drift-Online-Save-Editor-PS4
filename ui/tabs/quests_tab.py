from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QMessageBox
)

from core.json_ops import read_text_any, try_load_json


def _deep_find_first(obj: Any, keys: List[str]) -> Optional[Tuple[str, Any]]:
    keyset = set(keys)
    stack = [("$", obj)]
    while stack:
        path, cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in keyset:
                    return (f"{path}.{k}" if path != "$" else f"$.{k}", v)
                stack.append((f"{path}.{k}" if path != "$" else f"$.{k}", v))
        elif isinstance(cur, list):
            for i, v in enumerate(cur):
                stack.append((f"{path}[{i}]", v))
    return None


class QuestsTab(QWidget):
    """Read-only view of quests/events."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.extracted_dir: Optional[Path] = None

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        top.addWidget(self.btn_refresh)

        top.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("name/id contains…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        top.addWidget(self.filter_edit, 1)

        self.lbl_src = QLabel("Source: (none)")
        self.lbl_src.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.lbl_src)
        lay.addLayout(top)

        self.tbl = QTableWidget(0, 7)
        self.tbl.setHorizontalHeaderLabels(["Name/Id", "State", "Progress", "Start", "End", "Rewards", "Raw Keys"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(self.tbl.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(self.tbl.EditTrigger.NoEditTriggers)
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tbl, 1)

        self.setEnabled(False)

    def set_context(self, extracted_dir: Path) -> None:
        self.extracted_dir = extracted_dir
        self.setEnabled(True)

    def refresh_from_workdir(self, work_dir: Path) -> None:
        """Compatibility hook used by MainWindow/ActionsMixin after extraction."""
        self.set_context(work_dir)
        self.refresh()

    def refresh(self) -> None:
        self.tbl.setRowCount(0)
        self.lbl_src.setText("Source: (none)")

        if self.extracted_dir is None:
            return
        blocks_dir = self.extracted_dir / "blocks"
        if not blocks_dir.exists():
            return

        # Locate quests list in any block
        found_block = None
        found_val = None
        for p in sorted(blocks_dir.glob("*")):
            try:
                obj = try_load_json(read_text_any(p))
                if obj is None:
                    continue
                hit = _deep_find_first(obj, ["<quests>k__BackingField", "quests"])
                if hit and isinstance(hit[1], list):
                    found_block = p
                    found_val = hit[1]
                    break
            except Exception:
                continue

        if found_block is None or not isinstance(found_val, list):
            self.lbl_src.setText("Source: not found")
            return

        self.lbl_src.setText(f"Source: {found_block.name} ({len(found_val)} quests)")
        for q in found_val:
            if not isinstance(q, dict):
                continue
            name = str(q.get("name") or q.get("id") or q.get("questId") or q.get("title") or "Quest")
            state = str(q.get("state") or q.get("status") or ("completed" if q.get("completed") else ""))
            prog = str(q.get("progress") or q.get("current") or q.get("value") or "")
            start = str(q.get("start") or q.get("startDate") or q.get("startTime") or "")
            end = str(q.get("end") or q.get("endDate") or q.get("endTime") or "")
            rewards = q.get("rewards") or q.get("reward") or q.get("compensation") or ""
            if isinstance(rewards, (dict, list)):
                rewards_s = str(rewards)[:120]
            else:
                rewards_s = str(rewards)
            raw_keys = ", ".join(sorted([k for k in q.keys() if isinstance(k, str)])[:12])

            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            self.tbl.setItem(r, 0, QTableWidgetItem(name))
            self.tbl.setItem(r, 1, QTableWidgetItem(state))
            self.tbl.setItem(r, 2, QTableWidgetItem(prog))
            self.tbl.setItem(r, 3, QTableWidgetItem(start))
            self.tbl.setItem(r, 4, QTableWidgetItem(end))
            self.tbl.setItem(r, 5, QTableWidgetItem(rewards_s))
            self.tbl.setItem(r, 6, QTableWidgetItem(raw_keys))

        self._apply_filter(self.filter_edit.text())

    def _apply_filter(self, text: str) -> None:
        q = (text or "").strip().lower()
        for r in range(self.tbl.rowCount()):
            nm = (self.tbl.item(r, 0).text() if self.tbl.item(r, 0) else "").lower()
            hide = bool(q) and q not in nm
            self.tbl.setRowHidden(r, hide)