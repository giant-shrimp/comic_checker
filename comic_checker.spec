# -*- mode: python ; coding: utf-8 -*-
#
# 軽量ビルド（M3）: Wikipedia経路のみ。Playwright/Chromiumは同梱しない。
# --fallback-to-manba はこのビルドのEXEでは使用できない（起動時ではなく、
# 実際に --fallback-to-manba を指定した時点で明確なエラーメッセージが出る。
# comic_checker/main.py の _import_manba_client() 参照）。
#
# ビルド手順・検証チェックリストは docs/build_windows.md を参照。
# WSL/Linux上ではWindows向けのEXEは生成できない（PyInstallerはクロスコンパイル
# 不可）。ここでは依存関係グラフの健全性を確認するためにLinuxバイナリとして
# 一度ビルド・起動確認済み（`comic_checker.manba_client`が
# "excluded module ... (delayed, optional)" として除外されることを確認した）。
#
# ビルドコマンド（Windows/Linux共通、生成物のOSはビルドを実行したOSに従う）:
#   pyinstaller comic_checker.spec
#
# onefile（本ファイルの設定）は単一の .exe をダブルクリックするだけで良い
# 反面、起動のたびに一時ディレクトリへの自己展開が挟まるため初回起動が遅く、
# Windows Defender SmartScreen等に誤検知されやすい傾向がある（PyInstaller
# onefileビルドで既知の問題）。M4の実機検証でこれが問題になった場合は、
# EXE(..., exclude_binaries=True) + COLLECT(...) の形（onedir）に切り替える
# ことを検討する。

a = Analysis(
    ['comic_checker/gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # playwrightそのものと、それをimportするcomic_checker.manba_clientを
    # 明示的に除外する。main.py側でmanba_clientのimportを遅延化してあるため、
    # 除外してもWikipedia経路の起動・実行には影響しない。
    excludes=['playwright', 'comic_checker.manba_client'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='comic_checker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUIのみ表示し、背後にコンソールウィンドウを出さない
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
