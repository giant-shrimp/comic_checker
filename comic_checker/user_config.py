"""利用者ごとの設定ファイル（楽天ブックスAPIのキーの保存先）。

保存先はWindowsなら `%APPDATA%\\comic_checker\\config.json`、それ以外なら
`~/.config/comic_checker/config.json`。値は暗号化せず平文のJSONで保存する
（Windows以外ではファイルの権限を 0o600 にする）。

ファイルがない・JSONとして読めない・値が文字列でないときは「未設定」として扱う。
ファイルの中身は、例外の文面にもログにも出さない。
"""
import json
import os
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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if not _is_windows():
        path.chmod(_FILE_MODE)
