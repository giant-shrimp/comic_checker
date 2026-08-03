#!/usr/bin/env bash
#
# ループ（scripts/work_loop.sh）専用の git 書き込み経路。
#
# 【これは AI が呼ぶスクリプトではない】
# work_loop.sh の --allowedTools には入れていない。commit / push / PR作成はすべて
# 「verify.sh が通り、かつ変更があった」と work_loop.sh が判定した後の話であり、
# その判定はエージェントのターンが終わってから行われる。つまりエージェントには
# 成功を知る手段が無く、これらを呼ぶ必要が最初から無い。
# 入口を作らなければ、`./scripts/loop_git.sh commit x ; gh pr merge 70` のような
# 複合コマンドが権限パターンにどう照合されるかという未検証の性質に、安全を
# 預けなくて済む（照合の実測結果は docs/work_loop_testing.md 5-f を参照）。
# したがって、このスクリプトが守る相手はエージェントではなく **work_loop.sh 自身の
# バグ** である。
#
# 【なぜ権限パターンではなくスクリプトで縛るのか】
# `Bash(git push -u origin loop/*)` のような allow を並べても、
# `git push origin HEAD:main` という書き方が残る。.claude/settings.json の
# _note_deny_scope が既に書いているとおり「列挙で塞ぎ切ることは原理的にできない」。
# 過去に ALLOW_COMMIT=1 という環境変数で work_loop.settings.json の読み込みを
# 丸ごと止める迂回路を作り、66分後に撤去した経緯もある（3341902 → 6d7ef64）。
# あれはオール・オア・ナッシングだったのが問題で、正しい形は
# 「許す操作だけを別の入口として作り、生の git は deny のまま残す」である。
#
# 【構造で強制していること】
#   - main では動かない。ブランチ名が loop/<issue> でなければ動かない
#   - push は引数を一切取らない。refspec を外から与えられないので
#     `HEAD:main` も `--force` も `--tags` も構文的に渡せない
#   - 余分な引数は黙って無視せずエラーにする（無視すると呼び出し側のバグが静かに残る）
#   - PR は --draft 固定。マージは人間が GitHub GUI で行う（ADR-001）
#   - push 前に core.hooksPath を確認する。.githooks/pre-push が main 直push を
#     止める層（ADR-001）なので、それが無効な状態では push しない
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# ループが作業するブランチの形。issue番号だけを許し、それ以外の名前では動かない。
LOOP_BRANCH_RE='^loop/[0-9]+$'
# pre-push フック（ADR-001）が有効であることの条件。
EXPECTED_HOOKS_PATH=".githooks"

usage() {
  cat >&2 <<'USAGE'
usage: ./scripts/loop_git.sh <subcommand>

  commit <message-file>   現在のループブランチにコミットする
  tag <iteration>         loop/<issue>/iter-<iteration> を現在のHEADに打つ
  push                    現在のループブランチを origin へ push する（引数なし）
  pr <issue>              draft PR を作る

work_loop.sh から呼ばれることを想定している（AIの --allowedTools には入れていない）。
USAGE
  exit 64
}

die() {
  echo "loop_git.sh: $*" >&2
  exit 1
}

# 現在のブランチを返す。同時に「ループブランチであること」を強制する。
require_loop_branch() {
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD)"

  # main は明示的に弾く。下の正規表現でも落ちるが、事故のときに読むのは
  # エラーメッセージなので、何を守ったのかが分かる文言を出す。
  if [ "$branch" = "main" ]; then
    die "main では実行できません。ループは loop/<issue> ブランチ上でだけ動きます。"
  fi
  if [ "$branch" = "HEAD" ]; then
    die "detached HEAD では実行できません（ブランチ上にいません）。"
  fi
  if ! [[ "$branch" =~ $LOOP_BRANCH_RE ]]; then
    die "ブランチ名が loop/<issue> ではありません: ${branch}"
  fi

  printf '%s' "$branch"
}

# loop/<issue> から issue番号を取り出す。
issue_from_branch() {
  local branch="$1"
  printf '%s' "${branch#loop/}"
}

