# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_root = Path.cwd().parent
assets_dir = project_root / 'assets'
docs_dir = project_root / 'docs'
data_dir = project_root / 'data'
gui_dir = project_root / 'app' / 'gui'
core_dir = project_root / 'app' / 'core'

hiddenimports = [
    'gnss_gui_v3_5_6',
    'data_importer',
    'time_validator',
    'outlier_detector',
    'butterworth_filter',
    'median_filter',
    'processing_log',
    'data_exporter',
    'shiboken6',
    'matplotlib.backends.backend_qtagg',
    'matplotlib.backends.backend_agg',
    'matplotlib.backends.qt_compat',
    'pandas._config',
    'pandas._config.localization',
    'pandas.testing',
    'pandas._testing',
    'pandas._libs.tslibs.timedeltas',
    'pandas._libs.tslibs.nattype',
    'pandas._libs.tslibs.np_datetime',
    'pandas._libs.skiplist',
]

def add_dir_if_exists(src, dest):
    src = Path(src)
    if src.exists():
        return [(str(src), dest)]
    return []

datas = []
datas += add_dir_if_exists(assets_dir, 'assets')
datas += add_dir_if_exists(docs_dir, 'docs')
datas += add_dir_if_exists(data_dir / 'input', 'data/input')
datas += add_dir_if_exists(data_dir / 'output', 'data/output')

a = Analysis(
    ['../app/gui/gnss_gui_v3_5_6.py'],
    pathex=[str(project_root), str(gui_dir), str(core_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pandas.tests',
        'pytest',
        'hypothesis',
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DRender',
        'PySide6.QtCharts',
        'PySide6.QtConcurrent',
        'PySide6.QtDBus',
        'PySide6.QtDesigner',
        'PySide6.QtHelp',
        'PySide6.QtHttpServer',
        'PySide6.QtLocation',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNetworkAuth',
        'PySide6.QtNfc',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtPositioning',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtQuickControls2',
        'PySide6.QtQuickTest',
        'PySide6.QtRemoteObjects',
        'PySide6.QtScxml',
        'PySide6.QtSensors',
        'PySide6.QtSerialBus',
        'PySide6.QtSerialPort',
        'PySide6.QtSql',
        'PySide6.QtStateMachine',
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
        'PySide6.QtTest',
        'PySide6.QtTextToSpeech',
        'PySide6.QtUiTools',
        'PySide6.QtWebChannel',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebSockets',
        'PySide6.QtWebView',
        'PySide6.QtXml',
        'tkinter',
        '_tkinter',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GNSS_GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='../assets/app.ico',
    version='version_info.txt',
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GNSS_GUI',
)