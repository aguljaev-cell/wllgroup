# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    ['run.py'],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'vendor' / 'llama'), 'vendor/llama')],
    hiddenimports=['fitz', 'docx'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDFMathTranslate_WLL',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
