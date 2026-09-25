# PostToolUseのフック（.claude/settings.json）から`.`で読み込む。司令塔のセッション（`coordinator_session`）で、
# 次の確認の時刻（`next_check`）を過ぎたときだけ`scripts/orchestrate.py check --if-due`を起こす。
# `board claim`の呼び出しのときは、そのセッションを司令塔として記録させる。起こすかどうかの判定はここだけが持つ。
#
# 道具を使うたびに全セッション（サブエージェントの呼び出しを含む）で走るため、何もしないときはプロセスを
# 1つも起こさずに抜ける（シェルの組み込みだけを使う。この開発機ではpythonの起動だけで1秒かかる）。
# 確認を起こすときはorigin/masterの版の道具で動かす（launch.py。本体のチェックアウトの道具は古いことがある）。
# このファイル自体は本体から読まれるので、origin/masterと違えば確認の結果に「入口が古い」と出る。
#
# フックは`/bin/sh -c`で動くので、POSIXのshの組み込みだけで書く（クラウドのUbuntuでは/bin/shがdashで、
# bashの`read -d`・`[[ =~ ]]`・`printf -v`・`$'\r'`が無い）。キーの値は`tool_response`より前（`orch_head`）で探す
# ——展開のたびに文字列を写すので、数十万文字になりうる出力まで写すと1回で百ミリ秒単位になる。

hook_input=
while IFS= read -r orch_line; do
    hook_input="$hook_input$orch_line
"
done
hook_input="$hook_input$orch_line"

# orch_restをJSONのキーの直後に置いて呼ぶ。その値が文字列ならorch_valueへ入れる（`\"`は値の終わりとみなす）。
orch_string_value() {
    orch_value=$orch_rest
    while case "$orch_value" in [[:space:]]*) true ;; *) false ;; esac; do orch_value=${orch_value#?}; done
    case "$orch_value" in :*) orch_value=${orch_value#:} ;; *) return 1 ;; esac
    while case "$orch_value" in [[:space:]]*) true ;; *) false ;; esac; do orch_value=${orch_value#?}; done
    case "$orch_value" in '"'*) orch_value=${orch_value#?} ;; *) return 1 ;; esac
    orch_value=${orch_value%%'"'*}
}
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
# 担当（サブエージェント）の呼び出しは司令塔と同じsession_idを持つので、入力の`agent_id`（サブエージェントの
# 呼び出しにだけ付く）で最初に外す。司令塔の記録は、シェルの道具（Bash・PowerShell）に渡したコマンド（`tool_input.command`）が
# `board claim`のときだけ——入力全体で探すと、そのコマンドの文を含むファイルや出力を読んだ呼び出しでも走る。
case "$hook_input" in *'"agent_id"'*) exit 0 ;; esac
orch_head=${hook_input%%'"tool_response"'*}
case "$orch_head" in
    *'"tool_name"'*'"command"'*)
        orch_rest=${orch_head#*'"tool_name"'}
        orch_string_value || orch_value=
        case "$orch_value" in
            Bash | PowerShell)
                orch_rest=${orch_head#*'"command"'}
                if orch_string_value; then
                    case "$orch_value" in *orchestrate.py[[:space:]]board[[:space:]]claim*) orch_run ;; esac
                fi
                ;;
        esac
        ;;
esac
[ -f "$orch_dir/coordinator_session" ] || exit 0
IFS= read -r orch_session < "$orch_dir/coordinator_session"
orch_session=${orch_session%%[!0-9A-Za-z_-]*}
case "$orch_head" in *'"session_id"'*) ;; *) exit 0 ;; esac
orch_rest=${orch_head#*'"session_id"'}
orch_string_value || exit 0
[ -n "$orch_value" ] && [ "$orch_value" = "$orch_session" ] || exit 0
if [ -f "$orch_dir/next_check" ]; then
    IFS= read -r orch_due < "$orch_dir/next_check"
    orch_due=${orch_due%%[!0-9]*}
    # bash（開発機の/bin/sh）は変数で今の時刻を持つ。無いshだけdateを起こす（ここへ来るのは司令塔のセッションだけ）。
    orch_now=${EPOCHSECONDS:-}
    [ -n "$orch_now" ] || orch_now=$(date +%s)
    [ "$orch_now" -ge "${orch_due:-0}" ] || exit 0
fi
orch_run
