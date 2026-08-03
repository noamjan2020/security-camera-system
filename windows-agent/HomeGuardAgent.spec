# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all


datas, binaries, hiddenimports = collect_all('cv2')
for optional_package in ('onnxruntime', 'qrcode', 'aiortc', 'av', 'websockets'):
    try:
        package_datas, package_binaries, package_hidden = collect_all(optional_package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hidden
    except Exception:
        pass

models = Path('models')
if models.exists():
    for model in models.glob('*.onnx'):
        datas.append((str(model), 'models'))

hiddenimports += [
    'uvicorn.logging',
    'uvicorn.loops.auto',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto',
    'PIL.ImageTk',
]

a = Analysis(
    ['src/homeguard_agent/desktop.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HomeGuardAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='HomeGuardAgent')
