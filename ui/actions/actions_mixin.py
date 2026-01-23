from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

import json

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QLineEdit, QSpinBox

from core.extract import extract
from core.repack import repack, repack_preflight
from core.apply_presets import apply_updates_to_blocks
from core.json_ops import read_text_any, try_load_json, find_first_keys, dump_json_compact, write_text_utf16le
from core.scan_ids import scan_extracted_dir
from core.observed_db import ObservedDb


class ActionsMixin:
    """MainWindow mixin for project actions and extracted-save helpers.

    This file must stay strictly class-based. Previous iterations suffered from
    indentation drift which accidentally moved methods out of the class scope,
    causing runtime AttributeError failures.
    """

    # ---------------------------
    # Logging
    # ---------------------------

    def _msg(self, s: str) -> None:
        """Lightweight logger.

        The UI log panel was removed; keep logging available via stdout.
        """
        print(str(s))

    # ---------------------------
    # Formatting
    # ---------------------------

    @staticmethod
    def _format_number_like(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, (int, float)):
            if isinstance(v, float) and not v.is_integer():
                return str(v)
            try:
                return f"{int(v):,}"
            except Exception:
                return str(v)
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit():
                try:
                    return f"{int(s):,}"
                except Exception:
                    return s
            return s
        return str(v)

    # ---------------------------
    # Pickers / guards
    # ---------------------------

    def pick_base(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self,
            "Select base memory*.dat",
            "",
            "DAT files (*.dat);;All files (*.*)",
        )
        if not p:
            return
        self.base_dat = Path(p)
        self.base_edit.setText(str(self.base_dat))
        self._msg(f"Base set: {self.base_dat}")

    def pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select working folder")
        if not d:
            return
        self.work_dir = Path(d)
        self.dir_edit.setText(str(self.work_dir))
        self._msg(f"Folder set: {self.work_dir}")

        # Keep schema-aware tabs aligned with the active work directory.
        try:
            if hasattr(self, "garage_unlocks_tab") and hasattr(self.garage_unlocks_tab, "refresh_from_workdir"):
                self.garage_unlocks_tab.refresh_from_workdir(self.work_dir)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            if hasattr(self, "unlock_manager_tab") and hasattr(self.unlock_manager_tab, "refresh_from_workdir"):
                self.unlock_manager_tab.refresh_from_workdir(self.work_dir)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _ensure_ready(self) -> bool:
        if not getattr(self, "base_dat", None) or not self.base_dat.exists():
            QMessageBox.warning(self, "Missing base", "Pick a valid base memory*.dat")
            return False
        if not getattr(self, "work_dir", None):
            QMessageBox.warning(self, "Missing folder", "Pick a working folder")
            return False
        try:
            self.work_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, "Invalid folder", f"Cannot use work folder:\n{e}")
            return False
        return True

    def _ensure_extracted(self) -> bool:
        if not getattr(self, "work_dir", None):
            QMessageBox.warning(self, "Missing folder", "Pick a working folder first.")
            return False

        manifest = self.work_dir / "manifest.json"
        blocks = self.work_dir / "blocks"
        if not manifest.exists() or not blocks.exists():
            QMessageBox.warning(
                self,
                "Not extracted",
                "Run Extract first (need manifest.json and blocks/).",
            )
            return False

        try:
            if blocks.is_dir() and not any(blocks.iterdir()):
                QMessageBox.warning(self, "Not extracted", "blocks/ is empty. Re-run Extract.")
                return False
        except Exception:
            QMessageBox.warning(self, "Not extracted", "blocks/ is not readable. Re-run Extract.")
            return False

        return True

    # ---------------------------
    # Top menu actions
    # ---------------------------

    def on_open_file(self) -> None:
        """Open a memory*.dat file, then auto-extract + auto-load values."""
        start_dir = ""
        try:
            if getattr(self, "base_dat", None):
                start_dir = str(Path(self.base_dat).parent)
        except Exception:
            start_dir = ""

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open memory.dat",
            start_dir,
            "memory*.dat (*.dat);;All files (*.*)",
        )
        if not path:
            return

        self.base_dat = Path(path)
        self.base_edit.setText(str(self.base_dat))

        # Default work dir under project ./work/<stem>_<size>_<sig>/
        # This prevents collisions between multiple different saves that share the
        # same filename (e.g. memory.dat) and eliminates stale-manifest issues.
        try:
            base_dir = getattr(self, "base_dir", Path.cwd())
            work_root = base_dir / "work"
            work_root.mkdir(parents=True, exist_ok=True)

            size = self.base_dat.stat().st_size
            # Full SHA1 is fine for ~32MB files and gives a strong uniqueness guarantee.
            sig = hashlib.sha1(self.base_dat.read_bytes()).hexdigest()[:10]
            self.work_dir = work_root / f"{self.base_dat.stem}_{size}_{sig}"
            self.work_dir.mkdir(parents=True, exist_ok=True)
            self.dir_edit.setText(str(self.work_dir))

            # Make it very obvious which base file is currently active.
            try:
                self.setWindowTitle(f"CarX Drift PS4 - Save Editor — {self.base_dat.name} ({size} bytes)")
            except Exception:
                pass
        except Exception:
            pass

        self.on_extract_and_load()

    def on_save(self) -> None:
        """Save (Apply + Repack).

        This is the primary workflow button/shortcut. It applies Currency + Unlocks + Stats
        into the extracted JSON blocks first, then repacks.
        """
        # Ensure any debounced auto-sync edits are flushed to extracted blocks
        try:
            if hasattr(self, "_flush_auto_apply"):
                self._flush_auto_apply()
        except Exception:
            pass

        # Apply without reloading UI for each step (faster + avoids flicker)
        try:
            self.on_apply_currency(silent=True, reload_ui=False)
        except Exception:
            pass

        # Garage unlocks
        try:
            if hasattr(self, "garage_unlocks_tab") and hasattr(self, "_on_apply_garage_unlocks_requested"):
                payload = self.garage_unlocks_tab.get_payload()
                self._on_apply_garage_unlocks_requested(payload, reload_ui=False)
        except Exception:
            pass

        # Stats/Cups/Points
        try:
            if hasattr(self, "stats_tab") and hasattr(self, "_on_apply_stats_requested"):
                updates = self.stats_tab.get_updates()
                self._on_apply_stats_requested(updates, reload_ui=False)
        except Exception:
            pass

        # Car Slots (slot limits)
        try:
            if hasattr(self, "progression_tab") and hasattr(self.progression_tab, "apply_slot_limits"):
                # type: ignore[attr-defined]
                self.progression_tab.apply_slot_limits(silent=True, reload_ui=False)
        except Exception:
            pass

        # Finally repack
        self.on_repack()

    def on_extract_and_load(self) -> None:
        self.on_extract()
        self.on_load_values()

    # ---------------------------
    # Load values
    # ---------------------------

    def on_load_values(self) -> None:
        if not self._ensure_extracted():
            return
        self._populate_fields_from_save(show_summary=True)

    def _populate_fields_from_save(self, show_summary: bool = False) -> None:
        if not self._ensure_extracted():
            return

        # Prevent UI updates (setText/setValue) from triggering auto-apply while loading.
        was_suspended = getattr(self, "_suspend_auto_apply", False)
        try:
            self._suspend_auto_apply = True  # type: ignore[attr-defined]
        except Exception:
            pass

        keys = [
            # Currency
            "coins",
            "ratingPoints",
            "playerExp",
            # Stats
            "timeInGame",
            "racesPlayed",
            "driftRacesPlayed",
            "timeAttackRacesPlayed",
            "MPRacesPlayed",
            "maxPointsPerDrift",
            "maxPointsPerRace",
            "averagePointsPerRace",
            "cups1",
            "cups2",
            "cups3",
            # Garage / Unlocks
            "m_cars",
            "availableTracks",
            "availableCars",
        ]

        found: Dict[str, Any] = {}
        blocks_dir = self.work_dir / "blocks"
        for p in sorted(blocks_dir.glob("*")):
            try:
                txt = read_text_any(p)
                obj = try_load_json(txt)
                if obj is None:
                    continue
                got = find_first_keys(obj, keys)
                for k, v in got.items():
                    if k not in found:
                        found[k] = v
                if len(found) == len(keys):
                    break
            except Exception:
                continue

        def _set_line(le: QLineEdit, v: Any) -> None:
            if v is None:
                return
            le.setText(self._format_number_like(v))

        def _set_spin(sb: QSpinBox, v: Any) -> None:
            try:
                if isinstance(v, str):
                    v = int(float(v)) if any(c in v for c in ".eE") else int(v)
                sb.setValue(int(v))
            except Exception:
                pass

        if "coins" in found:
            _set_spin(self.coins_spin, found["coins"])
        if "ratingPoints" in found:
            _set_line(self.rating_edit, found["ratingPoints"])
        if "playerExp" in found:
            _set_line(self.player_exp_edit, found["playerExp"])

        # Delegate stats to the tab.
        if getattr(self, "stats_tab", None):
            try:
                self.stats_tab.load_from_found(found)
            except Exception:
                pass

        # Let specialized tabs refresh.
        for attr in ("garage_unlocks_tab", "engine_parts_tab", "quests_tab", "progression_tab"):
            try:
                tab = getattr(self, attr, None)
                if tab is not None and hasattr(tab, "refresh_from_workdir"):
                    tab.refresh_from_workdir(self.work_dir)
            except Exception:
                pass

        # ID scanning is deferred for speed. Advanced Unlocks / Database will scan on-demand.

        if show_summary:
            missing = [k for k in keys if k not in found]
            if missing:
                QMessageBox.information(
                    self,
                    "Loaded values (partial)",
                    "Loaded some values from the extracted save.\n\n"
                    "Missing keys (not found in extracted JSON blocks):\n- " + "\n- ".join(missing),
                )
            else:
                QMessageBox.information(self, "Loaded values", "Loaded current values from the extracted save.")

        # Restore auto-apply state
        try:
            self._suspend_auto_apply = was_suspended  # type: ignore[attr-defined]
        except Exception:
            pass

    # ---------------------------
    # Extract / apply / repack
    # ---------------------------

    def on_extract(self) -> None:
        if not self._ensure_ready():
            return
        try:
            self._msg("Extracting...")
            manifest = extract(self.base_dat, self.work_dir)
            self._msg(f"Extract complete: {manifest}")

            # NOTE:
            # We intentionally do *not* call _populate_fields_from_save() here.
            # The primary workflow uses "Extract + Load Values" which calls
            # on_extract() followed by on_load_values(). Calling populate here
            # would cause redundant refreshes (and in turn redundant EngineParts
            # DB loads/log spam) during a single user action.

            # Refresh schema-aware views that depend on blocks/ content.
            try:
                if hasattr(self, "garage_unlocks_tab") and hasattr(self.garage_unlocks_tab, "refresh_from_workdir"):
                    self.garage_unlocks_tab.refresh_from_workdir(self.work_dir)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                if hasattr(self, "unlock_manager_tab") and hasattr(self.unlock_manager_tab, "refresh_from_workdir"):
                    self.unlock_manager_tab.refresh_from_workdir(self.work_dir)  # type: ignore[attr-defined]
            except Exception:
                pass

            try:
                if hasattr(self, "favorites_tab") and hasattr(self.favorites_tab, "refresh_from_workdir"):
                    self.favorites_tab.refresh_from_workdir(self.work_dir)  # type: ignore[attr-defined]
            except Exception:
                pass

            # Browser refresh
            if hasattr(self, "_browser_refresh"):
                try:
                    self._browser_refresh()
                except Exception:
                    pass
        except Exception as e:
            QMessageBox.critical(self, "Extract failed", str(e))
            self._msg(f"Extract failed: {e}")

    def on_apply_currency(self, *, silent: bool = False, reload_ui: bool = True) -> None:
        if not self._ensure_extracted():
            return
        # NOTE: CarX stores many "numeric" fields as strings. Also, the UI
        # formats values with commas, so strip separators before writing.
        def _digits_only(s: str) -> str:
            s = (s or "").strip().replace(",", "").replace("_", "")
            return "".join(ch for ch in s if ch.isdigit())

        coins_s = str(int(self.coins_spin.value()))
        rating_s = _digits_only(self.rating_edit.text())
        exp_s = _digits_only(self.player_exp_edit.text())

        updates = {
            "coins": coins_s,
            "ratingPoints": rating_s,
            "playerExp": exp_s,
            # Some builds gate wallet application behind this flag.
            "isDLCMoneyApplied": "True",
        }
        try:
            n, warnings, touched = apply_updates_to_blocks(
                self.work_dir,
                updates,
                target_best_only=bool(self.chk_target_best.isChecked()),
                per_key_target=True,
                create_missing_root=False,
            )
            if warnings and not silent:
                self._msg("[Currency] " + " | ".join(warnings[:8]))
            if not silent:
                self._msg(f"[Currency] Applied {n} assignments to {len(touched)} block(s).")
            if reload_ui:
                self._populate_fields_from_save(show_summary=False)
        except Exception as e:
            QMessageBox.critical(self, "Apply failed", str(e))
            if not silent:
                self._msg(f"[Currency] Failed: {e}")

    def on_apply_unlocks(self) -> None:
        try:
            self.garage_unlocks_tab.request_apply()
        except Exception as e:
            self._msg(f"[Unlocks] Failed: {e}")

    def on_apply_stats(self) -> None:
        try:
            self.stats_tab.request_apply()
        except Exception as e:
            self._msg(f"[Stats] Failed: {e}")

    # ---------------------------
    # Tab signal handlers
    # ---------------------------

    def _on_apply_stats_requested(self, updates: dict, reload_ui: bool = True) -> None:
        if not self._ensure_extracted():
            return
        if not isinstance(updates, dict):
            self._msg("[Stats] Invalid update payload")
            return
        try:
            n, warnings, touched = apply_updates_to_blocks(
                self.work_dir,
                updates,
                target_best_only=bool(self.chk_target_best.isChecked()),
                per_key_target=True,
                create_missing_root=False,
            )
            if warnings:
                self._msg("[Stats] " + " | ".join(warnings[:8]))
            self._msg(f"[Stats] Applied {n} assignments to {len(touched)} block(s).")
            if reload_ui:
                self._populate_fields_from_save(show_summary=False)
        except Exception as e:
            QMessageBox.critical(self, "Apply failed", str(e))
            self._msg(f"[Stats] Failed: {e}")

    def _on_apply_garage_unlocks_requested(self, payload: dict, reload_ui: bool = True) -> None:
        if not self._ensure_extracted():
            return
        if not isinstance(payload, dict):
            self._msg("[Unlocks] Invalid payload")
            return

        # Payload supports both legacy and schema-aware formats
        op = payload.get("__op") or payload.get("op")
        car_key = payload.get("car_key") or "availableCars"
        track_key = payload.get("track_key") or "availableTracks"
        cars = payload.get("cars")
        tracks = payload.get("tracks")

        if cars is None:
            cars = payload.get(car_key) or payload.get("availableCars")
        if tracks is None:
            tracks = payload.get(track_key) or payload.get("availableTracks")

        # Accept sets/tuples (e.g., UnlockManagerTab emits sets)
        if isinstance(cars, (set, tuple)):
            cars = list(cars)
        if isinstance(tracks, (set, tuple)):
            tracks = list(tracks)

        def _iter_blocks() -> list[tuple[Path, Any]]:
            root = self.work_dir
            blocks_dir = root / "blocks"
            if not blocks_dir.exists() and (root / "extracted" / "blocks").exists():
                blocks_dir = root / "extracted" / "blocks"
            out: list[tuple[Path, Any]] = []
            for p in sorted(blocks_dir.glob("*")):
                try:
                    txt = read_text_any(p)
                    obj = try_load_json(txt)
                    if obj is None:
                        continue
                    out.append((p, obj))
                except Exception:
                    continue
            return out

        def _infer_list_kind(blocks: list[tuple[Path, Any]], key: str) -> Optional[str]:
            for _, obj in blocks:
                got = find_first_keys(obj, [key])
                if key not in got:
                    continue
                v = got.get(key)
                if not isinstance(v, list):
                    continue
                for x in v:
                    if x is None:
                        continue
                    return "int" if isinstance(x, int) else "str"
                # empty list: unknown, but treat as str by default (safer)
                return "str"
            return None

        def _dedupe_keep_order(vals: list[Any]) -> list[Any]:
            seen: set[str] = set()
            out: list[Any] = []
            for v in vals:
                k = str(v)
                if k in seen:
                    continue
                seen.add(k)
                out.append(v)
            return out

        def _coerce_list(xs: list, *, kind: Optional[str]) -> list[Any]:
            kind = kind or "str"
            out: list[Any] = []
            for x in xs:
                if x is None:
                    continue
                s = str(x).strip()
                if not s:
                    continue
                if kind == "int" and s.isdigit():
                    try:
                        out.append(int(s))
                        continue
                    except Exception:
                        pass
                # preserve strings if save uses strings
                out.append(s)
            return _dedupe_keep_order(out)

        def _inject_container(blocks: list[tuple[Path, Any]], ck: str, tk: str) -> Optional[Path]:
            # Prefer block containing lastCarId/lastTrackId (player profile root)
            best: Optional[tuple[int, Path, Any]] = None
            for p, obj in blocks:
                score = 0
                got = find_first_keys(obj, ["lastCarId", "lastTrackId"])
                if "lastCarId" in got:
                    score += 10
                if "lastTrackId" in got:
                    score += 5
                if score and (best is None or score > best[0]):
                    best = (score, p, obj)
            if best is None and blocks:
                # fallback: largest file
                biggest = max(blocks, key=lambda t: t[0].stat().st_size)
                best = (0, biggest[0], biggest[1])
            if not best:
                return None
            _, p, obj = best
            if not isinstance(obj, dict):
                return None
            obj.setdefault(ck, [])
            obj.setdefault(tk, [])
            try:
                write_text_utf16le(p, dump_json_compact(obj))
                return p
            except Exception:
                return None

        blocks = _iter_blocks()
        if op == "inject_unlock_container":
            injected = _inject_container(blocks, car_key, track_key)
            if injected:
                self._msg(f"[Unlocks] Created container {car_key}/{track_key} in {injected.name}")
                if reload_ui:
                    self._populate_fields_from_save(show_summary=False)
            else:
                self._msg(f"[Unlocks] Failed to create container {car_key}/{track_key}")
            return

        updates: Dict[str, Any] = {}

        # Determine per-key element types from the save (prevents 'applied but ignored' issues)
        car_kind = _infer_list_kind(blocks, car_key)
        track_kind = _infer_list_kind(blocks, track_key)

        # If the save doesn't contain the container, do not "invent" a target block silently.
        # Require explicit container creation to avoid writing keys into the wrong structure.
        if car_kind is None or track_kind is None:
            self._msg(
                f"[Unlocks] Container not found for {car_key}/{track_key}. "
                "Select the correct Schema in the Garage tab, or click 'Create container'."
            )
            return

        merge_mode = bool(payload.get("merge", True))

        # If UI explicitly allows removal, default to overwrite mode unless merge was specified.
        if payload.get("allow_removal") is True and ("merge" not in payload):
            merge_mode = False

        def _get_first_list(key: str) -> list:
            for _, obj in blocks:
                got = find_first_keys(obj, [key])
                if key in got and isinstance(got.get(key), list):
                    return got.get(key)  # type: ignore[return-value]
            return []

        if isinstance(cars, list):
            new_list = _coerce_list(cars, kind=car_kind)
            if merge_mode:
                existing_list = _get_first_list(car_key)
                updates[car_key] = _dedupe_keep_order(list(existing_list) + list(new_list))
            else:
                updates[car_key] = new_list

        if isinstance(tracks, list):
            new_list = _coerce_list(tracks, kind=track_kind)
            if merge_mode:
                existing_list = _get_first_list(track_key)
                updates[track_key] = _dedupe_keep_order(list(existing_list) + list(new_list))
            else:
                updates[track_key] = new_list


        if not updates:
            self._msg("[Unlocks] Nothing to apply")
            return

        try:
            # Debug summary (helps diagnose schema/type mismatches)
            try:
                mode = payload.get("schema_mode") or f"{car_key}/{track_key}"
                before_c = _get_first_list(car_key)
                before_t = _get_first_list(track_key)
                self._msg(
                    f"[Unlocks] Applying schema={mode} merge={merge_mode} "
                    f"car_kind={car_kind} track_kind={track_kind} "
                    f"cars {len(before_c)}→{len(updates.get(car_key, before_c))} "
                    f"tracks {len(before_t)}→{len(updates.get(track_key, before_t))}"
                )
            except Exception:
                pass

            n, warnings, touched = apply_updates_to_blocks(
                self.work_dir,
                updates,
                target_best_only=bool(self.chk_target_best.isChecked()),
                per_key_target=True,
                create_missing_root=False,
                update_all_occurrences=False,
            )
            if warnings:
                self._msg("[Unlocks] " + " | ".join(warnings[:8]))
            self._msg(f"[Unlocks] Applied {n} assignments to {len(touched)} block(s).")
            if reload_ui:
                self._populate_fields_from_save(show_summary=False)
        except Exception as e:
            QMessageBox.critical(self, "Apply failed", str(e))
            self._msg(f"[Unlocks] Failed: {e}")

    def on_repack(self) -> None:
        if not self._ensure_extracted():
            return

        # If enabled, apply all pending edits to the extracted blocks before repacking.
        try:
            if hasattr(self, "chk_apply_all") and self.chk_apply_all.isChecked():
                # Currency
                try:
                    if hasattr(self, "on_apply_currency"):
                        self.on_apply_currency(silent=True, reload_ui=False)  # type: ignore[arg-type]
                except Exception:
                    pass
                # Garage unlocks
                try:
                    if hasattr(self, "_on_apply_garage_unlocks_requested") and hasattr(self, "garage_unlocks_tab"):
                        payload = self.garage_unlocks_tab.get_payload()
                        self._on_apply_garage_unlocks_requested(payload, reload_ui=False)
                except Exception:
                    pass
                # Stats/Cups/Points
                try:
                    if hasattr(self, "_on_apply_stats_requested") and hasattr(self, "stats_tab"):
                        updates = self.stats_tab.get_updates()
                        self._on_apply_stats_requested(updates, reload_ui=False)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            out_path = self.base_dat.parent / (self.base_dat.stem + "_patched" + self.base_dat.suffix)
            ok, fail, warnings, report_path = repack(self.base_dat, self.work_dir, out_path)
            self._msg(f"Repacked: {out_path} (ok={ok}, fail={fail})")
            msg_lines = [
                f"Repacked to:\n{out_path}",
                "",
                f"Blocks written: {ok}",
                f"Blocks failed: {fail}",
                f"Report: {report_path}",
            ]
            if warnings:
                msg_lines.append("")
                msg_lines.append("Warnings (first 8):")
                for w in warnings[:8]:
                    msg_lines.append(f"- {w}")
            QMessageBox.information(self, "Repack", "\n".join(msg_lines))
        except Exception as e:
            QMessageBox.critical(self, "Repack failed", str(e))
            self._msg(f"Repack failed: {e}")


    def on_repack_preflight(self) -> None:
        """Compute and write a repack preflight report (no output written)."""
        if not self._ensure_extracted():
            return
        try:
            items, report_path = repack_preflight(self.base_dat, self.work_dir)
            # Build a concise on-screen summary (worst headroom).
            worst = sorted([it for it in items if it.status in ('OK','FAIL')], key=lambda x: x.headroom)[:8]
            lines = [
                f"Preflight report written to:\n{report_path}",
                "",
                "Worst headroom:",
            ]
            for it in worst:
                lines.append(f"block {it.index:02d} @0x{it.offset:08X} {it.status}: headroom={it.headroom} ({it.out_name})")
            QMessageBox.information(self, "Repack preflight", "\n".join(lines))
            self._msg(f"[Preflight] Wrote: {report_path}")
        except Exception as e:
            QMessageBox.critical(self, "Preflight failed", str(e))
            self._msg(f"Preflight failed: {e}")