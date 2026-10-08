"""user_config（設定ファイル）のテスト。保存先は conftest の fixture で tmp に差し替わる。"""
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from comic_checker import user_config

# conftest の autouse fixture が差し替える前の、本物の保存先関数。
_real_config_dir = user_config.config_dir


def test_save_and_load_roundtrip():
    assert user_config.get_value(user_config.KEY_RAKUTEN_APP_ID) is None
    user_config.save_values({user_config.KEY_RAKUTEN_APP_ID: "id-value-1"})
    assert user_config.get_value(user_config.KEY_RAKUTEN_APP_ID) == "id-value-1"
    assert user_config.is_set(user_config.KEY_RAKUTEN_APP_ID)
    assert not user_config.is_set(user_config.KEY_RAKUTEN_ACCESS_KEY)


def test_save_keeps_other_items():
    path = user_config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"other": {"a": 1}, "rakuten_app_id": "old"}), encoding="utf-8")
    user_config.save_values({user_config.KEY_RAKUTEN_ACCESS_KEY: "key-2"})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["other"] == {"a": 1}
    assert data["rakuten_app_id"] == "old"
    assert data["rakuten_access_key"] == "key-2"


def test_file_and_item_names():
    user_config.save_values(
        {
            user_config.KEY_RAKUTEN_APP_ID: "a",
            user_config.KEY_RAKUTEN_ACCESS_KEY: "b",
        }
    )
    path = user_config.config_path()
    assert path.name == "config.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "rakuten_app_id": "a",
        "rakuten_access_key": "b",
    }


@pytest.mark.parametrize("content", ["{broken", "[1, 2]", "", "null"])
def test_broken_json_is_unset(content):
    path = user_config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    assert user_config.get_value(user_config.KEY_RAKUTEN_APP_ID) is None
    # 壊れたファイルでも保存はできる
    user_config.save_values({user_config.KEY_RAKUTEN_APP_ID: "x"})
    assert user_config.get_value(user_config.KEY_RAKUTEN_APP_ID) == "x"


@pytest.mark.parametrize("value", [123, None, ["a"], {"a": 1}, ""])
def test_non_string_value_is_unset(value):
    path = user_config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"rakuten_app_id": value}), encoding="utf-8")
    assert user_config.get_value(user_config.KEY_RAKUTEN_APP_ID) is None


def test_broken_file_content_not_in_logs(caplog):
    path = user_config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text("SECRET-LOOKING-TEXT{", encoding="utf-8")
    user_config.get_value(user_config.KEY_RAKUTEN_APP_ID)
    assert "SECRET-LOOKING-TEXT" not in caplog.text


def test_file_permission_is_0600(monkeypatch):
    monkeypatch.setattr(user_config, "_is_windows", lambda: False)
    user_config.save_values({user_config.KEY_RAKUTEN_APP_ID: "x"})
    if os.name != "nt":  # Windows の実機では権限ビットの意味が違うため確かめない
        mode = stat.S_IMODE(user_config.config_path().stat().st_mode)
        assert mode == 0o600


def fake_os(monkeypatch, name, environ):
    monkeypatch.setattr(user_config, "os", SimpleNamespace(name=name, environ=environ))


def test_config_dir_on_windows_uses_appdata(monkeypatch):
    fake_os(monkeypatch, "nt", {"APPDATA": "Roaming-dir"})
    assert _real_config_dir() == Path("Roaming-dir") / "comic_checker"


def test_config_dir_on_windows_without_appdata(monkeypatch, tmp_path):
    fake_os(monkeypatch, "nt", {})
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert _real_config_dir() == tmp_path / "AppData" / "Roaming" / "comic_checker"


def test_config_dir_on_windows_empty_appdata_falls_back(monkeypatch, tmp_path):
    fake_os(monkeypatch, "nt", {"APPDATA": ""})
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert _real_config_dir() == tmp_path / "AppData" / "Roaming" / "comic_checker"


def test_config_dir_on_other_os(monkeypatch, tmp_path):
    fake_os(monkeypatch, "posix", {"APPDATA": "ignored"})
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert _real_config_dir() == tmp_path / ".config" / "comic_checker"
