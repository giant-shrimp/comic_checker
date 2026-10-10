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


def positive_int(value):
    """argparse の type 用。1以上の整数だけ受け付ける。

    整数でない値は int() の ValueError のまま（argparse が従来どおり扱う）。
    1未満は ArgumentTypeError にして、日本語のメッセージで終了コード 2 にする。
    """
    import argparse

    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("1以上の整数を指定してください")
    return number
