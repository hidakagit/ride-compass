# PostToolUseのフック（.claude/settings.json）から`.`で読み込む。司令塔のセッションで、確認間隔を
# 過ぎたときだけ`scripts/orchestrate.py check --if-due`を起こす。
#
# 道具を使うたびに全セッション（サブエージェントを含む）で走るため、何もしないときはプロセスを
# 1つも起こさずに抜ける（シェルの組み込みだけを使う。この開発機ではpythonの起動だけで1秒かかる）。
# 判定の正本はorchestrate.pyの側で、ここは起こすかどうかの前段にすぎない。

IFS= read -r -d '' hook_input
orch_git="${CLAUDE_PROJECT_DIR:-.}/.git"
if [ -f "$orch_git" ]; then
    IFS= read -r orch_line < "$orch_git"
    orch_git="${orch_line#gitdir: }"
    if [ -f "$orch_git/commondir" ]; then
        IFS= read -r orch_common < "$orch_git/commondir"
        case "$orch_common" in
            /* | ?:*) orch_git="$orch_common" ;;
            *) orch_git="$orch_git/$orch_common" ;;
        esac
    fi
fi
orch_dir="$orch_git/orchestration"
[ -f "$orch_dir/board.json" ] || exit 0

orch_run() {
    printf '%s' "$hook_input" | python "${CLAUDE_PROJECT_DIR:-.}/scripts/orchestrate.py" check --if-due
    exit 0
}
case "$hook_input" in *"orchestrate.py board claim"*) orch_run ;; esac
case "$hook_input" in *'"agent_id"'*) exit 0 ;; esac
[ -f "$orch_dir/coordinator_session" ] || exit 0
IFS= read -r orch_session < "$orch_dir/coordinator_session"
orch_session="${orch_session%$'\r'}"
[[ $hook_input =~ \"session_id\"[[:space:]]*:[[:space:]]*\"([^\"]+)\" ]] || exit 0
[ "${BASH_REMATCH[1]}" = "$orch_session" ] || exit 0
if [ -f "$orch_dir/next_check" ]; then
    IFS= read -r orch_due < "$orch_dir/next_check"
    orch_due="${orch_due%$'\r'}"
    printf -v orch_now '%(%s)T' -1
    [ "$orch_now" -ge "${orch_due:-0}" ] || exit 0
fi
orch_run
