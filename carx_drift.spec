# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for CarX Drift PS4 Save Tool
# Bundles code + data folders (databases/resources) recursively.
#
# Build:
#   pyinstaller --clean --noconfirm carx_drift_spec_fixed.spec

import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Run PyInstaller from repo root so this points to your project.
project_root = os.getcwd()

# ---------------------------
# Hidden imports
# ---------------------------
hiddenimports = []
hiddenimports += collect_submodules("PyQt6")

# ---------------------------
# Data files (databases/resources)
# PyInstaller 6.16 expects datas entries as 2-tuples: (src_file, dest_dir).
# ---------------------------
datas = []

def add_tree(rel_path: str, dest_root: str | None = None) -> None:
    """Recursively add rel_path folder into datas, preserving structure."""
    src_root = os.path.join(project_root, rel_path)
    if not os.path.isdir(src_root):
        return

    dest_root = dest_root or rel_path

    for root, _, files in os.walk(src_root):
        for fn in files:
            src_file = os.path.join(root, fn)
            # destination directory inside the bundle
            rel_dir = os.path.relpath(root, src_root)
            if rel_dir == ".":
                dest_dir = dest_root
            else:
                dest_dir = os.path.join(dest_root, rel_dir)
            datas.append((src_file, dest_dir))

# Common locations used in this project over iterations
add_tree("data", "data")
add_tree("database", "database")
add_tree("resources", "resources")
add_tree(os.path.join("app", "resources"), "app/resources")
add_tree(os.path.join("app", "resources", "database"), "app/resources/database")
add_tree("assets", "assets")

a = Analysis(
    ["app.py"],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="CarX_Drift_PS4_Save_Tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app
    # icon=os.path.join(project_root, "assets", "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CarX_Drift_PS4_Save_Tool",
)
