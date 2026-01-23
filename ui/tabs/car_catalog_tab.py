from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import QGuiApplication, QAction
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QTableView,
    QHeaderView,
    QAbstractItemView,
    QMenu,
)

from core.car_scan import scan_cars_from_workdir
from core.id_database import IdDatabase
from ui.models.car_catalog_model import CarCatalogModel


class _MultiColumnFilterProxyModel:
    """Small proxy wrapper enabling case-insensitive multi-column filtering.

    QSortFilterProxyModel filters a single column by default. For a “search box”
    UX we want to match on both car ID and DB name. Rather than depending on
    a heavyweight helper, we implement the minimum by overriding filterAcceptsRow.
    """

    # NOTE: We intentionally avoid importing QSortFilterProxyModel at module import
    # time because PyQt6 can be slow to import; this class is instantiated lazily.
    def __init__(self):
        from PyQt6.QtCore import QSortFilterProxyModel

        class _Proxy(QSortFilterProxyModel):
            def __init__(self, parent=None):
                super().__init__(parent)
                self._q = ""
                self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

            def set_query(self, q: str) -> None:
                self._q = (q or "").strip().lower()
                self.invalidateFilter()

            def filterAcceptsRow(self, source_row: int, source_parent):  # noqa: N802
                if not self._q:
                    return True
                m = self.sourceModel()
                if m is None:
                    return True
                # Column 0 = Car ID, Column 1 = DB Name
                for col in (0, 1):
                    idx = m.index(source_row, col, source_parent)
                    s = str(m.data(idx, Qt.ItemDataRole.DisplayRole) or "").lower()
                    if self._q in s:
                        return True
                return False

        self._proxy = _Proxy()

    def proxy(self):
        return self._proxy


class CarCatalogTab(QWidget):
    """A dedicated table for car IDs + friendly naming.

    This tab is intentionally editor-side: editing the "DB Name" column writes
    to data/id_database.json and does not modify the save.
    """

    def __init__(self, parent: QWidget, *, id_db: IdDatabase):
        super().__init__(parent)
        self._id_db = id_db
        self._work_dir: Optional[Path] = None

        self._model = CarCatalogModel(id_db=self._id_db)
        self._proxy_wrap = _MultiColumnFilterProxyModel()
        self._proxy = self._proxy_wrap.proxy()
        self._proxy.setSourceModel(self._model)

        self._build_ui()

    # ------------------ Public API ------------------

    def refresh_from_workdir(self, work_dir: Path) -> None:
        self._work_dir = work_dir
        cars = scan_cars_from_workdir(work_dir)
        self._model.set_rows(cars)
        self.lbl_counts.setText(f"Cars discovered: {len(cars)}")

    # ------------------ UI ------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("Search (Car ID or DB Name)")
        self.ed_search.textChanged.connect(lambda s: self._proxy_wrap.proxy().set_query(s))
        toolbar.addWidget(self.ed_search, 2)

        self.btn_export = QPushButton("Export CSV")
        self.btn_export.clicked.connect(self._export_csv)
        toolbar.addWidget(self.btn_export)

        self.btn_import = QPushButton("Import CSV")
        self.btn_import.clicked.connect(self._import_csv)
        toolbar.addWidget(self.btn_import)

        self.btn_reload = QPushButton("Reload")
        self.btn_reload.clicked.connect(lambda: self.refresh_from_workdir(self._work_dir) if self._work_dir else None)
        toolbar.addWidget(self.btn_reload)

        root.addLayout(toolbar)

        self.tbl = QTableView()
        self.tbl.setModel(self._proxy)
        self.tbl.setSortingEnabled(True)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self._open_menu)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.tbl, 1)

        self.lbl_counts = QLabel("Cars discovered: 0")
        self.lbl_counts.setObjectName("hint")
        self.lbl_counts.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.lbl_counts)

        hint = QLabel(
            "Edit 'DB Name' to build your friendly database. Changes save to data/id_database.json and never touch the save."  # noqa: E501
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        root.addWidget(hint)

    # ------------------ Context menu ------------------

    def _open_menu(self, pos) -> None:
        idxs = self.tbl.selectionModel().selectedRows()
        if not idxs:
            return
        menu = QMenu(self)

        act_copy_ids = QAction("Copy Car IDs", self)
        act_copy_ids.triggered.connect(self._copy_selected_ids)
        menu.addAction(act_copy_ids)

        act_copy_names = QAction("Copy DB Names", self)
        act_copy_names.triggered.connect(self._copy_selected_names)
        menu.addAction(act_copy_names)

        menu.exec(self.tbl.viewport().mapToGlobal(pos))

    def _copy_selected_ids(self) -> None:
        idxs = self.tbl.selectionModel().selectedRows()
        ids = []
        for i in idxs:
            src = self._proxy.mapToSource(i)
            cid = self._model.car_id_for_row(src.row())
            if cid:
                ids.append(cid)
        if ids:
            QGuiApplication.clipboard().setText("\n".join(ids))

    def _copy_selected_names(self) -> None:
        idxs = self.tbl.selectionModel().selectedRows()
        names = []
        for i in idxs:
            src = self._proxy.mapToSource(i)
            cid = self._model.car_id_for_row(src.row())
            if not cid:
                continue
            names.append(self._id_db.label_car(cid))
        if names:
            QGuiApplication.clipboard().setText("\n".join(names))

    # ------------------ CSV Import/Export ------------------

    def _export_csv(self) -> None:
        if not self._model.rowCount():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export car names", "cars_db.csv", "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["car_id", "db_name"])
                for r in range(self._model.rowCount()):
                    cid = self._model.car_id_for_row(r) or ""
                    w.writerow([cid, self._id_db.label_car(cid)])
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))

    def _import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import car names", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            changed = 0
            with open(path, "r", newline="", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    cid = str(row.get("car_id") or "").strip()
                    name = str(row.get("db_name") or "").strip()
                    if not cid or not cid.isdigit() or not name:
                        continue
                    self._id_db.set_car_label(cid, name)
                    changed += 1
            if self._work_dir:
                self.refresh_from_workdir(self._work_dir)
            QMessageBox.information(self, "Import complete", f"Updated {changed} car name(s).")
        except Exception as e:
            QMessageBox.warning(self, "Import failed", str(e))
