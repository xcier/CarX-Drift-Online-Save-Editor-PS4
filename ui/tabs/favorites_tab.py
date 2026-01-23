from __future__ import annotations

from typing import Any, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QPalette
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QGroupBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QMenu,
)

from core.favorites_db import FavoritesDb
from core.id_database import IdDatabase


class FavoritesTab(QWidget):
    """Editor-side favorites (does not modify the save).

    Favorites are stored in ``data/favorites.json`` and are meant to be quick
    shortcuts inside the editor UI. This tab also shows DB names (from
    ``data/id_database.json``) when the favorite category is ``cars`` or
    ``tracks``.
    """

    CATEGORIES = ["cars", "tracks", "engine_parts", "keys"]

    def __init__(self, parent: QWidget, *, id_db: IdDatabase, favorites_db: FavoritesDb):
        super().__init__(parent)
        self._id_db = id_db
        self._fav_db = favorites_db

        self._build_ui()
        self._reload_table()

    # -------------------- UI --------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        gb = QGroupBox("Favorites")
        gl = QVBoxLayout(gb)
        gl.setSpacing(8)

        toolbar = QHBoxLayout()

        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Search (matches category, value, DB name, favorite name)")
        self.ed_search.textChanged.connect(self._reload_table)
        toolbar.addWidget(self.ed_search, 2)

        self.cmb_filter = QComboBox()
        self.cmb_filter.addItem("all")
        for c in self.CATEGORIES:
            self.cmb_filter.addItem(c)
        self.cmb_filter.currentIndexChanged.connect(self._reload_table)
        toolbar.addWidget(self.cmb_filter, 0)

        # Quick add inputs (compact)
        self.cmb_cat = QComboBox()
        for c in self.CATEGORIES:
            self.cmb_cat.addItem(c)
        toolbar.addWidget(self.cmb_cat, 0)

        self.ed_value = QLineEdit()
        self.ed_value.setPlaceholderText("ID / key")
        toolbar.addWidget(self.ed_value, 1)

        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("Optional favorite name")
        toolbar.addWidget(self.ed_name, 1)

        btn_add = QPushButton("Add")
        btn_add.clicked.connect(self._add_favorite_from_inputs)
        toolbar.addWidget(btn_add)

        btn_remove = QPushButton("Remove")
        btn_remove.clicked.connect(self._remove_selected)
        toolbar.addWidget(btn_remove)

        btn_copy = QPushButton("Copy")
        btn_copy.clicked.connect(self._copy_selected_value)
        toolbar.addWidget(btn_copy)

        gl.addLayout(toolbar)

        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(["Category", "Value", "DB Name", "Favorite Name", "Added (UTC)"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setSortingEnabled(True)
        self.tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self._open_context_menu)

        gl.addWidget(self.tbl, 1)

        hint = QLabel("Favorites are stored in data/favorites.json (editor-side only).\nLabels come from data/id_database.json.")
        hint.setWordWrap(True)
        pal = hint.palette()
        pal.setColor(QPalette.ColorRole.WindowText, self.palette().color(QPalette.ColorRole.Mid))
        hint.setPalette(pal)
        gl.addWidget(hint)

        root.addWidget(gb, 1)

    # -------------------- Data / table --------------------

    def _db_name_for(self, category: str, value: str) -> str:
        cat = str(category)
        val = str(value)
        try:
            if cat == "cars":
                return self._id_db.label_car(val)
            if cat == "tracks":
                return self._id_db.label_track(val)
            if cat == "keys":
                return self._id_db.label_key(val)
        except Exception:
            return val
        return ""

    def _filtered_items(self) -> List[Tuple[int, Any]]:
        q = (self.ed_search.text() or "").strip().lower()
        cat_filter = str(self.cmb_filter.currentText() or "all").strip().lower()

        out: List[Tuple[int, Any]] = []
        for idx, it in enumerate(list(self._fav_db.items)):
            cat = str(getattr(it, "category", ""))
            val = str(getattr(it, "value", ""))
            name = str(getattr(it, "name", ""))
            added = str(getattr(it, "added", ""))

            if cat_filter != "all" and cat.lower() != cat_filter:
                continue

            db_name = self._db_name_for(cat, val)

            hay = " ".join([cat, val, db_name, name, added]).lower()
            if q and q not in hay:
                continue

            out.append((idx, it))
        return out

    def _reload_table(self) -> None:
        self.tbl.setSortingEnabled(False)
        self.tbl.setRowCount(0)

        rows = self._filtered_items()
        self.tbl.setRowCount(len(rows))

        for r, (idx, it) in enumerate(rows):
            cat = str(getattr(it, "category", ""))
            val = str(getattr(it, "value", ""))
            name = str(getattr(it, "name", ""))
            added = str(getattr(it, "added", ""))

            db_name = self._db_name_for(cat, val)

            c0 = QTableWidgetItem(cat)
            c1 = QTableWidgetItem(val)
            c2 = QTableWidgetItem(db_name)
            c3 = QTableWidgetItem(name)
            c4 = QTableWidgetItem(added)

            # store original index for removal
            c0.setData(Qt.ItemDataRole.UserRole, idx)

            for c, item in enumerate([c0, c1, c2, c3, c4]):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tbl.setItem(r, c, item)

        self.tbl.setSortingEnabled(True)

    def _selected_rows(self) -> List[int]:
        idxs: List[int] = []
        for it in self.tbl.selectedItems():
            if it.column() != 0:
                continue
            v = it.data(Qt.ItemDataRole.UserRole)
            if isinstance(v, int):
                idxs.append(v)
        # de-dupe / stable
        return sorted(set(idxs))

    # -------------------- Actions --------------------

    def _add_favorite_from_inputs(self) -> None:
        cat = str(self.cmb_cat.currentText() or "keys")
        val = str(self.ed_value.text() or "").strip()
        name = str(self.ed_name.text() or "").strip()
        if not val:
            return
        self._fav_db.add(cat, val, name=name)
        self._reload_table()

    def _remove_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        self._fav_db.remove_indices(rows)
        self._reload_table()

    def _copy_selected_value(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        # copy the first selected row's value
        for r in range(self.tbl.rowCount()):
            it0 = self.tbl.item(r, 0)
            if it0 is None:
                continue
            idx = it0.data(Qt.ItemDataRole.UserRole)
            if idx in rows:
                val_it = self.tbl.item(r, 1)
                if val_it:
                    QGuiApplication.clipboard().setText(val_it.text())
                return

    def _copy_selected_label(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        for r in range(self.tbl.rowCount()):
            it0 = self.tbl.item(r, 0)
            if it0 is None:
                continue
            idx = it0.data(Qt.ItemDataRole.UserRole)
            if idx in rows:
                lab_it = self.tbl.item(r, 2)
                if lab_it:
                    QGuiApplication.clipboard().setText(lab_it.text())
                return

    def _open_context_menu(self, pos) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        menu = QMenu(self)

        act_copy_value = menu.addAction("Copy value")
        act_copy_label = menu.addAction("Copy DB name")
        act_remove = menu.addAction("Remove selected")

        act = menu.exec(self.tbl.viewport().mapToGlobal(pos))
        if act == act_copy_value:
            self._copy_selected_value()
        elif act == act_copy_label:
            self._copy_selected_label()
        elif act == act_remove:
            self._remove_selected()

    # -------------------- Qt events --------------------

    def showEvent(self, event) -> None:  # type: ignore[override]
        # Ensure DB name column stays current when id_database.json changes elsewhere.
        try:
            self._reload_table()
        except Exception:
            pass
        super().showEvent(event)
