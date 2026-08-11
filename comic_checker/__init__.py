__version__ = "0.1.1"


def version_string():
    """バージョン文字列を組み立てる。GUI/CLI両方から呼ばれる唯一の組み立てロジック。

    `_build_info`（CIビルド時に上書きされる）にコミットハッシュ・ビルド日時が
    両方揃っている場合のみそれらを併記する。片方でも欠けていれば__version__のみを
    返す（壊れる方向ではなく情報が少ないだけの安全側の劣化にする）。
    """
    from comic_checker import _build_info

    commit = getattr(_build_info, "BUILD_COMMIT", None)
    build_date = getattr(_build_info, "BUILD_DATE", None)
    if commit and build_date:
        return f"{__version__} ({commit}, {build_date})"
    return __version__
