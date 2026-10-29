"""テスト全体の前提。

Issue #40 で`_api_get`にリクエスト間隔（1秒）と429時のバックオフ（5秒×試行回数）を
入れた。`requests.get`だけをモックしている既存テストは、そのままだと**実時間で待つ**
（この変更の直後、テストが0.2秒から53秒に伸びた）。

## 待機を止める方法として`time.sleep`のパッチを採らなかった理由

最初は `patch("comic_checker.wikipedia_client.time.sleep")` で無効化していたが、
**これは`time`モジュール本体の属性を差し替えるのでプロセス全域に効く**
（`wikipedia_client.time is time` が True。`manba_client`の待機まで巻き添えになる）。
フィクスチャの説明は「`_api_get`の待機を無効化する」と読めるのに実際の範囲が広く、
将来「待つべき箇所で待っていない」バグが入ったときに、それを観測しづらくする。

代わりに**`wikipedia_client`の間隔定数だけを0にする**。`time.sleep(0)`は実際に呼ばれる
ので、待機の呼ばれ方を検証するテストは従来どおり観測できる。範囲はこのモジュールに閉じる。

## 待機そのものを検証するテストは opt-out する

`@pytest.mark.real_wait_settings` を付けたテストには適用しない。それらのテストは
`time.sleep`を自分で差し替えて記録するので、実時間を待つことはない。
"""
import pytest

from comic_checker import bookwalker_client, user_config, wikipedia_client


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_wait_settings: 待機の間隔・バックオフを本番の値のまま使う"
        "（待機そのものを検証するテスト用）",
    )
    config.addinivalue_line(
        "markers",
        "bookwalker_fetch: BOOK☆WALKER の取得関数（fetch_search_page）を差し替えない"
        "（requests.get をモックして取得関数そのものを検証するテスト用）",
    )


@pytest.fixture(autouse=True)
def _isolated_user_config_dir(tmp_path, monkeypatch):
    """設定ファイルの保存先を tmp のディレクトリに差し替える。

    開発機の実際の設定ファイル（楽天ブックスのキー）を読み書きしないため。
    保存先の組み立てそのものを検証するテストは `user_config.config_dir` を自分で差し替える。
    """
    config_dir = tmp_path / "user_config_dir"
    monkeypatch.setattr(user_config, "config_dir", lambda: config_dir)
    return config_dir


@pytest.fixture(autouse=True)
def _no_real_waiting(request, monkeypatch):
    """`_api_get`の待機を実時間0にする。適用範囲は`wikipedia_client`の定数のみ。"""
    if "real_wait_settings" in request.keywords:
        return
    monkeypatch.setattr(wikipedia_client, "API_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(wikipedia_client, "API_RETRY_BACKOFF_SECONDS", 0)


@pytest.fixture(autouse=True)
def _no_bookwalker_network(request, monkeypatch):
    """BOOK☆WALKER へは通信しない。待機も実時間0にする。

    Wikipedia が記事なしの行では `main._judge_row` が BOOK☆WALKER を見に行く。
    `judge` だけをモックしている既存のテストが本物の bookwalker.jp に問い合わせないよう、
    既定では取得関数を「取得できない」（RuntimeError）に差し替える。そのとき `lookup` は
    エラーを返し、行は記事なしのまま変わらない。

    取得関数そのものを検証するテストは `@pytest.mark.bookwalker_fetch` を付けて、
    `requests.get` を自分でモックする。
    """
    if "real_wait_settings" not in request.keywords:
        monkeypatch.setattr(bookwalker_client, "REQUEST_INTERVAL_SECONDS", 0)
        monkeypatch.setattr(bookwalker_client, "RETRY_BACKOFF_SECONDS", 0)
    if "bookwalker_fetch" in request.keywords:
        return

    def refuse(query):
        raise RuntimeError("テストでは BOOK☆WALKER に通信しない")

    monkeypatch.setattr(bookwalker_client, "fetch_search_page", refuse)
