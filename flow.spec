# -*- mode: python ; coding: utf-8 -*-


from PyInstaller.utils.hooks import copy_metadata

_metadata = []
for _package in ('gdown', 'requests', 'urllib3', 'beautifulsoup4', 'pillow', 'soupsieve'):
    _metadata += copy_metadata(_package, recursive=True)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('logo.ico', '.'), ('extension', 'extension'),
           ('camera_motions.example.json', '.'), ('prompt_templates.example.json', '.'),
           ('plugin_script_adapter.js', '.'), ('FLOW_PLUGIN_OPEN_API.md', '.')] + _metadata,
    hiddenimports=['PIL', 'bs4', 'gdown', 'requests', 'PyQt6.QtWebSockets', 'PyQt6.QtNetwork', 'views', 'views.main_window', 'views.project_detail_widget', 'views.import_dialog', 'views.settings_dialog', 'views.template_config_dialog', 'views.video_check_dialog', 'views.video_compare_widget', 'models', 'models.storage_manager', 'models.project_model', 'models.config_manager', 'models.template_manager', 'services', 'services.text_processor', 'services.downloader', 'services.speech_extractor', 'services.video_checker', 'services.plugin_server', 'services.pipeline_scheduler', 'services.updater', 'services.browser_closer', 'views.hosted_mode_widget', 'views.batch_generate_tab', 'views.pipeline_tab_widget', 'views.close_confirm_dialog', 'views.update_dialog'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='flow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='flow',
)
