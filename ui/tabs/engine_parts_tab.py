from __future__ import annotations

import json
import copy
import os
import tempfile
import fnmatch
import traceback
from dataclasses import dataclass
from pathlib import Path

from core.app_paths import get_writable_data_dir
from core.fs_atomic import atomic_write_text
from typing import Any, Dict, Optional, Tuple, List, Set

from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem,
    QMessageBox, QPlainTextEdit, QSplitter, QLineEdit, QToolButton, QSizePolicy,
    QCheckBox, QInputDialog, QGroupBox, QFormLayout, QAbstractItemView, QComboBox
)

from core.id_database import IdDatabase
from core.tunes_db import TunesDb
from core.json_ops import read_text_any, try_load_json, dump_json_compact, write_text_utf16le
from core.json_ops import json_path_get, json_path_set


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically write a small text file (DB/log) to disk."""
    atomic_write_text(path, text, encoding=encoding)


def _parse_jsonish(text: str) -> Any:
    """
    Parse user input into a JSON-compatible value.

    Accepts JSON literals plus common Python literals:
      True/False/None => true/false/null
    """
    s = (text or "").strip()
    if s == "":
        return ""
    # Normalize common Python literals
    lowered = s
    # Replace only whole-token occurrences (simple, effective for dialog edits)
    if lowered in ("True", "False", "None"):
        lowered = {"True": "true", "False": "false", "None": "null"}[lowered]
    # Also allow lowercase python-ish
    if lowered in ("true", "false", "null"):
        return json.loads(lowered)
    # If it looks like a number, try int/float
    try:
        if re.match(r"^[+-]?\d+$", s):
            return int(s)
        if re.match(r"^[+-]?\d+\.\d+$", s):
            return float(s)
    except Exception:
        pass
    # Try JSON
    try:
        return json.loads(s)
    except Exception:
        # Treat as raw string (no quotes required)
        return s


import re  # placed after helpers to keep file compact


@dataclass
class _KeyRow:
    key: str
    label: str
    in_save: bool



@dataclass(frozen=True)
class SwapKey:
    raw: str
    car_id: str
    tune_id: str
    engine_token: str

    @property
    def engine_part_key(self) -> str:
        return f"engine_part_{self.engine_token}"
_RE_CAR_TUNE_SWAP = re.compile(r"^(?P<car>\d+)_(?P<tune>\d+)_swap_(?P<engine>[A-Za-z0-9]+)$")

def parse_car_tune_swap(key: str) -> Optional[SwapKey]:
    m = _RE_CAR_TUNE_SWAP.match(key)
    if not m:
        return None
    return SwapKey(raw=key, car_id=m['car'], tune_id=m['tune'], engine_token=m['engine'])

def format_car_tune_swap(car_id: str, tune_id: str, engine_part_key_or_token: str) -> str:
    car_id = str(car_id).strip()
    tune_id = str(tune_id).strip()
    tok = str(engine_part_key_or_token).strip()
    if tok.startswith('engine_part_'):
        tok = tok[len('engine_part_'):]
    return f"{car_id}_{tune_id}_swap_{tok}"

class EnginePartsTab(QWidget):
    """
    Engine parts editor for the m_items dictionary.

    Two concepts:
    - "In save": engine_part_* entries observed in the CURRENT extracted save.
    - "Known": engine_part_* keys accumulated in data/engine_parts_db.json across saves.

    This fixes the "parts disappear when swapping saves" symptom by showing the
    KNOWN database list by default (while still indicating which are present in
    the currently loaded save).
    """

    def __init__(self, parent=None, *, id_db: Optional[IdDatabase] = None, tune_db: Optional[TunesDb] = None):
        super().__init__(parent)
        self.extracted_dir: Optional[Path] = None
        self._current_path: Optional[Path] = None
        self._current_obj: Optional[Any] = None
        self._id_db = id_db
        self._tune_db = tune_db
        if self._tune_db is None:
            try:
                project_root = Path(__file__).resolve().parents[2]
                self._tune_db = TunesDb(project_root)
            except Exception:
                self._tune_db = None
        self._m_items_path: Optional[str] = None
        self._m_items: Optional[Dict[str, Any]] = None

        self._known_engine_parts: Dict[str, Dict[str, Any]] = {}
        # Cache for suppressing redundant reloads/log spam when multiple refreshes
        # happen during a single user action (e.g., Extract + Load Values).
        self._db_cache_path: Optional[Path] = None
        self._db_cache_mtime_ns: Optional[int] = None
        self._db_cache_loaded: bool = False
        self._in_save_engine_parts: Set[str] = set()
        self._swap_keys: Dict[str, SwapKey] = {}
        self._other_keys: List[str] = []
        self._selected_swap_key: Optional[str] = None
        self._unlocked_car_ids: List[str] = []

        lay = QVBoxLayout(self)

        # Top controls
        top = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        top.addWidget(self.btn_refresh)

        self.chk_only_engine_parts = QCheckBox("Only engine_part_*")
        self.chk_only_engine_parts.setChecked(True)
        self.chk_only_engine_parts.toggled.connect(lambda _=False: self.refresh())
        top.addWidget(self.chk_only_engine_parts)

        top.addSpacing(10)
        top.addWidget(QLabel("Search:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by ID or name…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        top.addWidget(self.filter_edit, 1)

        self.lbl_count = QLabel("0")
        self.lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_count.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        top.addWidget(self.lbl_count)
        lay.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.list_parts = QListWidget()
        self.list_parts.currentItemChanged.connect(self._on_selected)
        splitter.addWidget(self.list_parts)

        right = QWidget()
        right_lay = QVBoxLayout(right)

        self.lbl_title = QLabel("Select a part")
        f = QFont()
        f.setPointSize(f.pointSize() + 3)
        f.setBold(True)
        self.lbl_title.setFont(f)
        right_lay.addWidget(self.lbl_title)

        self.lbl_subtitle = QLabel("")
        self.lbl_subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right_lay.addWidget(self.lbl_subtitle)

        bar = QHBoxLayout()
        bar.addStretch(1)

        # Add-to-save actions (uses persistent DB as a catalog)
        self.btn_add = QToolButton()
        self.btn_add.setText("Add to save")
        self.btn_add.setToolTip("Insert the selected engine_part_* into the current save's m_items")
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self._add_selected_to_save)
        bar.addWidget(self.btn_add)

        self.btn_add_all = QToolButton()
        self.btn_add_all.setText("Add missing")
        self.btn_add_all.setToolTip("Insert all known engine_part_* entries missing from the current save")
        self.btn_add_all.setEnabled(False)
        self.btn_add_all.clicked.connect(self._add_all_missing_to_save)
        bar.addWidget(self.btn_add_all)

        self.btn_copy = QToolButton()
        self.btn_copy.setText("Copy key")
        self.btn_copy.clicked.connect(self._copy_selected_key)
        bar.addWidget(self.btn_copy)
        self.chk_show_raw = QCheckBox("Raw JSON")
        self.chk_show_raw.setToolTip("Show/hide the raw JSON for the selected entry")
        self.chk_show_raw.setChecked(False)
        bar.addWidget(self.chk_show_raw)
        right_lay.addLayout(bar)

        # Swap/Tune editor (for keys like CAR_TUNE_swap_ENGINE)
        self.swap_box = QGroupBox('Car / Tune / Engine Swap')
        self.swap_box.setVisible(False)
        swap_form = QFormLayout(self.swap_box)

        self.cmb_swap_car = QComboBox()
        self.cmb_swap_car.setEditable(True)
        self.cmb_swap_tune = QComboBox()
        self.cmb_swap_tune.setEditable(True)
        self.cmb_swap_engine = QComboBox()
        self.cmb_swap_engine.setEditable(True)

        btn_row = QHBoxLayout()
        self.btn_swap_save = QPushButton('Save mapping')
        self.btn_swap_create = QPushButton('Create mapping')
        self.btn_swap_delete = QPushButton('Delete mapping')
        btn_row.addWidget(self.btn_swap_save)
        btn_row.addWidget(self.btn_swap_create)
        btn_row.addWidget(self.btn_swap_delete)

        swap_form.addRow('Car ID', self.cmb_swap_car)
        swap_form.addRow('Tune ID', self.cmb_swap_tune)
        swap_form.addRow('Engine', self.cmb_swap_engine)
        swap_form.addRow(btn_row)

        right_lay.addWidget(self.swap_box)

        # Wiring (blocker used when setting values programmatically; QComboBox emits current*Changed even then)
        self.cmb_swap_car.currentTextChanged.connect(self._on_swap_car_changed)
        self.btn_swap_save.clicked.connect(self._on_swap_save_clicked)
        self.btn_swap_create.clicked.connect(self._on_swap_create_clicked)
        self.btn_swap_delete.clicked.connect(self._on_swap_delete_clicked)


        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Key / Path", "Value"])
        self.tree.itemDoubleClicked.connect(self._on_edit)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.tree.itemChanged.connect(self._on_tree_item_changed)
        right_lay.addWidget(self.tree, 2)

        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        # Hidden by default to avoid duplicating the same information as the tree view
        self.raw.setVisible(False)
        try:
            self.chk_show_raw.toggled.connect(self.raw.setVisible)
        except Exception:
            pass
        right_lay.addWidget(self.raw, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        lay.addWidget(splitter, 1)

        # Load known DB once
        self._reload_engine_parts_db()

    

    def _label_key(self, key: str) -> str:
        """Best-effort label lookup for a key/id.

        - For engine_part_* keys: prefer IdDatabase.key_labels when present.
        - For numeric car ids: prefer IdDatabase.cars labels when available.
        - Otherwise: fall back to the raw string.
        """
        s = str(key)
        try:
            if self._id_db is not None:
                if s.isdigit():
                    # Car label (e.g. "Car 142" or user-defined name)
                    return self._id_db.label_car(s)
                lbl = (self._id_db.key_labels or {}).get(s)
                if lbl:
                    return str(lbl)
                return self._id_db.label_key(s)
        except Exception:
            pass
        return s
    def _log(self, s: str) -> None:
        """Write a message to the main window log if available."""
        try:
            p = self.parent()
            fn = getattr(p, "_msg", None)
            if callable(fn):
                fn(s)
                return
        except Exception:
            pass
        # Fallback
        try:
            print(s)
        except Exception:
            pass

# ----------------------
    # Context / loading
    # ----------------------

    def set_context(self, extracted_dir: Optional[Path]) -> None:
        self.extracted_dir = extracted_dir

    def refresh_from_workdir(self, work_dir: Path) -> None:
        """Compatibility hook used by MainWindow/ActionsMixin after extraction."""
        self.set_context(work_dir)
        self.refresh()

    def _find_best_m_items_block(self) -> Tuple[Optional[Path], Optional[Any]]:
        """Locate the most relevant extracted block containing an ``m_items`` dict.

        CarX saves often contain multiple JSON blocks. Some blocks may include an
        ``m_items`` dict, but only one of them is typically the one users expect
        to edit (the one that actually contains the engine_part_* entries).

        We score candidates by the number of engine_part_* keys, then by total
        size of ``m_items``. This makes the selection deterministic and stable.
        """
        if not self.extracted_dir:
            return None, None

        blocks_dir = Path(self.extracted_dir) / "blocks"
        if not blocks_dir.exists() or not blocks_dir.is_dir():
            return None, None

        best_path: Optional[Path] = None
        best_obj: Optional[Any] = None
        best_score: Tuple[int, int] = (-1, -1)  # (engine_part_count, m_items_size)

        for p in sorted(blocks_dir.glob("*.json")):
            try:
                text = read_text_any(p)
                obj = try_load_json(text)
            except Exception:
                continue

            if obj is None:
                continue

            found: List[Dict[str, Any]] = []

            def walk(x: Any) -> None:
                if isinstance(x, dict):
                    mi = x.get("m_items")
                    if isinstance(mi, dict):
                        found.append(mi)
                    for v in x.values():
                        walk(v)
                elif isinstance(x, list):
                    for v in x:
                        walk(v)

            walk(obj)

            for mi in found:
                try:
                    ep_count = sum(1 for k in mi.keys() if str(k).startswith("engine_part_"))
                    mi_size = len(mi)
                    score = (ep_count, mi_size)
                    if score > best_score:
                        best_score = score
                        best_path = p
                        best_obj = obj
                except Exception:
                    continue

        return best_path, best_obj

    def _engine_db_path(self) -> Optional[Path]:
        """Return the persistent Engine Parts DB path.

        Uses the application's stable data directory (per-user AppData by default,
        or <project>/data in portable mode). This must NOT vary per save folder.
        """
        try:
            # Prefer MainWindow.data_dir when available
            mw = self.window()
            if mw is not None and hasattr(mw, "data_dir"):
                data_dir = Path(getattr(mw, "data_dir"))
                data_dir.mkdir(parents=True, exist_ok=True)
                return data_dir / "engine_parts_db.json"
        except Exception:
            pass

        try:
            base_dir = Path(__file__).resolve().parents[2]
            data_dir = get_writable_data_dir(base_dir)
            return data_dir / "engine_parts_db.json"
        except Exception:
            return None
    def _reload_engine_parts_db(self) -> None:
        p = self._engine_db_path()
        if not p:
            return
        if not p.exists():
            # Nothing persisted yet
            return

        # Suppress redundant reloads when the file hasn't changed.
        try:
            st = p.stat()
            mtime_ns = getattr(st, "st_mtime_ns", None)
            if mtime_ns is None:
                mtime_ns = int(st.st_mtime * 1_000_000_000)
            if (
                self._db_cache_loaded
                and self._db_cache_path == p
                and self._db_cache_mtime_ns == mtime_ns
            ):
                return
        except Exception:
            # If stat fails, fall through to best-effort reload.
            mtime_ns = None

        self._known_engine_parts = {}
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            ep = obj.get("engine_parts")
            if not isinstance(ep, dict):
                return

            out: Dict[str, Dict[str, Any]] = {}
            for k, v in ep.items():
                ks = str(k).strip()
                if not ks:
                    continue
                if isinstance(v, dict):
                    out[ks] = v
                else:
                    out[ks] = {"label": str(v)}
            self._known_engine_parts = out

            self._log(f"[EnginePartsDb] Loaded {len(self._known_engine_parts)} parts from {p}")
        except Exception:
            # Do not crash UI if DB is malformed, but make it visible in log
            self._known_engine_parts = {}
            try:
                import traceback
                self._log("[EnginePartsDb] Failed to read engine_parts_db.json:\n" + traceback.format_exc())
            except Exception:
                pass
        finally:
            try:
                self._db_cache_path = p
                self._db_cache_mtime_ns = mtime_ns
                self._db_cache_loaded = True
            except Exception:
                pass
    def _observe_engine_parts(self, m_items: Dict[str, Any]) -> None:
        """Merge current-save engine_part_* entries into the persistent DB.

        This is **merge-only**: we never delete existing DB entries when swapping saves.
        We also store a *compact* JSON-serializable sample to avoid write failures.
        """
        p = self._engine_db_path()
        if not p:
            return

        existing: Dict[str, Any] = {}
        if p.exists():
            try:
                existing = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                existing = {}

        ep = existing.get("engine_parts")
        if not isinstance(ep, dict):
            ep = {}

        # Only persist when something material changes. The editor previously
        # wrote/reloaded the DB on every refresh, which made it look like the DB
        # was "loading multiple times" during a single save load.
        changed = False

        def _make_sample(v: Any) -> Any:
            # Prefer a small dict of scalar values so JSON saving cannot fail.
            if isinstance(v, dict):
                sample: Dict[str, Any] = {}
                preferred = ["id", "count", "permanent", "level", "lvl", "rarity", "quality"]
                for kk in preferred:
                    if kk in v and len(sample) < 8:
                        vv = v.get(kk)
                        if isinstance(vv, (str, int, float, bool)) or vv is None:
                            sample[kk] = vv
                        else:
                            sample[kk] = str(vv)
                # If still empty, take first few scalar-ish fields
                if not sample:
                    for kk, vv in list(v.items())[:8]:
                        if isinstance(vv, (str, int, float, bool)) or vv is None:
                            sample[str(kk)] = vv
                        else:
                            sample[str(kk)] = str(vv)
                return sample
            # Scalars are fine; otherwise stringify
            if isinstance(v, (str, int, float, bool)) or v is None:
                return v
            return str(v)

        added = 0
        for k, v in m_items.items():
            ks = str(k).strip()
            if not ks.startswith("engine_part_"):
                continue

            key_changed = False

            if ks not in ep:
                ep[ks] = {}
                added += 1
                key_changed = True

            rec = ep.get(ks)
            if not isinstance(rec, dict):
                rec = {}
                ep[ks] = rec

            # Label from IdDatabase if available
            lbl = self._label_key(ks)
            if lbl and lbl != ks:
                if rec.get("label") != lbl:
                    rec["label"] = lbl
                    key_changed = True

            # Compact sample (only update if it actually changed)
            sample = _make_sample(v)
            if rec.get("sample") != sample:
                rec["sample"] = sample
                key_changed = True

            # Seen counters (only when we persisted something for this key)
            if key_changed:
                try:
                    rec["seen_count"] = int(rec.get("seen_count") or 0) + 1
                except Exception:
                    rec["seen_count"] = 1

            if key_changed:
                changed = True

        if not changed:
            # No-op: avoid re-writing/re-loading the DB on every refresh.
            return

        existing["engine_parts"] = ep
        if added:
            existing["added_count_last_observation"] = added

        # Timestamp
        try:
            from datetime import datetime, timezone
            existing["updated_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        except Exception:
            pass

        # Atomic write
        try:
            text_out = json.dumps(existing, indent=2, ensure_ascii=False)
            _atomic_write_text(p, text_out, encoding="utf-8")
            self._log(f"[EnginePartsDb] Saved {len(ep)} known parts (+{added}) -> {p}")
        except Exception:
            import traceback
            self._log("[EnginePartsDb] Failed to write engine_parts_db.json:\n" + traceback.format_exc())

        # Reload in-memory cache
        self._reload_engine_parts_db()
    def refresh(self) -> None:
        # Always reload DB (so swapping saves does not "lose" known keys)
        self._reload_engine_parts_db()

        self.list_parts.clear()
        self.tree.clear()
        self.raw.clear()
        self._current_path = None
        self._current_obj = None
        self._m_items_path = None
        self._m_items = None
        self._in_save_engine_parts = set()
        try:
            self.btn_add.setEnabled(False)
            self.btn_add_all.setEnabled(False)
        except Exception:
            pass

        self.lbl_title.setText("Select a part")
        self.lbl_subtitle.setText("")

        # Attempt to locate m_items in the current extracted save (if any)
        p, obj = self._find_best_m_items_block()
        if p is None or obj is None:
            # No extracted save loaded; still show known DB if requested
            self._populate_list_from_db_or_empty()
            return

        # Find path + dict
        m_items = None
        m_path = None

        def walk(x: Any, path: str) -> None:
            nonlocal m_items, m_path
            if m_items is not None:
                return
            if isinstance(x, dict):
                if "m_items" in x and isinstance(x["m_items"], dict):
                    m_items = x["m_items"]
                    m_path = f"{path}.m_items" if path != "$" else "$.m_items"
                    return
                for k, v in x.items():
                    walk(v, f"{path}.{k}" if path != "$" else f"$.{k}")
            elif isinstance(x, list):
                for i, v in enumerate(x):
                    walk(v, f"{path}[{i}]")

        walk(obj, "$")

        if not isinstance(m_items, dict) or not m_path:
            self.raw.setPlainText("m_items found but is not a dict.")
            self._populate_list_from_db_or_empty()
            return

        self._current_path = p
        self._current_obj = obj
        self._m_items_path = m_path
        self._m_items = m_items

        # Record in-save engine parts and update DB (merge-only)
        for k in m_items.keys():
            ks = str(k)
            if ks.startswith("engine_part_"):
                self._in_save_engine_parts.add(ks)

        self._observe_engine_parts(m_items)
        # Record swap/tune keys for this save and update Tunes DB (merge-only)
        self._swap_keys = {}
        self._other_keys = []
        if isinstance(m_items, dict):
            for k in m_items.keys():
                ks = str(k)
                sk = parse_car_tune_swap(ks)
                if sk is not None:
                    self._swap_keys[ks] = sk
                    try:
                        if self._tune_db is not None:
                            self._tune_db.observe(sk.car_id, sk.tune_id)
                    except Exception:
                        pass
                elif not ks.startswith('engine_part_'):
                    self._other_keys.append(ks)
        try:
            if self._tune_db is not None:
                self._tune_db.save()
        except Exception:
            pass


        
        # Pull car IDs from garage unlocks containers to drive Swap/Tune car dropdown
        try:
            self._unlocked_car_ids = self._scan_unlocked_car_ids()
        except Exception:
            self._unlocked_car_ids = []
# Populate list and header
        self._populate_list(p_name=p.name, m_path=m_path)

    def _populate_list_from_db_or_empty(self) -> None:
        if self.chk_only_engine_parts.isChecked() and self._known_engine_parts:
            self._populate_list(p_name="", m_path="")
            return
        self.lbl_count.setText("0")
        self.raw.setPlainText("m_items not found in any extracted block.")
        return

    def _populate_list(self, *, p_name: str, m_path: str) -> None:
        """Populate the left list.

        - If 'Only engine_part_*' is checked: show the persistent engine-part catalog (DB-driven),
          with items styled as "in save" vs "known only".
        - If unchecked: show *sections* in one list:
            ENGINE PARTS / SWAPS & TUNES / OTHER ITEMS
          This aligns with how CarX stores m_items: engine catalog + per-car tune swap keys + misc.
        """
        self.list_parts.clear()

        m_items = self._m_items if isinstance(self._m_items, dict) else {}
        keys_in_save = [str(k) for k in m_items.keys()]

        known_engine = sorted([str(k) for k in self._known_engine_parts.keys() if str(k).startswith('engine_part_')])
        in_save_engine = sorted([k for k in keys_in_save if k.startswith('engine_part_')])

        def add_header(title: str) -> None:
            it = QListWidgetItem(title)
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            f = it.font()
            try:
                f.setBold(True)
                it.setFont(f)
            except Exception:
                pass
            self.list_parts.addItem(it)

        def add_row(kind: str, key: str, text: str, *, present: bool = True) -> None:
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, {'kind': kind, 'key': key})
            if not present:
                # Visual hint: known-but-not-present
                try:
                    f = it.font()
                    f.setItalic(True)
                    it.setFont(f)
                except Exception:
                    pass
            self.list_parts.addItem(it)

        if self.chk_only_engine_parts.isChecked():
            # Catalog view: show union of (known DB) and (currently in save).
            # This prevents the "Only engine_part_* shows nothing" symptom when the DB was moved,
            # or when the user hasn't observed parts yet.
            engine_keys = sorted(set(known_engine) | set(in_save_engine))
            for k in engine_keys:
                label = self._known_engine_parts.get(k, {}).get('label') or self._label_key(k)
                present = (k in self._in_save_engine_parts)
                txt = f"{k} — {label}" if label and label != k else k
                add_row('engine', k, txt, present=present)
            self.lbl_count.setText(str(len(engine_keys)))
            return

        # Sectioned view
        add_header('ENGINE PARTS')
        for k in in_save_engine:
            label = self._known_engine_parts.get(k, {}).get('label') or self._label_key(k)
            txt = f"{k} — {label}" if label and label != k else k
            add_row('engine', k, txt, present=True)

        missing_engine = [k for k in known_engine if k not in in_save_engine]
        if missing_engine:
            add_header('ENGINE PARTS (KNOWN, NOT IN SAVE)')
            for k in missing_engine:
                label = self._known_engine_parts.get(k, {}).get('label') or self._label_key(k)
                txt = f"{k} — {label}" if label and label != k else k
                add_row('engine', k, txt, present=False)

        add_header('SWAPS & TUNES')
        swap_items = list(self._swap_keys.items()) if isinstance(self._swap_keys, dict) else []
        def _swap_sort(kv):
            sk = kv[1]
            try:
                return (int(sk.car_id), int(sk.tune_id), sk.engine_token)
            except Exception:
                return (sk.car_id, sk.tune_id, sk.engine_token)
        for raw_key, sk in sorted(swap_items, key=_swap_sort):
            car_label = self._id_db.label_car(sk.car_id) if self._id_db else sk.car_id
            tune_name = ''
            try:
                tune_name = self._tune_db.get_name(sk.tune_id) if self._tune_db is not None else ''
            except Exception:
                tune_name = ''
            tune_disp = f"{sk.tune_id}{' — ' + tune_name if tune_name else ''}"
            eng_disp = sk.engine_part_key
            txt = f"Car {sk.car_id} ({car_label}) | Tune {tune_disp} | Swap {eng_disp}"
            add_row('swap', raw_key, txt, present=True)

        add_header('OTHER ITEMS')
        for k in sorted(self._other_keys or [], key=lambda s: str(s)):
            add_row('other', k, k, present=True)

        self.lbl_count.setText(str(self.list_parts.count()))

        # Apply filter after rebuilding
        try:
            self._apply_filter(self.filter_edit.text())
        except Exception:
            pass
    def _apply_filter(self, text: str) -> None:
        q_raw = (text or '').strip()
        q = q_raw.lower()

        # If the user uses shell-style wildcards (* ? []), honor them.
        use_wildcard = any(ch in q_raw for ch in ('*', '?', '[', ']'))
        pat = q.lower() if use_wildcard else ''

        for i in range(self.list_parts.count()):
            it = self.list_parts.item(i)

            # Section headers: hide while filtering to reduce noise.
            try:
                if not bool(it.flags() & Qt.ItemFlag.ItemIsEnabled):
                    it.setHidden(bool(q))
                    continue
            except Exception:
                pass

            data = it.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                key = str(data.get('key') or '')
            else:
                key = str(data or '')
            hay_key = key.lower()
            hay_text = it.text().lower()

            if not q:
                it.setHidden(False)
                continue

            if use_wildcard:
                ok = fnmatch.fnmatchcase(hay_key, pat) or fnmatch.fnmatchcase(hay_text, pat)
                it.setHidden(not ok)
            else:
                it.setHidden(q not in hay_text)


    

    def _list_meta(self, item) -> tuple[str, str]:
        """Return (kind, key) from a QListWidgetItem's UserRole payload."""
        if item is None:
            return "", ""
        try:
            data = item.data(Qt.ItemDataRole.UserRole)
        except Exception:
            data = None
        if isinstance(data, dict):
            return str(data.get('kind') or ''), str(data.get('key') or '')
        return "", str(data or "")

    def _scan_unlocked_car_ids(self) -> List[str]:
        """Return car IDs discovered from the Garage Unlocks container(s).

        This is used to populate the Swap/Tune builder's Car ID dropdown even if no
        swap keys exist yet in the current save.

        We prefer `availableCars` (when present), otherwise fall back to `carIds`.
        """
        if not self.extracted_dir:
            return []
        blocks_dir = Path(self.extracted_dir) / "blocks"
        if not blocks_dir.exists():
            return []

        found_available: List[str] = []
        found_fallback: List[str] = []

        def walk_for_key(x: Any, key: str) -> Optional[list]:
            if isinstance(x, dict):
                if key in x and isinstance(x.get(key), list):
                    return x.get(key)
                for v in x.values():
                    r = walk_for_key(v, key)
                    if r is not None:
                        return r
            elif isinstance(x, list):
                for v in x:
                    r = walk_for_key(v, key)
                    if r is not None:
                        return r
            return None

        for p in sorted(blocks_dir.glob("*.json")):
            try:
                obj = try_load_json(read_text_any(p))
            except Exception:
                continue
            if obj is None:
                continue

            lst = walk_for_key(obj, "availableCars")
            if isinstance(lst, list) and lst:
                found_available.extend([str(v) for v in lst if str(v).strip() != ""])

            lst2 = walk_for_key(obj, "carIds")
            if isinstance(lst2, list) and lst2:
                found_fallback.extend([str(v) for v in lst2 if str(v).strip() != ""])

        # Deduplicate, preserve numeric ordering if possible
        cars = found_available or found_fallback
        cars = list(dict.fromkeys(cars))  # stable unique
        try:
            cars = sorted(cars, key=lambda x: int(x) if str(x).isdigit() else str(x))
        except Exception:
            pass
        return cars
