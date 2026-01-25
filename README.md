# CarX Drift PS4 Save Tool  
**Created by ProtoBuffers**

A modern, **offset-safe CarX Drift (PS4) save editor** for working with `memory*.dat` files.  
It is designed to be **round-trip safe**: it extracts the embedded blocks into a working folder, lets you edit selected values, and repacks **without shifting offsets** or rewriting unchanged regions.

---

## Supported input formats

- **Standard decrypted PS4 save**: `memory*.dat`
- **Save Wizard container**: `memory*.dat` that includes the `FALLEN` container format  
  - Uses the `FALLEN` header table when available (preferred), with a safe fallback to sentinel scanning.

> This tool does **not** decrypt or encrypt PS4 saves for you. You must start from a decrypted/usable `memory*.dat`.

---

## Key capabilities

### Core workflow (safe extract → edit → repack)
- Extracts embedded save blocks from `memory*.dat` into a working folder (`blocks/`) and records a `manifest.json`
- Repack is **offset-safe** and **slot-size safe**:
  - Base64 regions retain their original sizing rules
  - GZIP + UTF-16LE content is preserved for text blocks
- **Byte-identical round-trip when you make no edits**
  - Repack will **skip unchanged blocks** and preserve the original bytes

### Save Wizard / `FALLEN` safety
- Table-driven parsing of `FALLEN` segments when present (more reliable than raw delimiter scanning)
- Preserves non-JSON auxiliary chunks (e.g., `FALLEN 00 00`) and other non-editable regions
- For editable `FALLEN` text blocks, repack overwrites only the **JSON payload prefix** and preserves any tail bytes exactly

### Built-in editor (GUI)
- Clean, tabbed PyQt6 interface
- Dark / Light mode toggle

**Coins / Rating / XP**
- `coins` (int)
- `ratingPoints` (string)
- `playerExp` (string)
- Debounced auto-apply for currency edits (reduces accidental corruption from partial edits)

**Time / Races / Cups / Points**
- `timeInGame` (seconds + readable duration)
- `racesPlayed`
- `driftRacesPlayed`
- `timeAttackRacesPlayed`
- `MPRacesPlayed`
- `cups1`, `cups2`, `cups3`
- `maxPointsPerDrift`, `maxPointsPerRace`, `averagePointsPerRace`

**Garage & Unlocks**
- Locate or create an unlock container (when the save schema supports it)
- Unlock **ALL Cars** and/or **ALL Tracks** using known IDs
- Merge mode (add-only) to reduce risk when different saves store unlock lists differently
- Fast filtering/search for large lists
- Context actions to label unknown IDs via the database

**Engine Parts**
- View and edit `m_items` engine-part entries
- Filters:
  - `engine_part_*` only
  - Text search
- Raw JSON view for inspection (when needed)

**Car Slots (Progression)**
- Slot limit editing (unlocks the slot limit value so it can be changed)
- Custom car caption support:
  - Scans extracted blocks for caption entries
  - Displays `carId - caption`
  - Allows editing and applying captions

**Advanced Unlocks**
- Schema-aware unlock application with source selection
- Merge recommended by default; optional removal mode when you explicitly enable it

**Data Browser**
- Explore extracted blocks as:
  - Tree (JSON)
  - Pretty JSON
  - Raw text
  - Hex preview (binary)
- Edit primitive JSON values safely
- Undo last change (session)
- Revert a file to original (session)
- Context actions:
  - Copy JSON path / value preview
  - Set key labels
  - Set car/track labels in the ID database

### Databases & labeling
- Ships with editable JSON databases (stored in `data/`) to improve readability:
  - `id_database.json` (IDs → names/labels)
  - `engine_parts_db.json`
  - `tunes_db.json`
  - `observed_db.json` (auto-populated observations)
- The UI can update labels as you discover new IDs (no hardcoding required)

### Diagnostics & guardrails
- `manifest.json` records per-block metadata (offsets, sizes, SHA1 signatures) to support safe repacking
- Repack preflight detects:
  - “Block too large” edits (you exceeded the original allocation)
  - Base file mismatches (guardrails against repacking against the wrong base)
- Includes a `roundtrip_smoke_test.py` helper for quick sanity checks

---

## Quick start (GUI)

1. **Select Base Save**  
   Choose your original `memory*.dat` (this defines the fixed layout and block sizes).

2. **Choose Working Folder**  
   The tool writes extracted block files and `manifest.json` here.

3. **Extract**  
   Extracts and decodes embedded blocks safely.

4. **Edit**  
   Use tabs for common edits, or use **Data Browser** for targeted changes.

5. **Repack**  
   Produces a new `memory.dat` while preserving offsets and unchanged bytes.

---

## Project structure (high level)

```
carx drift debug/
├── app.py                      # Application entry point
├── carx_drift.spec             # PyInstaller build spec
├── core/
│   ├── extract.py              # memory.dat extractor (SaveWizard FALLEN-aware)
│   ├── repack.py               # offset-safe repacker + preflight validation
│   ├── memory_codec.py         # Base64 + GZIP helpers
│   ├── json_ops.py             # safe JSON read/write helpers
│   ├── id_database.py          # IDs → labels database
│   ├── observed_db.py          # auto-observed IDs/paths
│   ├── engine_parts_db.py      # engine parts DB helpers
│   └── ...                     # supporting modules
├── ui/
│   ├── main_window.py          # GUI + core editing fields
│   ├── tabs/                   # editor tabs (stats, unlocks, engine parts, etc.)
│   └── browser/                # Data Browser (inspect/edit JSON safely)
└── data/
    ├── id_database.json
    ├── engine_parts_db.json
    ├── observed_db.json
    └── tunes_db.json
```

---

## Building the EXE (PyInstaller)

### Requirements
- Python 3.10+
- PyQt6
- PyInstaller 6.x

### Build
```powershell
pyinstaller carx_drift.spec
```

Output (typical):
```
dist/
└── CarX_Drift_Editor/
    └── CarX_Drift_Editor.exe
```

---

## Troubleshooting / limitations

- **Always keep backups** of your original save.
- If repack reports **“block too large”**, your edits exceeded the original allocation for that slot.
  - Use a different base save with larger allocations, or reduce the edit size.
- Unlock list schemas can vary between saves/versions; the tool provides merge modes and schema selection to reduce risk, but not every save will store unlock lists identically.

---

## Credits / disclaimer
Created by **ProtoBuffers**. Reverse engineering, tooling, UI, and save format analysis.

This project is intended for educational and personal use only.
