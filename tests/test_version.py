import pytest

from comic_checker import _build_info, __version__, version_string
from comic_checker.main import parse_args


def test_version_is_pinned():
    """契約: パッケージのバージョン番号は"0.1.0"に固定されている。

    このテストが単独で検知できる壊れ方: __version__の値が意図せず変わる
    リグレッション（他の全表示箇所がこの値に依存するため、単独でpinする）。
    """
    assert __version__ == "0.1.0"


def test_version_string_is_bare_when_build_info_is_placeholder(monkeypatch):
    """契約: _build_info.BUILD_COMMIT/BUILD_DATEが両方Noneのとき（CI未適用時の
    プレースホルダ状態）、version_string()はバージョン番号のみを返す——
    例外を投げず、「情報が少ないだけの安全側の劣化」になる。

    このテストが単独で検知できる壊れ方: プレースホルダ状態でNone同士を
    文字列結合してしまい、"0.1.0 (None, None)"のような壊れた表示になる
    リグレッション。
    """
    monkeypatch.setattr(_build_info, "BUILD_COMMIT", None)
    monkeypatch.setattr(_build_info, "BUILD_DATE", None)
    assert version_string() == "0.1.0"


def test_version_string_includes_commit_and_date_when_both_present(monkeypatch):
    """契約: BUILD_COMMIT・BUILD_DATEが両方揃っているとき、version_string()は
    両方を併記した文字列を返す。

    このテストが単独で検知できる壊れ方: CIがビルド情報を埋め込んでも、
    version_string()側が握りつぶしてバージョン番号のみを返してしまう
    リグレッション（ビルド識別が一切表示されなくなる）。
    """
    monkeypatch.setattr(_build_info, "BUILD_COMMIT", "a1b2c3d")
    monkeypatch.setattr(_build_info, "BUILD_DATE", "2026-08-11T00:00:00Z")
    assert version_string() == "0.1.0 (a1b2c3d, 2026-08-11T00:00:00Z)"


def test_version_string_is_bare_when_only_commit_is_present(monkeypatch):
    """契約: BUILD_COMMITのみが設定されBUILD_DATEがNoneのまま（片方だけ上書き
    される不整合な状態）でも、version_string()はバージョン番号のみを返す
    （中途半端な併記をしない）。

    このテストが単独で検知できる壊れ方: `commit and build_date`の`and`が
    `or`に壊れ、片方だけの状態で"0.1.0 (a1b2c3d, None)"のような不完全な
    併記をしてしまうリグレッション。
    """
    monkeypatch.setattr(_build_info, "BUILD_COMMIT", "a1b2c3d")
    monkeypatch.setattr(_build_info, "BUILD_DATE", None)
    assert version_string() == "0.1.0"


def test_version_string_is_bare_when_only_date_is_present(monkeypatch):
    """契約: BUILD_DATEのみが設定されBUILD_COMMITがNoneのままでも、
    version_string()はバージョン番号のみを返す。

    このテストが単独で検知できる壊れ方: 上と対称の壊れ方——`commit and
    build_date`の判定がcommit側だけを見る形に壊れ、BUILD_DATEだけがある
    状態を見落として不完全な併記をしてしまうリグレッション。
    """
    monkeypatch.setattr(_build_info, "BUILD_COMMIT", None)
    monkeypatch.setattr(_build_info, "BUILD_DATE", "2026-08-11T00:00:00Z")
    assert version_string() == "0.1.0"


def test_main_version_flag_prints_version_and_exits(capsys):
    """契約: `--version`はargparseの標準versionアクションとして動作し、
    "comic_checker <version>"を標準出力へ書いてSystemExitで終了する
    （excel_path等の他の必須引数を要求しない）。

    このテストが単独で検知できる壊れ方: --version引数自体の削除、または
    version文字列の中身がバージョン番号を含まなくなるリグレッション。
    """
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "comic_checker 0.1.0" in captured.out
