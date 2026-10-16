# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Flow口播工具
Generates a one-folder distributable with all dependencies.
"""

import os, sys
from PyInstaller.utils.hooks import copy_metadata

block_cipher = None
project_dir = os.path.abspath('.')

# gdown 等库在导入时会用 importlib.metadata 读取自身版本，必须把包元数据一起打包，
# 否则运行时报 "No package metadata was found for gdown"
_meta = []
for _pkg in ['gdown', 'requests', 'urllib3', 'beautifulsoup4', 'tqdm', 'filelock',
             'certifi', 'idna', 'charset-normalizer', 'soupsieve', 'pillow', 'PySocks']:
    try:
        _meta += copy_metadata(_pkg)
    except Exception:
        pass

a = Analysis(
    ['main.py'],
    pathex=[project_dir],
    binaries=[],
    datas=[
        ('logo.ico', '.'),
        ('camera_motions.example.json', '.'),
        ('prompt_templates.example.json', '.'),
        ('plugin_script_adapter.js', '.'),
        ('FLOW_PLUGIN_OPEN_API.md', '.'),
        ('README.md', '.'),
        ('LICENSE', '.'),
        ('extension', 'extension'),
    ] + _meta,
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWebSockets',
        'PyQt6.QtNetwork',
        'PyQt6.QtMultimedia',
        'PyQt6.QtMultimediaWidgets',
        'PyQt6.sip',
        'PIL',
        'PIL.Image',
        'bs4',
        'gdown',
        'requests',
        'asyncio',
        'json',
        'pathlib',
        'uuid',
        'base64',
        'logging',
        'traceback',
        'ctypes',
        'models',
        'models.config_manager',
        'models.project_model',
        'models.storage_manager',
        'models.template_manager',
        'services',
        'services.downloader',
        'services.browser_closer',
        'services.pipeline_scheduler',
        'services.plugin_server',
        'services.speech_extractor',
        'services.text_processor',
        'services.video_checker',
        'views',
        'views.main_window',
        'views.close_confirm_dialog',
        'views.hosted_mode_widget',
        'views.batch_generate_tab',
        'views.pipeline_tab_widget',
        'views.project_detail_widget',
        'views.import_dialog',
        'views.settings_dialog',
        'views.template_config_dialog',
        'views.video_check_dialog',
        'views.video_compare_widget',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'IPython',
        'notebook',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FlowCue',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,         # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.ico',       # Application icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FlowCue',
)
