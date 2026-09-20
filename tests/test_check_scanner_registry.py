"""scripts/check_scanner_registry.sh のテスト。

ADR-024決定1（走査器の偽陽性の事前登録簿）・Issue #271の実装。走査器
（scripts/check_no_personal_info.py）自体は変更せず、その検出結果を
docs/scanner_false_positive_registry.md（既知の偽陽性の登録簿）と突き合わせる
薄い層を検査する。

検査項目は2つ。
- 未登録検出: 走査器が検出したが登録簿に無い（ファイル, ハッシュ）の組
- 陳腐化登録: 登録簿にあるが、現在は検出されない（ファイル, ハッシュ）の組

いずれも見逃してはならない（ADR-024決定1の設計要件）。同定はファイルパスと、
検出行の内容のSHA-256ハッシュ（先頭16桁）で行い、行番号には依存しない。

乖離時の挙動はフィクスチャ（tmp_path に書き出すダミーの対象ファイル・登録簿）
で検証し、実リポジトリの値には依存しない。フィクスチャの内容は実在の個人名・
作品名・敬称を含まない架空のものを使う。

負の対照は検査ごとに1つずつ用意し、その検査だけが鳴り他方は鳴らないことを
標準エラーの内容で確認する。

テスト方式は tests/test_errors_inventory.py と同じく pytest から subprocess で
シェルスクリプトを呼ぶ形。
"""
import hashlib
import importlib
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_scanner_registry.sh"
SCANNER_PY = REPO_ROOT / "scripts" / "check_no_personal_info.py"
REGISTRY_MD = REPO_ROOT / "docs" / "scanner_false_positive_registry.md"

REGISTRY_HEADER = (
    "| ファイル | ハッシュ | 型 | 理由 |\n"
    "|---|---|---|---|\n"
)

# 実在の個人名・作品名・敬称を含まない、架空のメールアドレスの形。
# email型を検出させるためのフィクスチャ本文（EMAIL_PATTERNに一致する形）。
FIXTURE_EMAIL_LINE = "contact = sample.fixture@fake-domain.invalid"
FIXTURE_EMAIL_HASH = hashlib.sha256(FIXTURE_EMAIL_LINE.encode("utf-8")).hexdigest()[:16]

# 検出を含まない、無関係なフィクスチャ本文。
FIXTURE_CLEAN_LINE = "no detection expected in this line"

# 登録簿には存在するが、どのフィクスチャファイルからも実際には検出されない
# ダミーのハッシュ（陳腐化登録のフィクスチャ用）。
STALE_HASH = "0" * 16


def _run(env_overrides=None):
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
    )


def _write_fixture(tmp_path, target_content, registry_rows):
    target = tmp_path / "sample.txt"
    target.write_text(target_content, encoding="utf-8")

    registry = tmp_path / "registry.md"
    registry.write_text(REGISTRY_HEADER + "\n".join(registry_rows) + "\n", encoding="utf-8")

    return {
        "REGISTRY_MD": str(registry),
        "SCANNER_PY": str(SCANNER_PY),
        "BASE_DIR": str(tmp_path),
        "TARGET_FILES": "sample.txt",
    }


def test_repo_registry_matches_current_scan():
    """正の対照。実リポジトリで終了コード0になり、かつ登録簿の(ファイル,ハッシュ)
    集合が、走査器を独立に呼び出して算出した現在の検出集合と完全に一致する
    （テスト側でも独立に算出して突き合わせる）。

    対象範囲は本番の抑制層と同じく、git追跡ファイル（`git ls-files`）と
    git未追跡ファイル（`git ls-files --others --exclude-standard`）の両方。
    """
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "OK", proc.stdout + proc.stderr

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    scanner = importlib.import_module("check_no_personal_info")

    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=str(REPO_ROOT), check=True
    ).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), check=True,
    ).stdout.splitlines()
    tracked = tracked + untracked

    actual = set()
    for relpath in tracked:
        try:
            hits = scanner.scan_path(str(REPO_ROOT / relpath))
        except OSError:
            continue
        for _path, _lineno, line in hits:
            if scanner.HOME_PREFIX_PATTERN.search(line):
                pass
            elif scanner.EMAIL_PATTERN.search(line):
                pass
            elif scanner._honorific_hit(line):
                pass
            else:
                continue
            digest = hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
            actual.add((relpath, digest))

    registered = set()
    in_table = False
    for line in REGISTRY_MD.read_text(encoding="utf-8").splitlines():
        if line.startswith("| ファイル "):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        registered.add((parts[1].strip(), parts[2].strip()))

    assert actual, "検出が1件も無いなら本テストが空振りしている"
    assert actual == registered, (
        "登録簿と現在の検出が一致しない: "
        "登録簿のみ=%s / 検出のみ=%s"
        % (sorted(registered - actual)[:5], sorted(actual - registered)[:5])
    )


