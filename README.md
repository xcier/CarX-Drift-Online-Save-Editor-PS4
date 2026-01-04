# CarX Drift PS4 Save Tool  
**Created by ProtoBuffers**

A modern, offset-safe **CarX Drift PS4 save editor** that allows you to extract, edit, and repack `memory*.dat` saves without corruption.

This tool is designed to be **safe, transparent, and user-friendly**, using PyQt6 with a dark-mode UI and strict repacking rules that preserve the original save structure.

---

## ✨ Features

- ✅ Extracts embedded save data from `memory*.dat`
- ✅ Editable UI for key gameplay values:
  - Coins
  - Rating Points
  - Player XP
  - Time played (seconds → readable time)
  - Races played (normal / drift / time attack / MP)
  - Cups (1 / 2 / 3)
  - Max & average points
- ✅ Unlock all cars & tracks (when supported by the base save)
- ✅ Offset-safe repacking (prevents PS4 corruption)
- ✅ Dark / Light mode toggle
- ✅ Clean, tabbed interface
- ✅ No unnecessary fields (`purchasesCount` intentionally excluded)

---

## 📁 Project Structure

carx_drift_tool/
├── app.py # Application entry point
├── core/
│ ├── extract.py # memory.dat extractor
│ ├── repack.py # offset-safe repacker
│ ├── apply_presets.py # JSON update logic
│ ├── memory_codec.py # Base64 + GZIP handling
│ └── presets.py # Unlock lists / constants
├── ui/
│ └── main_window.py # PyQt6 GUI
├── carx_drift.spec # PyInstaller build spec
└── README.md

yaml
Copy code

---

## 🚀 How to Use (GUI)

### 1️⃣ Select Base Save
- Choose your **original `memory*.dat`**
- This file defines the fixed layout and block sizes

### 2️⃣ Choose Working Folder
- This is where extracted blocks and `manifest.json` will be stored

### 3️⃣ Extract
- Click **Extract**
- The tool decompresses embedded save blocks safely

### 4️⃣ Edit Values
- Use the **Coins / Rating / XP** tab
- Use the **Time / Races / Cups / Points** tab
- Time is edited in **seconds** and shown as a readable duration

### 5️⃣ (Optional) Unlock Cars & Tracks
- Uses known unlock lists
- Requires a compatible base save

### 6️⃣ Repack
- Click **Repack**
- Produces a new `memory.dat` with:
  - Original offsets preserved
  - Fixed Base64 region sizes
  - UTF-16LE + GZIP encoding preserved

---

## 🛡️ Why This Tool Is Safe

This editor **never shifts offsets** inside `memory.dat`.

Internally it guarantees:
- Base64 regions remain the **exact same size**
- Extra space is padded safely
- Original GZIP metadata is preserved
- Text is always repacked as **UTF-16LE**

This is why saves built with this tool load correctly on PS4.

---

## 🌓 Dark / Light Mode

- Dark mode is enabled by default
- Toggle available in the UI
- Uses Qt Fusion style for consistency on Windows

---

## 🔧 Building the EXE (PyInstaller)

### Requirements
- Python 3.10+
- PyQt6
- PyInstaller 6.x

### Build
```powershell
pyinstaller carx_drift.spec
Output:

markdown
Copy code
dist/
└── CarX_Drift_PS4_Save_Tool/
    └── CarX_Drift_PS4_Save_Tool.exe
⚠️ Important Notes
Always use a clean base save when testing

If repacking reports “block too large,” your edits exceeded the original slot size

Use a different base save with larger allocations if needed

📜 Credits
Created by ProtoBuffers
Reverse engineering, tooling, UI, and save format analysis.

This project is intended for educational and personal use only.