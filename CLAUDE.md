# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A CLI tool that reads a list of manga titles from an Excel file, looks each one up
(primarily on Japanese Wikipedia, falling back to manba.co.jp only when opted in), and
writes back whether the series is completed (完結) or ongoing (連載中). Japanese is the
working language for user-facing strings (README, CLI help, column headers, status
values) — keep new strings consistent with that.

**Pivot history**: this was originally manba.co.jp-only (see git history / Issue #3).
manba.co.jp sits behind a Cloudflare interactive "Verify you are human" challenge that
kept reappearing even with a real human clicking it in `--no-headless` mode — strong
evidence Cloudflare was fingerprinting the Playwright automation itself, not just request
frequency. Rather than reach for stealth/evasion tooling (against the spirit of the
site's bot protections), the design was changed to make Wikipedia's MediaWiki API — which
has no bot protection — the default information source, with manba.co.jp demoted to an
explicit opt-in fallback (`--fallback-to-manba`) for rows Wikipedia can't judge. See
`manba_client.py`'s section below and "Known limitations" for what's still true about the
Cloudflare situation when the fallback path is used.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # dev/test: includes pytest + playwright (full test suite needs it)
playwright install chromium
```

Three requirements files, each `-r`-chaining into the next: `requirements.txt` (light —
`openpyxl` + `requests`, matches the M3 light EXE build and everyday Wikipedia-only usage)
→ `requirements-fallback.txt` (adds `playwright`, needed for `--fallback-to-manba`) →
`requirements-dev.txt` (adds `pytest`). Use `requirements.txt` alone for a runtime-only,
Wikipedia-path-only install (no Playwright/Chromium needed at all). The full test suite
needs `playwright` importable even though `manba_client.py` tests mock `sync_playwright`
— `tests/test_manba_client.py` still does `from comic_checker.manba_client import
ManbaClient` at collection time, which needs the real package installed — so always use
`requirements-dev.txt` (not `requirements.txt`) for development.

Chromium needs OS shared libraries (`libnspr4`, `libnss3`, `libatk1.0-0`, etc.) that are
not installed by pip. Check what's missing without changing the system:

```bash
playwright install-deps --dry-run chromium
```

Installing them (`sudo playwright install-deps chromium`) is a system change — don't run
it without the user's go-ahead.

The search API also requires a key exported as `MANBA_SEARCH_API_KEY` (see README.md
§4 for how to obtain it from the browser's Network tab — it is manba.co.jp's own public
frontend search key, not a secret, but it isn't hardcoded and isn't recorded in this repo).
`ManbaClient` raises `RuntimeError` at construction time if the env var is unset. This is
only needed for `--fallback-to-manba` runs — the default Wikipedia-only path needs
neither Playwright/Chromium nor this env var at all.

## Commands

```bash
python -m pytest                              # run tests
python -m pytest tests/test_excel_io.py -q    # run a single test file
python -m comic_checker.main path/to/file.xlsx           # run the tool
python -m comic_checker.main path/to/file.xlsx --no-headless   # with a visible browser (debugging)
python -m comic_checker.main --help           # full CLI options
```

There is no lint/format tooling configured yet.

## Architecture

モジュール別の設計詳細は `docs/architecture.md` を参照。必要なときだけ読むこと。

## Known limitations worth knowing before "fixing" something

既知の制限（Wikipedia経路・manba.co.jpフォールバック経路）は `docs/known_limitations.md`
を参照。挙動を「直す」前に必ず読むこと。

## 最終目的

Pythonをインストールしていないwindows PCで、EXEをダブルクリックするだけで動作する
GUIツールにする。

## 環境の分離

- 開発・テスト：WSL Ubuntu（このリポジトリ）
- EXEビルド・動作確認：Windows側（PyInstallerはクロスコンパイル不可）
- したがって、コードはWindows/Linux両方で動くように書く
  （パス区切りは os.path / pathlib を使い、`/` をハードコードしない）
- ビルド手順は`docs/build_windows.md`、ビルド設定は`comic_checker.spec`を参照
  （M3: 軽量ビルド。Playwright/Chromiumは同梱しない）。WSL側では実際のWindows向け
  EXEは作れないが、`comic_checker.spec`をそのまま使ってLinux向けバイナリを
  ビルドすることで、依存関係グラフの健全性（`playwright`/`manba_client`が正しく
  除外されているか等）だけは事前に確認できる。生成物（`build/`・`dist/`）は
  確認用途のみでコミットしない（`.gitignore`済み）。

## 過去に詰まった失敗

AI Loop（`scripts/work_loop.sh`）の検証で分かったことなど、過去の失敗と対応は
`ERRORS.md` を参照。似た仕組みを作る／触る前に読むこと。

## 作業ルール

- 変更後は必ず ./scripts/verify.sh を実行してから完了報告する
- コミット・pushは明示的な許可があるときだけ行う
- 秘密情報を読まない・出力しない
