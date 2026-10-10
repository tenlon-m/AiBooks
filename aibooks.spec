# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 - AiBooks 应用图标嵌入与资源包含 (onedir 模式)."""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

hidden = (
    collect_submodules('aiosqlite')
    + collect_submodules('sqlalchemy.ext.asyncio')
    + collect_submodules('greenlet')
    + collect_submodules('ebooklib')
    # 路由模块由 server.py 用 importlib.import_module 动态导入，PyInstaller
    # 的静态扫描看不到，必须显式收集；否则打包后所有 /api/* 接口全部 404
    # （表现为「AI源列表加载失败：API 404」，而源码运行完全正常）。
    + collect_submodules('src.api.routers')
)

a = Analysis(
    ['src/app.py'],
    pathex=[SPECPATH],
    binaries=[],
    datas=[
        ('src/resources', 'src/resources'),
        ('src/prompts', 'src/prompts'),
        ('src/templates', 'src/templates'),
    ] + collect_data_files('src.resources'),
    hiddenimports=hidden + [
        'aiosqlite',
        'aiosqlite.core',
        'aiosqlite.cursor',
        'aiosqlite.context',
        'sqlalchemy.ext.asyncio',
        'sqlalchemy.dialects.sqlite.aiosqlite',
        'ebooklib.epub',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.auto',

        # matplotlib -> dateutil -> six.moves.* 是 six 用 _SixMetaPathImporter
        # 动态生成的伪模块，PyInstaller 静态扫描不到，必须显式声明，
        # 否则打包后 sys.modules 里没有它们，shiboken 的 import hook 会去
        # inspect 这些模块从而触发 AttributeError（详见 src/utils/compat.py）。
        'six',
        'six.moves',
        'dateutil',
        'dateutil.rrule',
        'dateutil.parser',
        'dateutil.tz',
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_qt',
        'matplotlib.backends.qt_editor',
        'matplotlib.backends.qt_editor.figureoptions',
    ],
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
    [],
    exclude_binaries=True,
    name='AiBooks',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='src/resources/app.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AiBooks',
)