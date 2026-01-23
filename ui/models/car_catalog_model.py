from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from core.car_scan import CarRow
from core.id_database import IdDatabase


@dataclass
class _Row:
    car_id: str
    db_name: str
    owned: bool
    unlocked: bool
    mileage: Optional[float]
    profile_id: Optional[str]
    has_custom_setup: bool
    swap_count: int


class CarCatalogModel(QAbstractTableModel):
    """Model for the Cars Catalog table.

    Column 1 (DB Name) is editable and persists to IdDatabase.
    """

    HEADERS = [
        "Car ID",
        "DB Name",
        "Owned",
        "Unlocked",
        "Mileage",
        "Profile",
        "Custom setup",
        "Swap keys",
    ]

    def __init__(self, *, id_db: IdDatabase):
        super().__init__()
        self._id_db = id_db
        self._rows: List[_Row] = []

    def set_rows(self, cars: List[CarRow]) -> None:
        self.beginResetModel()
        rows: List[_Row] = []
        for c in cars:
            rows.append(
                _Row(
                    car_id=str(c.car_id),
                    db_name=self._id_db.label_car(c.car_id),
                    owned=bool(c.owned),
                    unlocked=bool(c.unlocked),
                    mileage=c.mileage,
                    profile_id=c.profile_id,
                    has_custom_setup=bool(c.has_custom_setup),
                    swap_count=int(c.swap_count or 0),
                )
            )
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        r = index.row()
        c = index.column()
        if r < 0 or r >= len(self._rows):
            return None
        row = self._rows[r]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if c == 0:
                return row.car_id
            if c == 1:
                return row.db_name
            if c == 2:
                return "Yes" if row.owned else "No"
            if c == 3:
                return "Yes" if row.unlocked else "No"
            if c == 4:
                return "" if row.mileage is None else f"{row.mileage:.4f}".rstrip("0").rstrip(".")
            if c == 5:
                return "" if row.profile_id is None else str(row.profile_id)
            if c == 6:
                return "Yes" if row.has_custom_setup else "No"
            if c == 7:
                return str(row.swap_count)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if index.column() == 1:
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole):  # noqa: N802
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        if index.column() != 1:
            return False

        r = index.row()
        if r < 0 or r >= len(self._rows):
            return False

        name = str(value or "").strip()
        if not name:
            # Keep a sane default; do not delete labels silently.
            return False

        row = self._rows[r]
        row.db_name = name
        try:
            self._id_db.set_car_label(row.car_id, name)
        except Exception:
            pass

        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
        return True

    def car_id_for_row(self, row: int) -> Optional[str]:
        if 0 <= row < len(self._rows):
            return self._rows[row].car_id
        return None