cmd_commit() {
  [ "$#" -eq 1 ] || die "commit はメッセージファイルを1つだけ取ります（渡された引数: $#）"
  local message_file="$1"
  local branch
  branch="$(require_loop_branch)"

  [ -f "$message_file" ] || die "コミットメッセージのファイルがありません: ${message_file}"
  [ -s "$message_file" ] || die "コミットメッセージのファイルが空です: ${message_file}"

  # 追跡ファイルの変更と新規ファイルの両方を対象にする。.gitignore 済みのものは
  # -A でも入らないので、logs/ がループ自身のログで混ざる心配はない。
  git add -A

  # 何も staged されていなければ、コミットせずに戻る（呼び出し側が no-op を判定する）。
  if git diff --cached --quiet; then
    echo "loop_git.sh: コミットする変更がありません（${branch}）。"
    return 0
  fi

  git commit --file="$message_file"
  echo "loop_git.sh: ${branch} にコミットしました（$(git rev-parse --short HEAD)）。"
}

cmd_tag() {
  [ "$#" -eq 1 ] || die "tag はイテレーション番号を1つだけ取ります（渡された引数: $#）"
  local iteration="$1"
  local branch issue tag
  branch="$(require_loop_branch)"
  issue="$(issue_from_branch "$branch")"

  [[ "$iteration" =~ ^[0-9]+$ ]] || die "イテレーション番号が数字ではありません: ${iteration}"

  tag="loop/${issue}/iter-${iteration}"
  # 打ち直しを許す（同じイテレーションを再実行した場合に落ちても得がない）。
  git tag -f "$tag" >/dev/null
  echo "loop_git.sh: タグ ${tag} を $(git rev-parse --short HEAD) に打ちました。"
}

cmd_push() {
  # 【引数を取らないことが安全性の中身】refspec を外から渡せないので、
  # HEAD:main も --force も --tags も構文的に指定できない。余分な引数を
  # 黙って無視すると呼び出し側のバグが静かに残るため、エラーにする。
  [ "$#" -eq 0 ] || die "push は引数を取りません（渡された引数: $*）"

  local branch hooks_path
  branch="$(require_loop_branch)"

  # ADR-001 の main 保護は .githooks/pre-push である。core.hooksPath が
  # 設定されていなければフックは呼ばれない（クローンごとに setup_hooks.sh が必要）。
  # 検査が成立しない状態では push しない。
  hooks_path="$(git config core.hooksPath || true)"
  if [ "$hooks_path" != "$EXPECTED_HOOKS_PATH" ]; then
    die "core.hooksPath が ${EXPECTED_HOOKS_PATH} ではありません（現在: '${hooks_path:-未設定}'）。
  ./scripts/setup_hooks.sh を実行してください。pre-push フックが無効な状態では
  push しません（ADR-001）。"
  fi

  # --no-verify は渡さない。フックを迂回する手段はこのスクリプトには無い。
  git push -u origin "$branch"
  echo "loop_git.sh: ${branch} を origin へ push しました。"
}

cmd_pr() {
  [ "$#" -eq 1 ] || die "pr はissue番号を1つだけ取ります（渡された引数: $#）"
  local issue="$1"
  local branch subject title body
  branch="$(require_loop_branch)"

  [[ "$issue" =~ ^[0-9]+$ ]] || die "issue番号が数字ではありません: ${issue}"

  subject="$(git log -1 --pretty=%s)"
  # コミット件名が既に #<issue> で始まっていれば二重に付けない。
  if [[ "$subject" == "#${issue} "* ]]; then
    title="${subject}"
  else
    title="#${issue} ${subject}"
  fi

  body="$(cat <<EOF
このPRは \`scripts/work_loop.sh\` が Issue #${issue} に対して作成したものです。

- \`./scripts/verify.sh\` が通ったイテレーションの内容だけが push されています
  （検証が失敗した版は origin に出ません）
- 途中の版はローカルのタグ \`loop/${issue}/iter-N\` から取り出せます
  （タグは push していません）
- **draft のままにしてあります。レビューとマージは人間が GitHub GUI で行ってください**
  （ADR-001）
EOF
)"

  # --draft 固定。マージは人間が行う（ADR-001）。
  gh pr create --draft --base main --head "$branch" --title "$title" --body "$body"
}

main() {
  [ "$#" -ge 1 ] || usage
  local subcommand="$1"
  shift

  case "$subcommand" in
    commit) cmd_commit "$@" ;;
    tag)    cmd_tag "$@" ;;
    push)   cmd_push "$@" ;;
    pr)     cmd_pr "$@" ;;
    *)      echo "loop_git.sh: 不明なサブコマンド: ${subcommand}" >&2; usage ;;
  esac
}

main "$@"
