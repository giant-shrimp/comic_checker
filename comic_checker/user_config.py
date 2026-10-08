"""利用者ごとの設定ファイル（楽天ブックスAPIのキーの保存先）。

保存先はWindowsなら `%APPDATA%\\comic_checker\\config.json`、それ以外なら
`~/.config/comic_checker/config.json`。値は暗号化せず平文のJSONで保存する
（Windows以外では、権限 0o600 の一時ファイルに書いてから置き換えるので、
他のユーザが読める瞬間も、途中で失敗して設定が壊れることもない）。

ファイルがない・JSONとして読めない・値が文字列でないときは「未設定」として扱う。
ファイルの中身は、例外の文面にもログにも出さない。
"""
import json
import os
import tempfile
from pathlib import Path

CONFIG_DIR_NAME = "comic_checker"
CONFIG_FILE_NAME = "config.json"

KEY_RAKUTEN_APP_ID = "rakuten_app_id"
KEY_RAKUTEN_ACCESS_KEY = "rakuten_access_key"

_FILE_MODE = 0o600


def _is_windows():
    return os.name == "nt"


def config_dir():
    """設定ファイルを置くディレクトリを返す。保存先の決定はここ1か所にまとめる。"""
    if _is_windows():
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata)
        else:
            base = Path.home() / "AppData" / "Roaming"
        return base / CONFIG_DIR_NAME
    return Path.home() / ".config" / CONFIG_DIR_NAME


def config_path():
    return config_dir() / CONFIG_FILE_NAME


def _read_all():
    """設定ファイル全体を dict で返す。読めないときは空の dict。"""
    try:
        text = config_path().read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get_value(key):
    """文字列の値を返す。未設定・空・文字列でないときは None。"""
    value = _read_all().get(key)
    if isinstance(value, str) and value:
        return value
    return None


def is_set(key):
    return get_value(key) is not None


def save_values(values):
    """values（キー -> 文字列）を保存する。ファイルにある他の項目は残す。

    保存できなければ OSError を投げる（文面にはパスが入りうるが、値は入らない）。
    """
    data = _read_all()
    data.update(values)
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = config_path()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    # 同じディレクトリの一時ファイル（最初から 0o600）に書いてから置き換える。
    # 途中で失敗しても既存の設定は壊れず、他のユーザが読める瞬間もない。
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".tmp")
    try:
        if not _is_windows():
            os.chmod(tmp_name, _FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
