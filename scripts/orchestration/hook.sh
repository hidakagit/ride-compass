# PostToolUseのフック（.claude/settings.json）から`.`で読み込む。司令塔のセッション（`coordinator_session`）で、
# 次の確認の時刻（`next_check`）を過ぎたときだけ`scripts/orchestrate.py check --if-due`を起こす。
# `board claim`の呼び出しのときは、そのセッションを司令塔として記録させる。起こすかどうかの判定はここだけが持つ。
#
# 道具を使うたびに全セッション（サブエージェントを含む）で走るため、何もしないときはプロセスを
# 1つも起こさずに抜ける（シェルの組み込みだけを使う。この開発機ではpythonの起動だけで1秒かかる）。
# 確認を起こすときはorigin/masterの版の道具で動かす（launch.py。本体のチェックアウトの道具は古いことがある）。
# このファイル自体は本体から読まれるので、origin/masterと違えば確認の結果に「入口が古い」と出る。

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
    # 本体のチェックアウトは古いことがあるので、起動役（launch.py）をorigin/masterから取り出して動かす。
    # 起動役が道具一式もorigin/masterの版で動かす。取り出せない（origin/masterに無い）ときだけ本体の道具で。
    orch_launch="$orch_dir/launch.py"
    if git -C "${CLAUDE_PROJECT_DIR:-.}" show origin/master:scripts/orchestration/launch.py > "$orch_launch.tmp" 2>/dev/null; then
        mv -f "$orch_launch.tmp" "$orch_launch"
        printf '%s' "$hook_input" | python "$orch_launch" --project "${CLAUDE_PROJECT_DIR:-.}"
    else
        rm -f "$orch_launch.tmp"
        printf '%s' "$hook_input" | python "${CLAUDE_PROJECT_DIR:-.}/scripts/orchestrate.py" check --if-due
    fi
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
