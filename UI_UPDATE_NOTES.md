# UI Update Notes

This build keeps the existing CarX save-editing logic intact and updates the PyQt6 interface layer.

## Changed

- Added `ui/themes.py` with a centralized theme engine.
- Added four themes:
  - Midnight Drift
  - Carbon Violet
  - Emerald Garage
  - Clean Light
- Reworked `app.py` to use the centralized theme instead of a duplicated hard-coded stylesheet.
- Reworked `ui/main_window.py` shell styling:
  - cleaner app header card
  - softer card-style group boxes
  - modern rounded controls
  - cleaner tables/lists/trees
  - improved toolbar/status bar styling
  - scrollable top tabs for long tab names
  - synced/unsynced pill indicator
- Added a theme dropdown under `Options`.
- Removed the heavy black-outline look from the default controls.

## Notes

The sandbox used to package this update does not have PyQt6 installed, so I syntax-checked the code with Python `compileall` but could not launch the live window here.