# ----------------------
    # Swap/Tune editor helpers
    # ----------------------
    def _refresh_swap_editor_sources(self) -> None:
        """Populate car/tune/engine choices from DB + current save."""
        # Cars: union of observed swaps + garage unlocks + DBs
        cars_set: Set[str] = set(str(sk.car_id) for sk in (self._swap_keys or {}).values())
        # From garage unlocks (availableCars / carIds) so you can pick unlocked cars even if no swap keys exist yet
        for cid in (getattr(self, "_unlocked_car_ids", None) or []):
            cars_set.add(str(cid))
        # From IdDatabase (user-named cars)
        try:
            if self._id_db is not None:
                for cid in (self._id_db.cars or {}).keys():
                    cars_set.add(str(cid))
        except Exception:
            pass
        # From Tunes DB (cars observed in mappings across saves)
        try:
            if self._tune_db is not None:
                for cid in self._tune_db.all_cars():
                    cars_set.add(str(cid))
        except Exception:
            pass

        cars = sorted(list(cars_set), key=lambda x: int(x) if str(x).isdigit() else str(x))

        # Engines: show full engine_part_* keys (align with engine-parts DB)
        engines: List[str] = []
        for k in sorted([str(k) for k in self._known_engine_parts.keys() if str(k).startswith('engine_part_')]):
            engines.append(k)
        # Also include engines referenced by swaps in this save
        for sk in (self._swap_keys or {}).values():
            ep = sk.engine_part_key
            if ep not in engines:
                engines.append(ep)

        with QSignalBlocker(self.cmb_swap_car):
            self.cmb_swap_car.clear()
            self.cmb_swap_car.addItems([str(c) for c in cars])
        self._on_swap_car_changed(self.cmb_swap_car.currentText())

        with QSignalBlocker(self.cmb_swap_engine):
            self.cmb_swap_engine.clear()
            self.cmb_swap_engine.addItems([str(e) for e in engines])

    def _on_swap_car_changed(self, car_id: str) -> None:
        car_id = (car_id or '').strip()
        tunes: List[str] = []
        if self._tune_db is not None and car_id:
            try:
                tunes = self._tune_db.tunes_for_car(car_id)
            except Exception:
                tunes = []
        # Also include tunes observed in current save swaps for that car
        for sk in (self._swap_keys or {}).values():
            if sk.car_id == car_id and sk.tune_id not in tunes:
                tunes.append(sk.tune_id)
        try:
            tunes = sorted(tunes, key=lambda x: int(x) if str(x).isdigit() else str(x))
        except Exception:
            pass
        with QSignalBlocker(self.cmb_swap_tune):
            self.cmb_swap_tune.clear()
            self.cmb_swap_tune.addItems([str(t) for t in tunes])

    def _swap_builder_values(self) -> Tuple[str, str, str]:
        car = (self.cmb_swap_car.currentText() or '').strip()
        tune = (self.cmb_swap_tune.currentText() or '').strip()
        eng = (self.cmb_swap_engine.currentText() or '').strip()
        if not car.isdigit():
            raise ValueError('Car ID must be numeric')
        if not tune.isdigit():
            raise ValueError('Tune ID must be numeric')
        if not eng:
            raise ValueError('Engine must not be empty')
        return car, tune, eng

    def _on_swap_save_clicked(self) -> None:
        if not self._can_edit_save():
            QMessageBox.warning(self, 'No extracted save', 'Load/extract a save first.')
            return
        if not (self._m_items and isinstance(self._m_items, dict)):
            QMessageBox.warning(self, 'No m_items', 'm_items was not found in the extracted save.')
            return
        if not self._selected_swap_key:
            QMessageBox.warning(self, 'No selection', 'Select a swap key (CAR_TUNE_swap_ENGINE) first.')
            return
        try:
            car, tune, eng = self._swap_builder_values()
            new_key = format_car_tune_swap(car, tune, eng)
            old_key = self._selected_swap_key
            if new_key != old_key:
                if new_key in self._m_items:
                    raise ValueError(f'Key already exists: {new_key}')
                self._m_items[new_key] = self._m_items.pop(old_key)
                # Keep id field aligned if present
                try:
                    if isinstance(self._m_items[new_key], dict) and 'id' in self._m_items[new_key]:
                        self._m_items[new_key]['id'] = new_key
                except Exception:
                    pass
                self._selected_swap_key = new_key
            # Observe tune in DB
            if self._tune_db is not None:
                self._tune_db.observe(car, tune)
                self._tune_db.save()
            if not self._write_current_block():
                raise ValueError('Failed to write block')
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, 'Save mapping failed', str(e))

    def _on_swap_create_clicked(self) -> None:
        if not self._can_edit_save():
            QMessageBox.warning(self, 'No extracted save', 'Load/extract a save first.')
            return
        if not (self._m_items and isinstance(self._m_items, dict)):
            QMessageBox.warning(self, 'No m_items', 'm_items was not found in the extracted save.')
            return
        try:
            car, tune, eng = self._swap_builder_values()
            key = format_car_tune_swap(car, tune, eng)
            if key in self._m_items:
                raise ValueError('Mapping already exists in this save')
            # Clone an existing swap template if possible to preserve types
            tmpl = None
            for k, v in self._m_items.items():
                if parse_car_tune_swap(str(k)) is not None and isinstance(v, dict):
                    tmpl = dict(v)
                    break
            if tmpl is None:
                tmpl = {'id': key, 'count': '1', 'permanent': 'True'}
            tmpl['id'] = key
            self._m_items[key] = tmpl
            self._selected_swap_key = key
            if self._tune_db is not None:
                self._tune_db.observe(car, tune)
                self._tune_db.save()
            if not self._write_current_block():
                raise ValueError('Failed to write block')
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, 'Create mapping failed', str(e))

    def _on_swap_delete_clicked(self) -> None:
        if not self._can_edit_save():
            QMessageBox.warning(self, 'No extracted save', 'Load/extract a save first.')
            return
        if not (self._m_items and isinstance(self._m_items, dict)):
            QMessageBox.warning(self, 'No m_items', 'm_items was not found in the extracted save.')
            return
        if not self._selected_swap_key:
            QMessageBox.warning(self, 'No selection', 'Select a swap mapping first.')
            return
        k = self._selected_swap_key
        try:
            if k in self._m_items:
                del self._m_items[k]
            self._selected_swap_key = None
            if not self._write_current_block():
                raise ValueError('Failed to write block')
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, 'Delete mapping failed', str(e))

    def _on_selected(self, cur, prev) -> None:
        self._tree_populating = True
        try:
            self.tree.clear()
            self.raw.clear()
            self._selected_swap_key = None
            try:
                self.swap_box.setVisible(False)
            except Exception:
                pass

            if cur is None:
                return

            data = cur.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                kind = str(data.get('kind') or '')
                key = str(data.get('key') or '')
            else:
                kind = 'engine'
                key = str(data or '')

            if not key:
                return

            # Enable/disable engine-add buttons depending on selection
            try:
                can_edit = self._can_edit_save()
                in_save = key in self._in_save_engine_parts
                self.btn_add.setEnabled(bool(can_edit and (not in_save) and kind == 'engine' and key.startswith('engine_part_')))
                self.btn_add_all.setEnabled(bool(can_edit and self.chk_only_engine_parts.isChecked()))
            except Exception:
                pass

            # Title / subtitle
            if kind == 'swap':
                sk = self._swap_keys.get(key) if isinstance(self._swap_keys, dict) else None
                if sk:
                    self.lbl_title.setText(f"{sk.raw}")
                    self.lbl_subtitle.setText(f"Car {sk.car_id} | Tune {sk.tune_id} | Engine {sk.engine_part_key}")
                else:
                    self.lbl_title.setText(key)
                    self.lbl_subtitle.setText('Swap mapping')
            else:
                label = self._label_key(key)
                self.lbl_title.setText(label if label else key)
                self.lbl_subtitle.setText('In save' if (isinstance(self._m_items, dict) and key in self._m_items) else 'Known from database')

            # Resolve value to display
            val = None
            if kind in ('swap', 'other', 'engine') and isinstance(self._m_items, dict) and key in self._m_items:
                val = self._m_items.get(key)
            elif kind == 'engine':
                # Known-only engine parts: show DB sample
                rec = self._known_engine_parts.get(key, {})
                sample = rec.get('sample')
                if sample is None:
                    self.raw.setPlainText(f"{key}\n\nNot present in this save. Load a save that contains it to capture a sample.")
                else:
                    try:
                        self.raw.setPlainText(json.dumps(sample, ensure_ascii=False, indent=2)[:20000])
                    except Exception:
                        self.raw.setPlainText(str(sample)[:20000])
                return

            if kind == 'swap':
                # Show swap editor and populate fields
                try:
                    self.swap_box.setVisible(True)
                    self._refresh_swap_editor_sources()
                    sk = self._swap_keys.get(key) if isinstance(self._swap_keys, dict) else None
                    if sk:
                        self._selected_swap_key = sk.raw
                        with QSignalBlocker(self.cmb_swap_car):
                            self.cmb_swap_car.setCurrentText(sk.car_id)
                        # tunes depend on car
                        self._on_swap_car_changed(sk.car_id)
                        with QSignalBlocker(self.cmb_swap_tune):
                            self.cmb_swap_tune.setCurrentText(sk.tune_id)
                        with QSignalBlocker(self.cmb_swap_engine):
                            self.cmb_swap_engine.setCurrentText(sk.engine_part_key)
                except Exception:
                    self._log('[EngineParts] Swap editor populate failed:\n' + traceback.format_exc())

            if val is None:
                self.raw.setPlainText('Value not found in m_items.')
                return

            # Render value into tree for editing
            path = f"{self._m_items_path}.{key}" if self._m_items_path else f"$.{key}"
            root = QTreeWidgetItem([key, self._preview(val)])
            root.setData(0, Qt.ItemDataRole.UserRole, path)
            self.tree.addTopLevelItem(root)
            self._populate(root, val, path)
            root.setExpanded(True)

            try:
                self.raw.setPlainText(json.dumps(val, ensure_ascii=False, indent=2)[:20000])
            except Exception:
                self.raw.setPlainText(str(val)[:20000])

            # Enable add actions based on selection/save state
            try:
                can_edit = self._can_edit_save()
                self.btn_add.setEnabled(can_edit and key.startswith('engine_part_') and key not in self._in_save_engine_parts)
                known = [k for k in self._known_engine_parts.keys() if str(k).startswith('engine_part_')]
                missing = [k for k in known if k not in self._in_save_engine_parts]
                self.btn_add_all.setEnabled(can_edit and bool(missing))
            except Exception:
                pass

        finally:
            self._tree_populating = False
    def _can_edit_save(self) -> bool:
        return isinstance(self._m_items, dict) and self._current_path is not None and self._current_obj is not None

    def _mark_unsynced(self, reason: str) -> None:
        try:
            p = self.parent()
            fn = getattr(p, "mark_unsynced", None)
            if callable(fn):
                fn(reason)
        except Exception:
            pass

    def _write_current_block(self) -> bool:
        """Persist the currently loaded block JSON to disk."""
        if self._current_path is None or self._current_obj is None:
            return False
        try:
            out = json.dumps(self._current_obj, indent=2, ensure_ascii=False, default=str)
            _atomic_write_text(self._current_path, out, encoding="utf-16le")
            return True
        except Exception:
            self._log("[EngineParts] Failed to write block JSON:\n" + traceback.format_exc())
            return False

    def _make_entry_for_key(self, key: str) -> Dict[str, Any]:
        """Build a new engine_part_* entry matching the current save's schema."""
        # Prefer a template from the current save to preserve types (strings vs bool/int, extra fields, etc.)
        tmpl = None
        if isinstance(self._m_items, dict):
            for k, v in self._m_items.items():
                if str(k).startswith("engine_part_") and isinstance(v, dict):
                    tmpl = v
                    break

        # Fallback: sample stored in DB
        if tmpl is None:
            sample = self._known_engine_parts.get(str(key), {}).get("sample")
            if isinstance(sample, dict):
                tmpl = sample

        if tmpl is None:
            tmpl = {"id": key, "count": 1, "permanent": True}

        entry = copy.deepcopy(tmpl)

        # Ensure required fields
        entry["id"] = str(key)

        # Count default (preserve type)
        c = entry.get("count", 1)
        if isinstance(c, str):
            entry["count"] = "1"
        elif isinstance(c, (int, float)):
            entry["count"] = int(c)
        else:
            entry["count"] = 1

        # Permanent default (preserve type)
        p = entry.get("permanent", True)
        if isinstance(p, str):
            entry["permanent"] = "True"
        elif isinstance(p, bool):
            entry["permanent"] = True
        else:
            entry["permanent"] = True

        return entry

    def _add_part_key_to_save(self, key: str) -> bool:
        if not self._can_edit_save():
            return False
        if not isinstance(self._m_items, dict):
            return False

        ks = str(key)
        if ks in self._m_items:
            return True  # already present

        entry = self._make_entry_for_key(ks)
        self._m_items[ks] = entry
        self._in_save_engine_parts.add(ks)

        # Persist + update DB
        ok = self._write_current_block()
        if ok:
            try:
                self._observe_engine_parts(self._m_items)
            except Exception:
                pass
            self._mark_unsynced(f"Added {ks}")
        return ok

    def _add_selected_to_save(self) -> None:
        cur = self.list_parts.currentItem()
        if cur is None:
            return
        kind, key = self._list_meta(cur)
        # only real part entries
        if not key or kind in ("", "header"):
            return
        if not self._can_edit_save():
            QMessageBox.information(self, "No extracted save", "Extract a save first so we can edit m_items.")
            return
        if not key.startswith("engine_part_"):
            QMessageBox.information(self, "Not an engine part", f"{key} is not an engine_part_* entry.")
            return
        if key in self._in_save_engine_parts:
            QMessageBox.information(self, "Already present", f"{key} is already present in this save.")
            return

        if self._add_part_key_to_save(key):
            # Refresh UI (list + selection)
            self._populate_list(p_name=self._current_path.name if self._current_path else "", m_path=self._m_items_path or "")
            self._select_key_in_list(key)

    def _add_all_missing_to_save(self) -> None:
        if not self._can_edit_save():
            QMessageBox.information(self, "No extracted save", "Extract a save first so we can edit m_items.")
            return

        known = [k for k in self._known_engine_parts.keys() if str(k).startswith("engine_part_")]
        missing = [k for k in known if k not in self._in_save_engine_parts]
        if not missing:
            QMessageBox.information(self, "Nothing to add", "All known engine_part_* entries are already present in this save.")
            return

        added = 0
        for k in sorted(missing):
            if self._add_part_key_to_save(k):
                added += 1

        self._populate_list(p_name=self._current_path.name if self._current_path else "", m_path=self._m_items_path or "")
        self._log(f"[EngineParts] Added {added} missing engine parts to current save.")
        QMessageBox.information(self, "Added", f"Added {added} engine parts to this save.")

    def _select_key_in_list(self, key: str) -> None:
        try:
            for i in range(self.list_parts.count()):
                it = self.list_parts.item(i)
                k_kind, k_key = self._list_meta(it)
                if str(k_key) == str(key):
                    self.list_parts.setCurrentRow(i)
                    return
        except Exception:
            pass



    def _copy_selected_key(self) -> None:
        try:
            from PyQt6.QtGui import QGuiApplication
            item = self.list_parts.currentItem()
            if not item:
                return
            key = item.data(Qt.ItemDataRole.UserRole)
            QGuiApplication.clipboard().setText(str(key))
        except Exception:
            pass

    # ----------------------
    # Tree population
    # ----------------------

    def _preview(self, v: Any) -> str:
        if isinstance(v, dict):
            return f"{{...}} ({len(v)})"
        if isinstance(v, list):
            return f"[...] ({len(v)})"
        if v is None:
            return "null"
        s = str(v)
        if len(s) > 80:
            s = s[:77] + "…"
        return s

    def _populate(self, parent: QTreeWidgetItem, v: Any, path: str) -> None:
        """Populate the tree view.
    
        Leaf (scalar) nodes are editable inline (Value column). Complex nodes
        (dict/list) are containers only.
        """
        if isinstance(v, dict):
            for k in sorted(v.keys(), key=lambda s: str(s)):
                child_path = f"{path}.{k}"
                val = v[k]
                child = QTreeWidgetItem([str(k), self._preview(val)])
                child.setData(0, Qt.ItemDataRole.UserRole, child_path)
    
                # Make scalar leaves editable
                if not isinstance(val, (dict, list)):
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsEditable)
                    # Normalize count display if stored as bool
                    if str(k) == "count" and isinstance(val, bool):
                        child.setText(1, "1" if val else "0")
                    # Bool / bool-like strings become checkable
                    if str(k) != "count" and (isinstance(val, bool) or (isinstance(val, str) and val.lower() in ("true", "false"))):
                        child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        is_true = val if isinstance(val, bool) else (val.lower() == "true")
                        child.setCheckState(1, Qt.CheckState.Checked if is_true else Qt.CheckState.Unchecked)
                        child.setText(1, "True" if is_true else "False")
    
                parent.addChild(child)
                self._populate(child, val, child_path)
    
        elif isinstance(v, list):
            for i, item in enumerate(v):
                child_path = f"{path}[{i}]"
                child = QTreeWidgetItem([f"[{i}]", self._preview(item)])
                child.setData(0, Qt.ItemDataRole.UserRole, child_path)
    
                if not isinstance(item, (dict, list)):
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsEditable)
                    if isinstance(item, bool) or (isinstance(item, str) and item.lower() in ("true", "false")):
                        child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        is_true = item if isinstance(item, bool) else (item.lower() == "true")
                        child.setCheckState(1, Qt.CheckState.Checked if is_true else Qt.CheckState.Unchecked)
                        child.setText(1, "True" if is_true else "False")
    
                parent.addChild(child)
                self._populate(child, item, child_path)
    
    def _on_tree_item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        """Inline edit handler for the tree.
    
        Updates the underlying JSON in the current block file immediately.
        """
        if getattr(self, "_tree_populating", False):
            return
        if col != 1:
            return
        if self._current_obj is None or self._current_path is None:
            return
    
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path or path == "$":
            return
    
        try:
            old_val = json_path_get(self._current_obj, str(path))
        except Exception:
            return
    
        # Ignore container nodes
        if isinstance(old_val, (dict, list)):
            return
    

        # Special-case: engine-part 'count' should be numeric (string digits), not boolean.
        try:
            path_s = str(path)
            leaf = path_s.rsplit(".", 1)[-1] if "." in path_s else path_s
        except Exception:
            leaf = ""
        if leaf == "count":
            raw = str(item.text(1) or "").strip()
            raw_norm = raw.replace(",", "").replace("_", "").strip()
            # Keep only digits and optional leading minus
            if raw_norm.startswith("-"):
                sign = "-"
                digits = "".join(ch for ch in raw_norm[1:] if ch.isdigit())
                raw_norm = sign + digits
            else:
                raw_norm = "".join(ch for ch in raw_norm if ch.isdigit())
            if raw_norm == "" or raw_norm == "-":
                return
            from PyQt6.QtCore import QSignalBlocker
            with QSignalBlocker(self.tree):
                item.setText(1, raw_norm)
            old_norm = old_val
            if isinstance(old_norm, bool):
                old_norm = "1" if old_norm else "0"
            if str(old_norm) == raw_norm:
                return
            json_path_set(self._current_obj, str(path), raw_norm)
            write_text_utf16le(self._current_path, dump_json_compact(self._current_obj))
            self._mark_unsynced("Engine Parts")
            try:
                self.raw.setPlainText(json.dumps(json_path_get(self._current_obj, str(path)), ensure_ascii=False, indent=2)[:20000])
            except Exception:
                pass
            return
        try:
            # Checkbox path
            if bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                is_checked = (item.checkState(1) == Qt.CheckState.Checked)
                if isinstance(old_val, bool):
                    new_val = is_checked
                elif isinstance(old_val, str) and old_val.lower() in ("true", "false"):
                    new_val = "True" if is_checked else "False"
                else:
                    new_val = is_checked
                item.setText(1, "True" if is_checked else "False")
            else:
                raw = str(item.text(1) or "").strip()
                raw_norm = raw.replace(",", "").replace("_", "").strip()
    
                if isinstance(old_val, int):
                    new_val = int(raw_norm or "0")
                    item.setText(1, str(new_val))
                elif isinstance(old_val, float):
                    new_val = float(raw_norm or "0")
                    item.setText(1, str(new_val))
                elif isinstance(old_val, str):
                    if old_val.strip().lstrip("-").isdigit() and raw_norm.lstrip("-").isdigit():
                        new_val = raw_norm
                        item.setText(1, new_val)
                    elif old_val.lower() in ("true", "false") and raw.lower() in ("true", "false"):
                        new_val = "True" if raw.lower() == "true" else "False"
                        item.setText(1, new_val)
                    else:
                        new_val = raw
                else:
                    new_val = _parse_jsonish(raw)
    
            if new_val == old_val:
                return
    
            json_path_set(self._current_obj, str(path), new_val)
            write_text_utf16le(self._current_path, dump_json_compact(self._current_obj))
            self._mark_unsynced("Engine Parts")
    
            try:
                self.raw.setPlainText(json.dumps(json_path_get(self._current_obj, str(item.data(0, Qt.ItemDataRole.UserRole))), ensure_ascii=False, indent=2)[:20000])
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, "Write failed", str(e))
    

    # ----------------------
    # Editing
    # ----------------------

    def _on_edit(self, item: QTreeWidgetItem, col: int) -> None:
        if self._current_obj is None or self._current_path is None:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path or path == "$":
            return

        try:
            cur_val = json_path_get(self._current_obj, path)
        except Exception:
            return

        # Complex: edit JSON text
        if isinstance(cur_val, (dict, list)):
            txt = json.dumps(cur_val, ensure_ascii=False, indent=2)
            inp, ok = QInputDialog.getMultiLineText(self, "Edit JSON (object/array)", "JSON:", txt)
            if not ok:
                return
            try:
                new_val = json.loads(inp)
            except Exception:
                QMessageBox.warning(self, "Invalid JSON", "The value must be valid JSON for objects/arrays.")
                return
        else:
            # Primitive: accept JSON or python-ish literals; no need for quotes for strings
            inp, ok = QInputDialog.getText(
                self,
                "Edit value",
                'Enter a JSON/Python literal (e.g. 123, true/false/null, "text", True/False/None):',
                text=json.dumps(cur_val, ensure_ascii=False) if not isinstance(cur_val, str) else cur_val
            )
            if not ok:
                return
            new_val = _parse_jsonish(inp)

        try:
            json_path_set(self._current_obj, path, new_val)
            write_text_utf16le(self._current_path, dump_json_compact(self._current_obj))
            item.setText(1, self._preview(new_val))
            # Refresh raw preview
            try:
                self.raw.setPlainText(json.dumps(json_path_get(self._current_obj, self._m_items_path + "." + str(self.list_parts.currentItem().data(Qt.ItemDataRole.UserRole))), ensure_ascii=False, indent=2)[:20000])
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, "Write failed", str(e))