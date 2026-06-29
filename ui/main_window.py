from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QMainWindow,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.id_database import IdDatabase
from core.favorites_db import FavoritesDb
from core.tunes_db import TunesDb
from core.app_paths import get_writable_data_dir, migrate_portable_files_if_needed

from ui.actions.actions_mixin import ActionsMixin
from ui.browser.browser_mixin import BrowserMixin
from ui.themes import DEFAULT_THEME, THEME_NAMES, apply_app_theme, is_dark_theme

from ui.tabs.stats_tab import StatsTab
from ui.tabs.garage_unlocks_tab import GarageUnlocksTab
from ui.tabs.engine_parts_tab import EnginePartsTab
from ui.tabs.progression_tab import ProgressionTab
from ui.tabs.unlock_manager_tab import UnlockManagerTab


def _seconds_to_duration_str(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class MainWindow(ActionsMixin, BrowserMixin, QMainWindow):
    """Application main window.

    Design goals:
      - Keep this file focused on UI layout and theming.
      - Keep signal handlers and heavy logic in mixins / tab modules.
      - Avoid indentation/scope regressions that previously caused missing-method crashes.
    """

    def __init__(self):
        super().__init__()

        base_dir = Path(__file__).resolve().parents[1]
        # Keep a stable reference for mixins/tabs that need project-relative paths.
        self.base_dir = base_dir

        # Stable per-user (or portable) editor data directory
        self.data_dir = get_writable_data_dir(base_dir)
        # One-way migration from old portable <base_dir>/data into per-user dir
        migrate_portable_files_if_needed(base_dir, self.data_dir, [
            "id_database.json",
            "favorites.json",
            "engine_parts_db.json",
            "tunes_db.json",
        ])
        self.id_db = IdDatabase.load_default(base_dir)
        self.favorites_db = FavoritesDb.load_default(base_dir)
        self.tune_db = TunesDb(base_dir)

        self.setWindowTitle("CarX Drift PS4 - Save Editor")

        self.base_dat: Optional[Path] = None
        self.work_dir: Optional[Path] = None

        self._theme_name = DEFAULT_THEME
        self._dark_enabled = True
        self._build_ui()
        self._setup_auto_apply()
        self.apply_named_theme(self._theme_name)


    # ---------------------------
    # Theme
    # ---------------------------


    def reload_ui(self) -> None:
        """Refresh tabs after Extract / Load Values."""
        # Refresh any tabs that support workdir-based loading
        for tab in (
            getattr(self, "garage_unlocks_tab", None),
            getattr(self, "engine_parts_tab", None),
            getattr(self, "progression_tab", None),
            getattr(self, "unlock_manager_tab", None),
            getattr(self, "stats_tab", None),
        ):
            if tab is not None and hasattr(tab, "refresh_from_workdir"):
                try:
                    tab.refresh_from_workdir(self.work_dir)
                except Exception:
                    pass


    def _setup_auto_apply(self) -> None:
        """Initialize debounced auto-apply (sync to extracted blocks; does not repack)."""
        self._auto_apply_timer = QTimer(self)
        self._auto_apply_timer.setSingleShot(True)
        self._auto_apply_timer.timeout.connect(self._run_auto_apply)
        self._auto_apply_pending = False
        # Domain-specific dirty flags so we don't re-apply heavy operations (unlock/stats)
        # on every small UI edit.
        self._dirty_currency = False
        # Global suspend flag for programmatic UI updates (loading values, refreshing tabs).
        self._suspend_auto_apply = False

    def _queue_auto_apply(self, delay_ms: int = 650, *, domain: str = "currency") -> None:
        """Queue an auto-apply flush after a short debounce.

        We only auto-apply lightweight domains (currency) to keep the UI responsive.
        Heavy domains (garage unlocks / stats) are applied explicitly via their
        "Apply" buttons or via Save/Repack when "Apply pending edits" is enabled.
        """
        if not hasattr(self, "_auto_apply_timer"):
            return
        if getattr(self, "_suspend_auto_apply", False):
            return

        if domain == "currency":
            self._dirty_currency = True
        self._auto_apply_pending = True
        try:
            self.mark_unsynced()
        except Exception:
            pass
        self._auto_apply_timer.start(delay_ms)

    def _flush_auto_apply(self) -> None:
        """Flush any pending auto-apply immediately (call before Save/Repack)."""
        if hasattr(self, "_auto_apply_timer") and self._auto_apply_timer.isActive():
            self._auto_apply_timer.stop()
        self._run_auto_apply()

    def _run_auto_apply(self) -> None:
        """Apply current UI values into extracted blocks using existing handlers."""
        if not getattr(self, "_auto_apply_pending", False):
            return
        self._auto_apply_pending = False

        if getattr(self, "_suspend_auto_apply", False):
            return

        # Only apply if extracted blocks exist
        if hasattr(self, "_ensure_extracted"):
            try:
                if not self._ensure_extracted():
                    return
            except Exception:
                return

        # Apply without showing dialogs and without re-loading UI for each step.
        # IMPORTANT: only auto-apply currency to avoid lag/log spam.
        if getattr(self, "_dirty_currency", False):
            try:
                if hasattr(self, "on_apply_currency"):
                    # type: ignore[arg-type]
                    self.on_apply_currency(silent=True, reload_ui=False)
            except Exception:
                pass
            self._dirty_currency = False

        # NOTE: do not auto-apply other domains here (unlock/stats/slot-limits),
        # as those can be expensive and should be explicit.
        try:
            self.mark_synced()
        except Exception:
            pass

    def _repolish(self, widget: QWidget) -> None:
        """Refresh Qt dynamic-property styling after state/theme changes."""
        try:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        except Exception:
            pass

    def apply_named_theme(self, name: str) -> None:
        app = QApplication.instance()
        if not app:
            return
        if name not in THEME_NAMES:
            name = DEFAULT_THEME
        self._theme_name = name
        self._dark_enabled = is_dark_theme(name)
        apply_app_theme(app, name)

        combo = getattr(self, "cmb_theme", None)
        if combo is not None and combo.currentText() != name:
            try:
                combo.blockSignals(True)
                combo.setCurrentText(name)
            finally:
                combo.blockSignals(False)

        chk = getattr(self, "chk_dark_mode", None)
        if chk is not None and chk.isChecked() != self._dark_enabled:
            try:
                chk.blockSignals(True)
                chk.setChecked(self._dark_enabled)
            finally:
                chk.blockSignals(False)

        lbl = getattr(self, "_sync_label", None)
        if lbl is not None:
            self._repolish(lbl)

    def apply_dark_theme(self) -> None:
        self.apply_named_theme(DEFAULT_THEME)

    def apply_light_theme(self) -> None:
        self.apply_named_theme("Clean Light")

    def on_dark_mode_toggled(self, enabled: bool) -> None:
        # Keep the old checkbox behavior, but route it through the new theme system.
        if enabled:
            self.apply_named_theme(DEFAULT_THEME if not is_dark_theme(self._theme_name) else self._theme_name)
        else:
            self.apply_named_theme("Clean Light")

    def on_theme_changed(self, name: str) -> None:
        self.apply_named_theme(name)

    # ---------------------------
    # UI layout
    # ---------------------------

    def _build_ui(self) -> None:
        """Build the main window layout.

        Note: This must remain a class method (indentation matters). Previous
        iterations had scope drift where methods were accidentally defined at the
        module level, causing AttributeError crashes at startup.
        """

        self.setMinimumSize(1160, 720)

        self._central = QWidget()
        self.setCentralWidget(self._central)
        root = QVBoxLayout(self._central)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(14)

        root.addWidget(self._build_header_card())

        # ---- Tabs ----
        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        self.tabs.tabBar().setObjectName("MainTabBar")
        # Keep the tab row fully custom-painted. Document mode / native tab bases can
        # draw a thin horizontal line across the whole tab row on Windows.
        self.tabs.setDocumentMode(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        try:
            self.tabs.tabBar().setDrawBase(False)
        except Exception:
            pass

        # Core project controls and settings (moved out of top-of-window group boxes)
        self.tabs.addTab(self._build_project_tab(), "Project")
        self.tabs.addTab(self._build_options_tab(), "Options")

        # Editable values
        self.tabs.addTab(self._build_currency_tab(), "Coins / Rating / XP")

        self.stats_tab = StatsTab(
            id_db=self.id_db,
            format_number_like=self._format_number_like,
            seconds_to_duration=_seconds_to_duration_str,
        )
        self.stats_tab.applyRequested.connect(self._on_apply_stats_requested)
        try:
            # Do not auto-apply heavy domains on each edit; just mark unsynced.
            self.stats_tab.changed.connect(lambda: self.mark_unsynced("Stats"))
        except Exception:
            pass
        self.tabs.addTab(self.stats_tab, "Time / Races / Cups / Points")

        self.garage_unlocks_tab = GarageUnlocksTab(
            self,
            id_db=self.id_db,
            observed_db_path=Path(self.data_dir) / "observed_db.json",
        )
        self.garage_unlocks_tab.applyRequested.connect(
            lambda payload: self._on_apply_garage_unlocks_requested(payload, reload_ui=True)  # type: ignore[misc]
        )
        try:
            self.garage_unlocks_tab.changed.connect(lambda: self.mark_unsynced("Garage"))
        except Exception:
            pass
        self.tabs.addTab(self.garage_unlocks_tab, "Garage & Unlocks")

        # Engine Parts tab currently accepts id_db + tune_db; keep call signature aligned.
        self.engine_parts_tab = EnginePartsTab(
            self,
            id_db=self.id_db,
            tune_db=self.tune_db,
        )
        try:
            self.engine_parts_tab.changed.connect(lambda: self.mark_unsynced("Engine Parts"))
        except Exception:
            pass
        self.tabs.addTab(self.engine_parts_tab, "Engine Parts")
        try:
            pass
        except Exception:
            pass


        self.progression_tab = ProgressionTab(self, id_db=self.id_db)
        try:
            self.progression_tab.changed.connect(lambda: self.mark_unsynced("Car Slots"))
        except Exception:
            pass
        self.tabs.addTab(self.progression_tab, "Car Slots")

        # Advanced (power-user) unlock management
        self.unlock_manager_tab = UnlockManagerTab(self)
        try:
            # Some builds expose configure(); keep this optional to avoid boot failures.
            if hasattr(self.unlock_manager_tab, "configure"):
                self.unlock_manager_tab.configure(
                    id_db=self.id_db,
                    extracted_dir=self.work_dir,
                    observed_db_path=Path(self.data_dir) / "observed_db.json",
                )
        except Exception:
            pass
        try:
            self.unlock_manager_tab.applyRequested.connect(
                lambda payload: self._on_apply_garage_unlocks_requested(payload, reload_ui=True)  # type: ignore[arg-type]
            )
        except Exception:
            pass
        self.tabs.addTab(self.unlock_manager_tab, "Advanced Unlocks")

        self.browser_tab = self._build_browser_tab()
        self.tabs.addTab(self.browser_tab, "Data Browser")

        self._setup_lazy_refresh()

        root.addWidget(self.tabs)

        # Status bar sync indicator
        try:
            self._sync_label = QLabel("Synced")
            self._sync_label.setObjectName("SyncPill")
            self._sync_label.setProperty("state", "synced")
            self.statusBar().addPermanentWidget(self._sync_label)
        except Exception:
            self._sync_label = None

        # Toolbar (keyboard shortcuts) - no top menus to save space
        self._build_actions_bar()

    def _build_header_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("HeroCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        title = QLabel("CarX Drift Save Editor")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Extract • edit • sync • repack")
        subtitle.setObjectName("AppSubtitle")

        title_col.addWidget(title)
        title_col.addWidget(subtitle)

        badge = QLabel("ProtoBuffers")
        badge.setObjectName("AuthorBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addLayout(title_col, 1)
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return card

    # ---------------------------
    # Lazy tab refresh
    # ---------------------------

    def _setup_lazy_refresh(self) -> None:
        """Defer expensive extracted-save tab loading until the user opens that tab."""
        self._lazy_refresh_pending = set()
        self._lazy_refresh_widgets = {}
        for attr in (
            "garage_unlocks_tab",
            "engine_parts_tab",
            "progression_tab",
            "unlock_manager_tab",
        ):
            tab = getattr(self, attr, None)
            if tab is not None:
                self._lazy_refresh_widgets[tab] = attr
        browser_tab = getattr(self, "browser_tab", None)
        if browser_tab is not None:
            self._lazy_refresh_widgets[browser_tab] = "browser"
        try:
            self.tabs.currentChanged.connect(self._on_main_tab_changed)
        except Exception:
            pass

    def _mark_extracted_views_stale(self) -> None:
        """Mark heavyweight views as needing refresh without doing the work now."""
        try:
            self._lazy_refresh_pending = {
                "garage_unlocks_tab",
                "engine_parts_tab",
                "progression_tab",
                "unlock_manager_tab",
                "browser",
            }
        except Exception:
            self._lazy_refresh_pending = set()

    def _refresh_active_lazy_tab(self) -> None:
        """Refresh only the currently visible heavyweight tab, if it is stale."""
        if not getattr(self, "work_dir", None):
            return
        try:
            widget = self.tabs.currentWidget()
            attr = getattr(self, "_lazy_refresh_widgets", {}).get(widget)
        except Exception:
            attr = None
        if not attr:
            return
        pending = getattr(self, "_lazy_refresh_pending", set())
        if attr not in pending:
            return

        try:
            if attr == "browser":
                if hasattr(self, "_browser_refresh"):
                    self._browser_refresh()
            else:
                tab = getattr(self, attr, None)
                if tab is not None and hasattr(tab, "refresh_from_workdir"):
                    tab.refresh_from_workdir(self.work_dir)
            pending.discard(attr)
        except Exception as e:
            try:
                self._msg(f"[LazyLoad] {attr} refresh failed: {e}")
            except Exception:
                pass

    def _on_main_tab_changed(self, _index: int) -> None:
        self._refresh_active_lazy_tab()

    # ---------------------------
    # Project + Options tabs
    # ---------------------------

    def _build_project_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        proj = QGroupBox("Project files")
        pl = QVBoxLayout(proj)
        pl.setSpacing(12)

        r1 = QHBoxLayout()
        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("Base memory*.dat (e.g., memory1.dat)")
        b1 = QPushButton("Browse")
        b1.setProperty("variant", "secondary")
        b1.clicked.connect(self.pick_base)
        r1.addWidget(QLabel("Base:"))
        r1.addWidget(self.base_edit, 1)
        r1.addWidget(b1)
        pl.addLayout(r1)

        r2 = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("Working folder (manifest.json / blocks/)")
        b2 = QPushButton("Browse")
        b2.setProperty("variant", "secondary")
        b2.clicked.connect(self.pick_dir)
        r2.addWidget(QLabel("Folder:"))
        r2.addWidget(self.dir_edit, 1)
        r2.addWidget(b2)
        pl.addLayout(r2)

        outer.addWidget(proj)

        qa = QGroupBox("Quick actions")
        qal = QHBoxLayout(qa)
        qal.setSpacing(10)
        btn_extract = QPushButton("Extract")
        btn_extract.setProperty("variant", "primary")
        btn_extract.clicked.connect(self.on_extract)  # type: ignore[attr-defined]
        btn_load = QPushButton("Load values")
        btn_load.clicked.connect(self.on_load_values)  # type: ignore[attr-defined]
        btn_save = QPushButton("Save → memory.dat")
        btn_save.setProperty("variant", "primary")
        btn_save.clicked.connect(self.on_save)  # type: ignore[attr-defined]
        qal.addWidget(btn_extract)
        qal.addWidget(btn_load)
        qal.addWidget(btn_save)
        outer.addWidget(qa)

        outer.addStretch(1)
        return w

    def _build_options_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        g = QGroupBox("Appearance & safety")
        form = QFormLayout(g)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(THEME_NAMES)
        self.cmb_theme.setCurrentText(self._theme_name)
        self.cmb_theme.currentTextChanged.connect(self.on_theme_changed)

        self.chk_dark_mode = QCheckBox("Use dark theme")
        self.chk_dark_mode.setChecked(is_dark_theme(self._theme_name))
        self.chk_dark_mode.toggled.connect(self.on_dark_mode_toggled)

        self.chk_target_best = QCheckBox("Target best-matching JSON block only (safer)")
        self.chk_target_best.setChecked(True)

        form.addRow("Theme", self.cmb_theme)
        form.addRow(self.chk_dark_mode)
        form.addRow(self.chk_target_best)
        outer.addWidget(g)
        outer.addStretch(1)
        return w

    # ---------------------------
    # Sync state
    # ---------------------------

    def mark_unsynced(self, reason: str = "") -> None:
        """Mark the extracted workdir as modified (pending repack)."""
        lbl = getattr(self, "_sync_label", None)
        if lbl is not None:
            lbl.setText("Unsynced" if not reason else f"Unsynced – {reason}")
            lbl.setProperty("state", "dirty")
            self._repolish(lbl)
        if reason:
            try:
                self._msg(f"[State] Unsynced: {reason}")
            except Exception:
                pass

    def mark_synced(self) -> None:
        lbl = getattr(self, "_sync_label", None)
        if lbl is not None:
            lbl.setText("Synced")
            lbl.setProperty("state", "synced")
            self._repolish(lbl)

    def _build_actions_bar(self) -> None:
        """Create a compact toolbar and global shortcuts.

        We intentionally avoid a traditional menu bar to keep the UI vertically compact.
        """
        try:
            # Hide any default menu bar (Windows can reserve height even if empty).
            try:
                self.menuBar().setVisible(False)
            except Exception:
                pass

            act_open = QAction("Open…", self)
            act_open.setShortcut("Ctrl+O")
            act_open.triggered.connect(self.on_open_file)  # type: ignore[attr-defined]
            self.addAction(act_open)

            act_extract_load = QAction("Extract + Load Values", self)
            act_extract_load.setShortcut("Ctrl+E")
            act_extract_load.triggered.connect(self.on_extract_and_load)  # type: ignore[attr-defined]
            self.addAction(act_extract_load)

            act_save = QAction("Save → memory.dat", self)
            act_save.setShortcut("Ctrl+S")
            act_save.triggered.connect(self.on_save)  # type: ignore[attr-defined]
            self.addAction(act_save)


            tb = QToolBar("Main", self)
            tb.setMovable(False)
            self.addToolBar(tb)
            tb.addAction(act_open)
            tb.addAction(act_extract_load)
            tb.addAction(act_save)
        except Exception:
            # Never block app startup on toolbar errors.
            pass

    def _build_currency_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.coins_spin = QSpinBox()
        self.coins_spin.setRange(0, 2_000_000_000)
        self.coins_spin.setValue(999_999_999)

        self.rating_edit = QLineEdit("999999999")
        self.player_exp_edit = QLineEdit("9999999")

        # Debounced auto-apply (currency only). Use textEdited/editingFinished to avoid
        # triggering a full apply on every programmatic setText() or keystroke.
        try:
            self.coins_spin.valueChanged.connect(lambda _=0: self._queue_auto_apply(domain="currency"))
            self.rating_edit.textEdited.connect(lambda _="": self._queue_auto_apply(domain="currency"))
            self.player_exp_edit.textEdited.connect(lambda _="": self._queue_auto_apply(domain="currency"))
            self.rating_edit.editingFinished.connect(lambda: self._queue_auto_apply(domain="currency", delay_ms=50))
            self.player_exp_edit.editingFinished.connect(lambda: self._queue_auto_apply(domain="currency", delay_ms=50))
        except Exception:
            pass

        form.addRow("Coins (int)", self.coins_spin)
        form.addRow("ratingPoints (string)", self.rating_edit)
        form.addRow("playerExp (string)", self.player_exp_edit)
        return w
