# CI（.github/workflows/build-windows.yml）がEXEビルド直前にこのファイルを
# git commitのショートハッシュ・UTC日時で上書きする（このリポジトリへの
# コミットは伴わない、CIランナーのワークスペース上だけの上書き）。
# 上書きされていない状態（手元のsource実行、またはこのステップ導入前の
# ビルド）ではNoneのままで、comic_checker.version_string()はビルド識別無しの
# バージョン番号のみを返す。
BUILD_COMMIT = None
BUILD_DATE = None
