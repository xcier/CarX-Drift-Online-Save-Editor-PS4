from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.json_ops import (
    dump_json_compact,
    json_path_get,
    json_path_set,
    read_text_any,
    try_load_json,
    write_text_utf16le,
)


class BrowserMixin:
    """MainWindow mixin for the Data Browser tab.

    Provides a browsable list of extracted blocks and a JSON tree viewer.
    Double-clicking a primitive value edits it in-place and writes back.
    """

    # ---------------------------
    # Tab builder
    # ---------------------------

    def _build_browser_tab(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)

        top = QHBoxLayout()

        self.browser_refresh_btn = QPushButton("Refresh")
        self.browser_refresh_btn.clicked.connect(self._browser_refresh)

        self.browser_load_btn = QPushButton("Load values into forms")
        self.browser_load_btn.clicked.connect(self.on_load_values)

        self.browser_show_all = QCheckBox("Show all blocks (may be large)")
        self.browser_show_all.setChecked(False)
        self.browser_show_all.toggled.connect(self._browser_refresh)

        self.browser_rank = QCheckBox("Rank blocks by player keys")
        self.browser_rank.setChecked(True)
        self.browser_rank.toggled.connect(self._browser_refresh)

        self.browser_view_mode = QComboBox()
        self.browser_view_mode.addItems([
            "Tree (JSON)",
            "Pretty JSON",
            "Raw text",
            "Hex (binary preview)",
        ])
        self.browser_view_mode.currentIndexChanged.connect(self._browser_open_selected)

        top.addWidget(self.browser_refresh_btn)
        top.addWidget(self.browser_load_btn)
        top.addStretch(1)
        top.addWidget(self.browser_rank)
        top.addWidget(self.browser_show_all)
        top.addWidget(QLabel("View:"))
        top.addWidget(self.browser_view_mode)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.browser_list = QTreeWidget()
        self.browser_list.setHeaderLabels(["Block", "Score"])
        self.browser_list.setColumnWidth(0, 420)
        self.browser_list.itemSelectionChanged.connect(self._browser_open_selected)

        self.browser_json_tree = QTreeWidget()
        self.browser_json_tree.setHeaderLabels(["Key / Index", "Value preview"])
        self.browser_json_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.browser_json_tree.customContextMenuRequested.connect(self._on_json_tree_menu)
        self.browser_json_tree.itemDoubleClicked.connect(self._on_json_tree_double_clicked)
        self.browser_json_tree.itemSelectionChanged.connect(self._on_json_tree_selection_changed)

        # Search + quick editor panel (better for editing userdata)
        self.browser_find = QLineEdit()
        self.browser_find.setPlaceholderText("Find key/value… (filters tree)")
        self.browser_find.textChanged.connect(self._browser_apply_filter)

        self.browser_find_keys_only = QCheckBox("Keys only")
        self.browser_find_keys_only.setChecked(False)
        self.browser_find_keys_only.toggled.connect(self._browser_apply_filter)

        self.browser_find_auto_expand = QCheckBox("Auto-expand")
        self.browser_find_auto_expand.setChecked(True)
        self.browser_find_auto_expand.toggled.connect(self._browser_apply_filter)

        self.browser_path_label = QLabel("Path: —")
        self.browser_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.browser_value_editor = QPlainTextEdit()
        self.browser_value_editor.setPlaceholderText("Edit JSON literal here (e.g. 123, true, \"text\")")
        self.browser_value_editor.setFixedHeight(90)

        self.browser_apply_btn = QPushButton("Apply value")
        self.browser_apply_btn.clicked.connect(self._browser_apply_editor_value)

        self.browser_reset_btn = QPushButton("Reset")
        self.browser_reset_btn.clicked.connect(self._browser_reset_editor_value)

        self.browser_undo_btn = QPushButton("Undo last")
        self.browser_undo_btn.clicked.connect(self._browser_undo_last)

        self.browser_json_panel = QWidget()
        jv = QVBoxLayout(self.browser_json_panel)
        jv.setContentsMargins(0, 0, 0, 0)
        jv.setSpacing(8)

        find_row = QHBoxLayout()
        find_row.addWidget(QLabel("Find:"))
        find_row.addWidget(self.browser_find, 1)
        find_row.addWidget(self.browser_find_keys_only)
        find_row.addWidget(self.browser_find_auto_expand)
        jv.addLayout(find_row)

        jv.addWidget(self.browser_json_tree, 1)

        edit_row = QHBoxLayout()
        edit_row.addWidget(self.browser_path_label, 1)
        edit_row.addWidget(self.browser_undo_btn)
        edit_row.addWidget(self.browser_reset_btn)
        edit_row.addWidget(self.browser_apply_btn)
        jv.addLayout(edit_row)

        jv.addWidget(self.browser_value_editor)

        self.browser_text = QPlainTextEdit()
        self.browser_text.setReadOnly(True)

        self.browser_right = QStackedWidget()
        self.browser_right.addWidget(self.browser_json_panel)  # 0
        self.browser_right.addWidget(self.browser_text)        # 1

        splitter.addWidget(self.browser_list)
        splitter.addWidget(self.browser_right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        # Per-file original text + undo stack (session only)
        self._browser_original_text = {}
        self._browser_undo_stack = []  # (Path, json_path, old_val, new_val)
        self._browser_path_to_item = {}
        self._browser_selected_path = None

        root.addWidget(splitter, 1)

        self.browser_text.setPlainText("Run Extract first, then click Refresh to browse extracted blocks.")
        self.browser_right.setCurrentIndex(1)
        return w

    # ---------------------------
    # Ranking helpers
    # ---------------------------

    def _browser_player_keys(self) -> List[str]:
        return [
            "coins", "ratingPoints", "playerExp",
            "timeInGame", "racesPlayed", "driftRacesPlayed", "timeAttackRacesPlayed", "MPRacesPlayed",
            "maxPointsPerDrift", "maxPointsPerRace", "averagePointsPerRace",
            "cups1", "cups2", "cups3",
        ]

    def _find_keys_in_obj(self, obj: Any, keys: List[str]) -> set:
        keyset = set(keys)
        found = set()
        stack = [obj]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                for k, v in cur.items():
                    if k in keyset:
                        found.add(k)
                    stack.append(v)
            elif isinstance(cur, list):
                stack.extend(cur)
        return found

    # ---------------------------
    # Refresh/open
    # ---------------------------

    def _browser_refresh(self) -> None:
        if not hasattr(self, "browser_list"):
            return

        self.browser_list.clear()
        self.browser_json_tree.clear()

        if not self._ensure_extracted():
            return

        manifest_path = self.work_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            blocks = manifest.get("blocks", [])
        except Exception as e:
            self.browser_text.setPlainText(f"Failed to read manifest.json: {e}")
            self.browser_right.setCurrentIndex(1)
            return

        limit = None if self.browser_show_all.isChecked() else 20
        shown = blocks if limit is None else blocks[:limit]

        ranked = []
        keys = self._browser_player_keys()
        for b in shown:
            out_name = b.get("out_name", "")
            p = (self.work_dir / out_name) if out_name else None
            score = 0
            found_keys: List[str] = []

            if self.browser_rank.isChecked() and p and p.exists() and p.suffix.lower() == ".json":
                try:
                    txt = read_text_any(p)
                    obj = try_load_json(txt)
                    if obj is not None:
                        found = self._find_keys_in_obj(obj, keys)
                        found_keys = sorted(found)
                        score = len(found)
                except Exception:
                    pass
            ranked.append((score, found_keys, b))

        if self.browser_rank.isChecked():
            ranked.sort(key=lambda t: (t[0], t[2].get("index", -1)), reverse=True)

        for score, found_keys, b in ranked:
            idx = b.get("index", -1)
            out_name = b.get("out_name", "")
            kind = b.get("kind", "")
            note = b.get("note", "")
            label = f"{idx:03d}  {Path(out_name).name}  [{kind}]"
            if note:
                label += f"  – {note}"
            if found_keys:
                try:
                    pretty = [self.id_db.label_key(k) for k in found_keys]
                except Exception:
                    pretty = found_keys
                label += "  {" + ", ".join(pretty[:6]) + ("…" if len(pretty) > 6 else "") + "}"

            it = QTreeWidgetItem([label, str(score)])
            it.setData(0, Qt.ItemDataRole.UserRole, out_name)
            self.browser_list.addTopLevelItem(it)

        if self.browser_list.topLevelItemCount() == 0:
            self.browser_text.setPlainText("No blocks listed in manifest.json.")
            self.browser_right.setCurrentIndex(1)
        else:
            self.browser_list.setCurrentItem(self.browser_list.topLevelItem(0))

    def _browser_open_selected(self) -> None:
        if not hasattr(self, "browser_list"):
            return
        items = self.browser_list.selectedItems()
        if not items:
            return
        it = items[0]
        out_name = it.data(0, Qt.ItemDataRole.UserRole)
        if not out_name:
            return

        p = self.work_dir / out_name
        if not p.exists():
            self.browser_text.setPlainText(f"Missing file: {p}")
            self.browser_right.setCurrentIndex(1)
            return

        mode = self.browser_view_mode.currentText()
        try:
            if p.suffix.lower() == ".json":
                txt = read_text_any(p)
                obj = try_load_json(txt)

                if mode == "Raw text" or obj is None:
                    self.browser_text.setPlainText(txt)
                    self.browser_right.setCurrentIndex(1)
                    return

                if mode == "Pretty JSON":
                    self.browser_text.setPlainText(json.dumps(obj, indent=2, ensure_ascii=False))
                    self.browser_right.setCurrentIndex(1)
                    return

                # Tree (JSON)
                self.browser_json_tree.clear()
                self._browser_path_to_item = {}
                try:
                    if p not in self._browser_original_text:
                        self._browser_original_text[p] = txt
                except Exception:
                    pass
                root_item = QTreeWidgetItem(["$", ""])
                try:
                    self._browser_path_to_item["$"] = root_item
                except Exception:
                    pass
                root_item.setData(0, Qt.ItemDataRole.UserRole, "$")
                self.browser_json_tree.addTopLevelItem(root_item)
                self._browser_current_path = p
                self._browser_current_obj = obj
                self._populate_json_tree(root_item, obj, "$")
                root_item.setExpanded(True)
                self.browser_right.setCurrentIndex(0)
                return

            # Binary / other
            b = p.read_bytes()
            head = b[:4096]
            if mode == "Hex (binary preview)":
                hex_dump = " ".join(f"{x:02X}" for x in head)
                self.browser_text.setPlainText(
                    f"{p.name} (binary)\nSize: {len(b)} bytes\n\nFirst 4096 bytes (hex):\n{hex_dump}"
                )
            else:
                self.browser_text.setPlainText(
                    f"{p.name} (binary)\nSize: {len(b)} bytes\n\nSelect 'Hex (binary preview)' to view bytes."
                )
            self.browser_right.setCurrentIndex(1)
        except Exception as e:
            self.browser_text.setPlainText(f"Failed to open {p}: {e}")
            self.browser_right.setCurrentIndex(1)

    # ---------------------------
    # Tree population + editing
    # ---------------------------

    def _populate_json_tree(self, parent: QTreeWidgetItem, obj: Any, path: str) -> None:
        MAX_CHILDREN = 500

        CAR_ID_KEYS = {"carId", "lastCarId", "selectedCarId", "currentCarId"}
        TRACK_ID_KEYS = {"trackId", "lastTrackId", "selectedTrackId", "currentTrackId"}

        def _label_for_key(k: str, v: Any) -> str:
            try:
                if not hasattr(self, "id_db") or self.id_db is None:  # type: ignore[attr-defined]
                    return ""
                if k in CAR_ID_KEYS:
                    return str(self.id_db.label_car(v))
                if k in TRACK_ID_KEYS:
                    return str(self.id_db.label_track(v))
            except Exception:
                return ""
            return ""

        def preview(v: Any, *, key: str | None = None) -> str:
            if isinstance(v, (dict, list)):
                if isinstance(v, dict):
                    return f"{{...}} ({len(v)})"
                return f"[...] ({len(v)})"

            # If this looks like a car/track id field, append the friendly label.
            try:
                if key and isinstance(v, (int, str)):
                    lbl = _label_for_key(key, v)
                    if lbl and not lbl.startswith("Car ") and not lbl.startswith("Track "):
                        s = f"{v} — {lbl}"
                        return s if len(s) <= 120 else (s[:117] + "...")
                    if lbl and (lbl.startswith("Car ") or lbl.startswith("Track ")):
                        # Still show default label form for quick sanity.
                        s = f"{v} — {lbl}"
                        return s if len(s) <= 120 else (s[:117] + "...")
            except Exception:
                pass

            s = str(v)
            return s if len(s) <= 120 else (s[:117] + "...")

        if isinstance(obj, dict):
            for i, (k, v) in enumerate(obj.items()):
                if i >= MAX_CHILDREN:
                    QTreeWidgetItem(parent, ["…", f"truncated at {MAX_CHILDREN} children"]).setData(
                        0, Qt.ItemDataRole.UserRole, path
                    )
                    break
                child_path = f"{path}.{k}" if path != "$" else f"$.{k}"
                item = QTreeWidgetItem([str(k), preview(v, key=str(k))])
                item.setData(0, Qt.ItemDataRole.UserRole, child_path)
                try:
                    self._browser_path_to_item[str(child_path)] = item
                except Exception:
                    pass
                parent.addChild(item)
                if isinstance(v, (dict, list)):
                    self._populate_json_tree(item, v, child_path)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                if i >= MAX_CHILDREN:
                    QTreeWidgetItem(parent, ["…", f"truncated at {MAX_CHILDREN} children"]).setData(
                        0, Qt.ItemDataRole.UserRole, path
                    )
                    break
                child_path = f"{path}[{i}]"
                item = QTreeWidgetItem([f"[{i}]", preview(v)])
                item.setData(0, Qt.ItemDataRole.UserRole, child_path)
                try:
                    self._browser_path_to_item[str(child_path)] = item
                except Exception:
                    pass
                parent.addChild(item)
                if isinstance(v, (dict, list)):
                    self._populate_json_tree(item, v, child_path)

    # -------------------- Tree filtering + quick editor --------------------

    def _browser_apply_filter(self) -> None:
        try:
            needle = (self.browser_find.text() or "").strip().lower()
        except Exception:
            return

        keys_only = bool(getattr(self, "browser_find_keys_only", None) and self.browser_find_keys_only.isChecked())
        auto_expand = bool(getattr(self, "browser_find_auto_expand", None) and self.browser_find_auto_expand.isChecked())

        def item_text(it: QTreeWidgetItem) -> str:
            try:
                k = (it.text(0) or "").lower()
                v = (it.text(1) or "").lower()
                return k if keys_only else (k + " " + v)
            except Exception:
                return ""

        def recurse(it: QTreeWidgetItem) -> bool:
            matched = (needle in item_text(it)) if needle else True
            any_child = False
            try:
                for i in range(it.childCount()):
                    c = it.child(i)
                    any_child = recurse(c) or any_child
            except Exception:
                pass

            show = matched or any_child
            it.setHidden(not show)

            if auto_expand and needle and show and any_child:
                it.setExpanded(True)

            # Bold direct matches for visibility
            try:
                f = it.font(0)
                f.setBold(bool(needle and matched))
                it.setFont(0, f)
            except Exception:
                pass

            return show

        try:
            for i in range(self.browser_json_tree.topLevelItemCount()):
                recurse(self.browser_json_tree.topLevelItem(i))
        except Exception:
            pass

    def _on_json_tree_selection_changed(self) -> None:
        item = None
        try:
            item = self.browser_json_tree.currentItem()
        except Exception:
            item = None

        if not item:
            self._browser_selected_path = None
            self.browser_path_label.setText("Path: —")
            self.browser_value_editor.setPlainText("")
            self.browser_apply_btn.setEnabled(False)
            self.browser_reset_btn.setEnabled(False)
            return

        path = None
        try:
            path = item.data(0, Qt.ItemDataRole.UserRole)
        except Exception:
            path = None

        self._browser_selected_path = path
        self.browser_path_label.setText(f"Path: {path or '—'}")

        obj = getattr(self, "_browser_current_obj", None)
        if obj is None or not path or path == "$":
            self.browser_value_editor.setPlainText("")
            self.browser_apply_btn.setEnabled(False)
            self.browser_reset_btn.setEnabled(False)
            return

        try:
            cur_val = json_path_get(obj, path)
        except Exception:
            cur_val = None

        if isinstance(cur_val, (dict, list)):
            self.browser_value_editor.setPlainText("")
            self.browser_apply_btn.setEnabled(False)
            self.browser_reset_btn.setEnabled(False)
            return

        try:
            self.browser_value_editor.setPlainText(json.dumps(cur_val, ensure_ascii=False))
        except Exception:
            self.browser_value_editor.setPlainText(str(cur_val))

        self.browser_apply_btn.setEnabled(True)
        self.browser_reset_btn.setEnabled(True)

    def _browser_reset_editor_value(self) -> None:
        self._on_json_tree_selection_changed()

    def _browser_apply_editor_value(self) -> None:
        path = getattr(self, "_browser_selected_path", None)
        if not path or path == "$":
            return

        obj = getattr(self, "_browser_current_obj", None)
        p = getattr(self, "_browser_current_path", None)
        if obj is None or p is None:
            return

        try:
            old_val = json_path_get(obj, path)
        except Exception:
            return

        if isinstance(old_val, (dict, list)):
            return

        new_txt = (self.browser_value_editor.toPlainText() or "").strip()
        if not new_txt:
            new_val = ""
        else:
            try:
                new_val = json.loads(new_txt)
            except Exception:
                new_val = new_txt

        try:
            if p not in self._browser_original_text:
                try:
                    self._browser_original_text[p] = read_text_any(p)
                except Exception:
                    pass

            json_path_set(obj, path, new_val)
            write_text_utf16le(p, dump_json_compact(obj))

            try:
                self._browser_undo_stack.append((p, path, old_val, new_val))
            except Exception:
                pass

            try:
                self.mark_unsynced("Data Browser")
            except Exception:
                pass

            self._browser_open_selected()
            self._browser_select_path(path)

            try:
                self._msg(f"[Browser] Updated {path} in {p.name}")
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, "Write failed", str(e))

    def _browser_undo_last(self) -> None:
        if not getattr(self, "_browser_undo_stack", None):
            return
        try:
            p, path, old_val, _new_val = self._browser_undo_stack.pop()
        except Exception:
            return

        obj = getattr(self, "_browser_current_obj", None)
        cur_p = getattr(self, "_browser_current_path", None)
        if obj is None or cur_p is None or cur_p != p:
            # best-effort: rely on open_selected to reload current file
            obj = getattr(self, "_browser_current_obj", None)

        if obj is None:
            return

        try:
            json_path_set(obj, path, old_val)
            write_text_utf16le(p, dump_json_compact(obj))
            try:
                self.mark_unsynced("Data Browser")
            except Exception:
                pass
            self._browser_open_selected()
            self._browser_select_path(path)
            try:
                self._msg(f"[Browser] Undo {path} in {p.name}")
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, "Undo failed", str(e))

    def _browser_select_path(self, path: str) -> None:
        try:
            it = self._browser_path_to_item.get(str(path))
        except Exception:
            it = None
        if not it:
            return
        try:
            self.browser_json_tree.setCurrentItem(it)
            self.browser_json_tree.scrollToItem(it)
        except Exception:
            pass

    def _on_json_tree_menu(self, pos) -> None:
        item = self.browser_json_tree.itemAt(pos)
        if item is None:
            return

        path = item.data(0, Qt.ItemDataRole.UserRole) or ""
        raw_key = item.text(0) or ""

        menu = QMenu(self.browser_json_tree)

        act_copy_path = QAction("Copy JSON path", self.browser_json_tree)
        act_copy_path.triggered.connect(lambda: QApplication.clipboard().setText(str(path)))
        menu.addAction(act_copy_path)

        act_copy_value = QAction("Copy value preview", self.browser_json_tree)
        act_copy_value.triggered.connect(lambda: QApplication.clipboard().setText(item.text(1)))
        menu.addAction(act_copy_value)

        menu.addSeparator()
        act_undo = QAction("Undo last change", self.browser_json_tree)
        act_undo.triggered.connect(self._browser_undo_last)
        menu.addAction(act_undo)

        act_revert = QAction("Revert this file to original (session)", self.browser_json_tree)

        def _do_revert() -> None:
            p = getattr(self, "_browser_current_path", None)
            if not p:
                return
            try:
                original = self._browser_original_text.get(p)
            except Exception:
                original = None
            if not original:
                QMessageBox.information(self, "Revert", "No original snapshot captured for this file in this session.")
                return
            try:
                write_text_utf16le(p, original)
                self._browser_open_selected()
                self.mark_unsynced("Data Browser")
                try:
                    self._msg(f"[Browser] Reverted {p.name}")
                except Exception:
                    pass
            except Exception as e:
                QMessageBox.critical(self, "Revert failed", str(e))

        act_revert.triggered.connect(_do_revert)
        menu.addAction(act_revert)

        # Labeling helpers backed by data/id_database.json (shared across all tabs)
        CAR_ID_KEYS = {"carId", "lastCarId", "selectedCarId", "currentCarId"}
        TRACK_ID_KEYS = {"trackId", "lastTrackId", "selectedTrackId", "currentTrackId"}

        id_db = getattr(self, "id_db", None)
        cur_obj = getattr(self, "_browser_current_obj", None)
        cur_val = None
        if cur_obj is not None and path and path != "$":
            try:
                cur_val = json_path_get(cur_obj, path)
            except Exception:
                cur_val = None

        def _refresh_everywhere() -> None:
            try:
                self._browser_refresh()
            except Exception:
                pass
            try:
                self.reload_ui()  # type: ignore[attr-defined]
            except Exception:
                pass

        if id_db is not None:
            # Key label (only for dict keys, not list indices)
            if raw_key and not raw_key.startswith("[") and raw_key not in {"$", "…"}:
                menu.addSeparator()
                act_key = QAction("Set key label…", self.browser_json_tree)

                def _do_key() -> None:
                    try:
                        existing = str(id_db.key_labels.get(raw_key, ""))
                    except Exception:
                        existing = ""
                    txt, ok = QInputDialog.getText(
                        self,
                        "Key label",
                        f"Friendly label for key '{raw_key}':",
                        text=existing,
                    )
                    if not ok:
                        return
                    txt = txt.strip()
                    if not txt:
                        # Clear
                        try:
                            if raw_key in id_db.key_labels:
                                del id_db.key_labels[raw_key]
                                id_db.save()
                        except Exception:
                            pass
                    else:
                        try:
                            id_db.set_key_label(raw_key, txt)
                        except Exception:
                            pass
                    _refresh_everywhere()

                act_key.triggered.connect(_do_key)
                menu.addAction(act_key)

            # Car label
            if raw_key in CAR_ID_KEYS and isinstance(cur_val, (int, str)):
                menu.addSeparator()
                act_car = QAction("Set car label in database…", self.browser_json_tree)

                def _do_car() -> None:
                    cid = str(cur_val)
                    try:
                        existing = str(id_db.cars.get(cid, ""))
                    except Exception:
                        existing = ""
                    txt, ok = QInputDialog.getText(
                        self,
                        "Car label",
                        f"Friendly name for car ID {cid}:",
                        text=existing,
                    )
                    if not ok:
                        return
                    txt = txt.strip()
                    if not txt:
                        return
                    try:
                        id_db.set_car_label(cid, txt)
                    except Exception:
                        pass
                    try:
                        item.setText(1, f"{cid} — {id_db.label_car(cid)}")
                    except Exception:
                        pass
                    _refresh_everywhere()

                act_car.triggered.connect(_do_car)
                menu.addAction(act_car)

            # Track label
            if raw_key in TRACK_ID_KEYS and isinstance(cur_val, (int, str)):
                menu.addSeparator()
                act_track = QAction("Set track label in database…", self.browser_json_tree)

                def _do_track() -> None:
                    tid = str(cur_val)
                    try:
                        existing = str(id_db.tracks.get(tid, ""))
                    except Exception:
                        existing = ""
                    txt, ok = QInputDialog.getText(
                        self,
                        "Track label",
                        f"Friendly name for track ID {tid}:",
                        text=existing,
                    )
                    if not ok:
                        return
                    txt = txt.strip()
                    if not txt:
                        return
                    try:
                        id_db.set_track_label(tid, txt)
                    except Exception:
                        pass
                    try:
                        item.setText(1, f"{tid} — {id_db.label_track(tid)}")
                    except Exception:
                        pass
                    _refresh_everywhere()

                act_track.triggered.connect(_do_track)
                menu.addAction(act_track)

        menu.exec(self.browser_json_tree.viewport().mapToGlobal(pos))

    def _on_json_tree_double_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        path = None
        try:
            path = item.data(0, Qt.ItemDataRole.UserRole)
        except Exception:
            pass
        if not path or path == "$":
            return

        obj = getattr(self, "_browser_current_obj", None)
        p = getattr(self, "_browser_current_path", None)
        if obj is None or p is None:
            return

        try:
            cur_val = json_path_get(obj, path)
        except Exception:
            return

        if isinstance(cur_val, (dict, list)):
            QMessageBox.information(
                self,
                "Edit value",
                "This value is an object/array. Editing is supported for primitive values in this view.",
            )
            return

        try:
            default_text = json.dumps(cur_val, ensure_ascii=False)
        except Exception:
            default_text = str(cur_val)

        new_txt, ok = QInputDialog.getText(
            self,
            "Edit value",
            "Enter JSON literal (e.g. 5, true, null, \"text\"):",
            text=default_text,
        )
        if not ok:
            return

        try:
            new_val = json.loads(new_txt)
        except Exception:
            # If user did not enter valid JSON literal, treat as raw string.
            new_val = new_txt

        try:
            json_path_set(obj, path, new_val)
            write_text_utf16le(p, dump_json_compact(obj))

            # Immediately reflect that the extracted files differ from the last loaded state.
            try:
                self.mark_unsynced("Data Browser")
            except Exception:
                pass

            disp = str(new_val)
            if len(disp) > 120:
                disp = disp[:117] + "..."
            item.setText(1, disp)
            try:
                self._msg(f"[Browser] Updated {path} in {p.name}")
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, "Write failed", str(e))
