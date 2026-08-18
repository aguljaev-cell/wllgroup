# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

root = Path(SPECPATH)

datas = [
    (str(root / "vendor" / "llama"), "vendor/llama"),
    (str(root / "vendor" / "opus"), "vendor/opus"),
]

# Данные библиотек, которые могут понадобиться после упаковки.
datas += collect_data_files("certifi")
datas += collect_data_files("fitz")
datas += collect_data_files("docx")
datas += collect_data_files("sentencepiece")

binaries = []
binaries += collect_dynamic_libs("PySide6")
binaries += collect_dynamic_libs("ctranslate2")

hiddenimports = [
    "fitz",
    "pymupdf",
    "docx",
    "requests",
    "certifi",
    "ctranslate2",
    "sentencepiece",
]
hiddenimports += collect_submodules("PySide6")

a = Analysis(
    ["run.py"],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy.testing",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PDFMathTranslate_WLL",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