def test_unregistered_detection_dummy_exits_nonzero(tmp_path):
    """負の対照1。登録簿に無い検出を持つフィクスチャで非ゼロ終了する。"""
    env = _write_fixture(
        tmp_path,
        target_content=FIXTURE_EMAIL_LINE + "\n",
        registry_rows=(),
    )
    proc = _run(env)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "未登録検出" in proc.stderr, proc.stderr
    assert "sample.txt" in proc.stderr, proc.stderr
    assert FIXTURE_EMAIL_HASH in proc.stderr, proc.stderr
    assert "email" in proc.stderr, proc.stderr
    # 検出行の本文は出さない。
    assert FIXTURE_EMAIL_LINE not in proc.stderr, proc.stderr
    # 陳腐化登録は鳴っていない（落ち方が観測可能に異なる）。
    assert "陳腐化登録" not in proc.stderr, proc.stderr


def test_untracked_file_in_scope_dummy_exits_nonzero(tmp_path):
    """負の対照3。既定の対象範囲（TARGET_FILES未設定）が、gitの未追跡ファイルも
    含むことを確認する。隔離された一時gitリポジトリ（実リポジトリには触れない）
    に未追跡ファイルを置き、そこに未登録の検出があれば非ゼロ終了する。
    """
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    target = tmp_path / "untracked_sample.txt"
    target.write_text(FIXTURE_EMAIL_LINE + "\n", encoding="utf-8")
    # git add はしない。未追跡のままにする。

    registry = tmp_path / "registry.md"
    registry.write_text(REGISTRY_HEADER, encoding="utf-8")

    env = {
        "REGISTRY_MD": str(registry),
        "SCANNER_PY": str(SCANNER_PY),
        "BASE_DIR": str(tmp_path),
        "GIT_SCAN_ROOT": str(tmp_path),
    }
    proc = _run(env)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "未登録検出" in proc.stderr, proc.stderr
    assert "untracked_sample.txt" in proc.stderr, proc.stderr
    assert FIXTURE_EMAIL_HASH in proc.stderr, proc.stderr
    assert "email" in proc.stderr, proc.stderr
    # 検出行の本文は出さない。
    assert FIXTURE_EMAIL_LINE not in proc.stderr, proc.stderr
    # 陳腐化登録は鳴っていない（落ち方が観測可能に異なる）。
    assert "陳腐化登録" not in proc.stderr, proc.stderr


def test_stale_registration_dummy_exits_nonzero(tmp_path):
    """負の対照2。登録簿に載っているが検出されない項目を持つフィクスチャで
    非ゼロ終了する。
    """
    env = _write_fixture(
        tmp_path,
        target_content=FIXTURE_CLEAN_LINE + "\n",
        registry_rows=(
            "| sample.txt | %s | email | 架空のフィクスチャ用ダミー登録（テスト専用）。 |"
            % STALE_HASH,
        ),
    )
    proc = _run(env)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "陳腐化登録" in proc.stderr, proc.stderr
    assert "sample.txt" in proc.stderr, proc.stderr
    assert STALE_HASH in proc.stderr, proc.stderr
    assert "email" in proc.stderr, proc.stderr
    # 未登録検出は鳴っていない（落ち方が観測可能に異なる）。
    assert "未登録検出" not in proc.stderr, proc.stderr


def test_matching_dummy_inputs_exit_zero(tmp_path):
    """検出とその登録が一致するダミー入力では OK・終了コード0。"""
    env = _write_fixture(
        tmp_path,
        target_content=FIXTURE_EMAIL_LINE + "\n",
        registry_rows=(
            "| sample.txt | %s | email | 架空のフィクスチャ用ダミー登録（テスト専用）。 |"
            % FIXTURE_EMAIL_HASH,
        ),
    )
    proc = _run(env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "OK"


def test_does_not_modify_repo_files():
    """引数なし実行後もリポジトリ本体の登録簿・走査器は不変。"""
    before_registry = REGISTRY_MD.read_bytes()
    before_scanner = SCANNER_PY.read_bytes()
    _run()
    assert REGISTRY_MD.read_bytes() == before_registry
    assert SCANNER_PY.read_bytes() == before_scanner
