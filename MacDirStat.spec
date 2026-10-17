# -*- mode: python ; coding: utf-8 -*-
"""Spec de PyInstaller para MacDirStat (macOS, build .app en modo onedir).

La build oficial se hace con ./build_macos.sh, que valida herramientas,
ejecuta las pruebas rápidas, genera el icono y verifica arquitectura/firma.
"""

from pathlib import Path

ROOT = Path(SPECPATH)
VERSION = "1.0.0"
BUNDLE_ID = "com.sergiovalle.macdirstat"

# La app carga el icono con QIcon desde `resources/icons/app.svg`; en modo
# congelado `resource_path()` usa sys._MEIPASS, por lo que el destino es
# `resources/icons` y no `app/resources/icons`.
datas = [(str(ROOT / "app" / "resources" / "icons" / "app.svg"), "resources/icons")]

# Módulos Qt que la aplicación no usa: evita arrastrar cientos de MB.
excludes = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtHttpServer",
    "PySide6.QtLocation", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtPositioning",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2", "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio", "PySide6.QtSql", "PySide6.QtStateMachine",
    "PySide6.QtTest", "PySide6.QtTextToSpeech", "PySide6.QtUiTools",
    "PySide6.QtWebChannel", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
    "tkinter", "unittest", "pydoc_data",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MacDirStat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # build_macos.sh puede sobrescribir con --target-arch
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MacDirStat",
)

app = BUNDLE(
    coll,
    name="MacDirStat.app",
    icon=str(ROOT / "build" / "AppIcon.icns"),
    bundle_identifier=BUNDLE_ID,
    version=VERSION,
    info_plist={
        "CFBundleName": "MacDirStat",
        "CFBundleDisplayName": "MacDirStat",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHumanReadableCopyright": "© 2026 Sergio Valle",
    },
)
