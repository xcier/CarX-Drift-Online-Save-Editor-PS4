from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGroupBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QPushButton,
    QMessageBox,
)


@dataclass
class _KeyBinding:
    key: str
    widget: QSpinBox
    original_type: type = str


class StatsTab(QWidget):
    """Readable + editable stats tab.

    Responsibilities:
      - Present common profile stats with friendly labels
      - Allow edits with safe numeric widgets
      - Emit a dict of updates to be applied by MainWindow

    MainWindow remains the source of truth for applying updates into blocks.
    """

    applyRequested = pyqtSignal(dict)
    changed = pyqtSignal()

    def __init__(
        self,
        *,
        id_db: Any,
        format_number_like: Callable[[Any], str],
        seconds_to_duration: Callable[[int], str],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._id_db = id_db
        self._format_number_like = format_number_like
        self._seconds_to_duration = seconds_to_duration

        self._bindings: Dict[str, _KeyBinding] = {}

        self._build_ui()

    # -------------------------
    # UI
    # -------------------------

    def _label_for_key(self, key: str) -> str:
        try:
            lbl = self._id_db.label_key(key) if self._id_db else None
        except Exception:
            lbl = None
        return lbl or key

    def _make_spin(self, *, maximum: int = 2_000_000_000) -> QSpinBox:
        sb = QSpinBox()
        sb.setRange(0, maximum)
        sb.setValue(0)
        sb.setKeyboardTracking(False)
        return sb

    def _bind_spin(self, key: str, sb: QSpinBox) -> None:
        self._bindings[key] = _KeyBinding(key=key, widget=sb, original_type=str)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(12)

        # --- Playtime & races
        grp_play = QGroupBox("Playtime & Races")
        form_play = QFormLayout(grp_play)
        form_play.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_play.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form_play.setHorizontalSpacing(12)
        form_play.setVerticalSpacing(8)

        self.time_seconds = self._make_spin(maximum=2_000_000_000)
        self.time_seconds.valueChanged.connect(self._refresh_duration)
        self.time_human = QLabel("")
        self.time_human.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.races_played = self._make_spin()
        self.drift_races_played = self._make_spin()
        self.time_attack_races_played = self._make_spin()
        self.mp_races_played = self._make_spin()

        self._bind_spin("timeInGame", self.time_seconds)
        self._bind_spin("racesPlayed", self.races_played)
        self._bind_spin("driftRacesPlayed", self.drift_races_played)
        self._bind_spin("timeAttackRacesPlayed", self.time_attack_races_played)
        self._bind_spin("MPRacesPlayed", self.mp_races_played)

        form_play.addRow(self._label_for_key("timeInGame"), self.time_seconds)
        form_play.addRow("Duration", self.time_human)
        form_play.addRow(self._label_for_key("racesPlayed"), self.races_played)
        form_play.addRow(self._label_for_key("driftRacesPlayed"), self.drift_races_played)
        form_play.addRow(self._label_for_key("timeAttackRacesPlayed"), self.time_attack_races_played)
        form_play.addRow(self._label_for_key("MPRacesPlayed"), self.mp_races_played)

        # --- Cups
        grp_cups = QGroupBox("Cups")
        form_cups = QFormLayout(grp_cups)
        form_cups.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_cups.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form_cups.setHorizontalSpacing(12)
        form_cups.setVerticalSpacing(8)

        self.cups1 = self._make_spin()
        self.cups2 = self._make_spin()
        self.cups3 = self._make_spin()
        self._bind_spin("cups1", self.cups1)
        self._bind_spin("cups2", self.cups2)
        self._bind_spin("cups3", self.cups3)

        form_cups.addRow(self._label_for_key("cups1"), self.cups1)
        form_cups.addRow(self._label_for_key("cups2"), self.cups2)
        form_cups.addRow(self._label_for_key("cups3"), self.cups3)

        # --- Points
        grp_points = QGroupBox("Points")
        form_points = QFormLayout(grp_points)
        form_points.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_points.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form_points.setHorizontalSpacing(12)
        form_points.setVerticalSpacing(8)

        self.max_points_per_drift = self._make_spin()
        self.max_points_per_race = self._make_spin()
        self.avg_points_per_race = self._make_spin()
        self._bind_spin("maxPointsPerDrift", self.max_points_per_drift)
        self._bind_spin("maxPointsPerRace", self.max_points_per_race)
        self._bind_spin("averagePointsPerRace", self.avg_points_per_race)

        form_points.addRow(self._label_for_key("maxPointsPerDrift"), self.max_points_per_drift)
        form_points.addRow(self._label_for_key("maxPointsPerRace"), self.max_points_per_race)
        form_points.addRow(self._label_for_key("averagePointsPerRace"), self.avg_points_per_race)

        row.addWidget(grp_play, 2)
        row.addWidget(grp_cups, 1)
        row.addWidget(grp_points, 1)
        root.addLayout(row)

        # Bottom actions
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.btn_apply = QPushButton("Apply Stats to Extracted Save")
        self.btn_apply.clicked.connect(self._on_apply_clicked)

        # Auto-apply support: emit changed on any edit
        for _k, _b in self._bindings.items():
            try:
                _b.widget.valueChanged.connect(lambda _v=None: self.changed.emit())
            except Exception:
                pass

        btn_row.addWidget(self.btn_apply)
        root.addLayout(btn_row)

        self._refresh_duration()

    def _refresh_duration(self) -> None:
        try:
            secs = int(self.time_seconds.value())
        except Exception:
            secs = 0
        self.time_human.setText(self._seconds_to_duration(secs))

    # -------------------------
    # Data binding
    # -------------------------

    def load_from_found(self, found: Dict[str, Any]) -> None:
        """Load values from the dict produced by MainWindow scanning blocks."""
        for k, b in self._bindings.items():
            if k not in found:
                continue
            raw = found.get(k)
            # track original type to preserve write-back type (string vs int)
            b.original_type = type(raw)
            try:
                if isinstance(raw, str):
                    raw_s = raw.strip()
                    # most are integer-like strings
                    v = int(float(raw_s)) if any(c in raw_s for c in ".eE") else int(raw_s or 0)
                elif isinstance(raw, (int, float)):
                    v = int(raw)
                else:
                    # unknown -> best effort
                    v = int(raw)  # type: ignore[arg-type]
                b.widget.setValue(max(0, v))
            except Exception:
                # leave existing value
                pass

        self._refresh_duration()

    def get_updates(self) -> Dict[str, Any]:
        """Return the current updates dict without prompting."""
        return self._collect_updates()

    def _collect_updates(self) -> Dict[str, Any]:
        updates: Dict[str, Any] = {}
        for k, b in self._bindings.items():
            v_int = int(b.widget.value())
            # Preserve original type where practical.
            if b.original_type is str:
                updates[k] = str(v_int)
            else:
                updates[k] = v_int
        return updates

    def _on_apply_clicked(self) -> None:
        updates = self._collect_updates()
        if not updates:
            return
        # Small guard rail: confirm very large playtime changes.
        if int(updates.get("timeInGame", 0)) > 50_000_000:
            res = QMessageBox.question(
                self,
                "Large playtime",
                "timeInGame is very large. Apply anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                return

        self.applyRequested.emit(updates)

    # Public API used by MainWindow action buttons
    def request_apply(self) -> None:
        """Programmatically trigger Apply (same as clicking the tab's Apply button)."""
        self._on_apply_clicked()
