---
name: test-review
description: "backend のテストを、変異テストの全部の測りで見直す（測りを起こす・待つ・結果を読む・消す／直すタスクにする・記録する）。テストの定期の見直しをするとき・テストの見直しを頼まれたときに使う。"
---

## テストの見直しを回す

導く原則: 1・4・5。

backend のテストを、.claude/rules/testing-review.md「テストを変異テストで見直す」の4つの観点（効き・重なり・隔離・書き方）で見直す1回の
手順。開発機の対話のセッションが、この手順だけで始めから終わりまで進める。測りは GitHub Actions のワークフロー
`.github/workflows/mutation.yml`（先頭に2段の中身と持ち時間）が回し、台本は `backend/scripts/mutation/`（各ファイルの先頭に使い方）。
測りの結果から何を消す・直すかの決まりは testing-review.md が持ち、ここには書かない。

### 1. 始める

1. **記録する issue を決める**: 頼まれたときに issue の番号があればそれ。無ければ .claude/skills/file-issue/SKILL.md「issue の形」の
   とおり、種類は保守、題名「テストの定期の見直し（<日付>）」で起こす（やること: この節の 2〜6、完了の条件: 変異を回し終えた
   測りの 6 の記録と、5 で起こしたタスクの番号があること）。
2. **持つ**: .claude/skills/dev-session/SKILL.md「開発機の対話のセッション」の「持つ」で持ち、進行中へ動かす。
3. **計画を伝える**（CLAUDE.md「作業の進め方」）: 何をどの順で、どれくらいかかるか。見込みは前回の見直しの記録（6 の実際の時間）
   から出し、無ければ `mutation.yml` の先頭の持ち時間から出す。どちらにもランナーの空き待ちが足される。

### 2. 測りを起こす

    gh workflow run mutation.yml -R ridecompass/ride-compass --ref master -f ref=master

- `-f ref=` で渡す測る版・一覧の口・成果物の保持の日数は .claude/skills/run-checks/SKILL.md「変異テストでテストの効きを測る」。
- 起こした実行の id は、`gh run list -R ridecompass/ride-compass --workflow mutation.yml -L 1 --json databaseId,createdAt,status` で
  取り、`createdAt` が起こした時刻のあとであることを見る。
- 同じワークフローが動いていれば、終わるまで待ってから始まる（`concurrency: mutation`）。
- 測りは、アカウントで同時に動かせるジョブの枠を担当（Claude Task）・CI と分け合う。起こすときに動いている実行の数
  （`gh run list -R ridecompass/ride-compass --status in_progress`）を、空き待ちの原因として 6 の記録に書く。

### 3. 待つ

Monitor で次を回す（ジョブが終わるたびに1行出し、実行が終われば抜ける）。

    id=<id>; prev=""; while true; do
      cur=$(gh run view $id -R ridecompass/ride-compass --json jobs -q '.jobs[] | select(.status=="completed") | "\(.name): \(.conclusion)"' 2>/dev/null | sort) || { sleep 60; continue; }
      comm -13 <(echo "$prev") <(echo "$cur"); prev=$cur
      st=$(gh run view $id -R ridecompass/ride-compass --json status,conclusion -q '"\(.status) \(.conclusion)"')
      case $st in completed*) echo "実行: ${st#completed }"; break;; esac
      sleep 300
    done

（開発機に jq は無いので、`gh` の `-q` で読む。Monitor の持ち時間は最長30分なので、切れたら同じコマンドで張り直す。）

終わった本の記録は、実行全体が終わる前でも
`gh api --allow-escape-sequences repos/ridecompass/ride-compass/actions/jobs/<ジョブの id>/logs` で読める（`gh run view --log` は
実行全体が終わるまで読めない。ジョブの id は `gh run view <id> --json jobs`）。本の中の手順ごとの始まりと終わりは
`gh api repos/ridecompass/ride-compass/actions/jobs/<ジョブの id>` の `steps` で見られ、1つの手順が見込み（3 の見込み・`mutation.yml`
の先頭の持ち時間）より長く止まっていれば、下の「落ちたとき」に当たるかを見る。

落ちたとき:

- **shard の1本が「The runner has received a shutdown signal」で止まった**（変異がランナーのメモリを使い切った）:
  `gh run rerun <id> -R ridecompass/ride-compass --failed` で落ちた本と、それに続く段だけをやり直す。同じ本が続けて止まるなら、
  その本の記録（`gh run view <id> --job <ジョブの id> --log`）の最後の「始め <変異>」の変異が原因なので、台本の直しを要る直しとして
  下の「止める」。
- **shard の1本が、DB を用意する手順（`./.github/actions/postgis`）の10分の上限で落ちた**（apt の取得が詰まった）:
  同じく `gh run rerun <id> -R ridecompass/ride-compass --failed` で1回やり直す。続けて落ちるなら、次の「それ以外」と同じに扱う。
- **1つの手順が上限の無いまま、見込みより長く止まっている**: 起こしたのは自分なので、`gh run cancel <id> -R ridecompass/ride-compass`
  で止め、止まったのを見てから `gh run rerun <id> -R ridecompass/ride-compass --failed` で、止めた本と続く段をやり直す（止まった本は
  ランナーの枠を使い続け、担当や CI の待ちを延ばす）。担当や CI の実行は止めない。
- **それ以外で落ちた**: `gh run view <id> -R ridecompass/ride-compass --log-failed` で読む。台本・ワークフローの誤りなら、その回の
  中で直さず、その直しを要る直しとして下の「止める」。
- **review の段の要約に「変異を回し終えていない」と出た**（stop_after で抜けた本がある）: その回の見直しは比べに使えない。
  持ち時間か本数を変える直しを要る直しとして下の「止める」。

止める: 要る直しを .claude/skills/file-issue/SKILL.md「起票する」のとおり起こし、記録する issue の前提（blocked by）に張る
（「前後関係と組」）。6 の1 の記録を止めた理由と直しの番号まで書き、記録する issue は閉じずに終える
（前提が開いている間は振り出されない）。直しが閉じたら、同じ issue で 2 から測り直す。

### 4. 結果を読む

    gh run download <id> -R ridecompass/ride-compass -n mutation-review -D <作業ツリーの外の使い捨ての場所>

- `summary.md`: 実行の要約と同じ表（観点ごとのテスト関数の数と行数・効きの変異スコア・判断できずに残したテストの理由）。
- `review.json` には次の欄がある。`measured`（測った版）・`previous`（比べた前回の版。無ければ null）・`complete`・`candidates`（今回の重なりの候補。
  テスト関数ごとに `hash`・`lines`・`height`・消したあとの確かめに使う `mutant` と、それを見つける残すテスト `kept_test`）・
  `delete`（消す一覧）・`writing.zero`・`writing.broad_only`（書き方の候補）・`isolation`（隔離の候補）。
- `analyze.txt`: 層ごとの変異スコアと、テストの区分ごとの数。

### 5. 観点ごとに行き先を決める

決まりは testing-review.md「テストを変異テストで見直す」。ここでは、出た一覧をどこへ渡すかだけを決める。隔離と書き方のタスクは
.claude/skills/file-issue/SKILL.md「起票する」のとおり起こし、記録する issue へ前後関係を張らず、本文に「<記録する issue> の見直し
（実行 <id>）から」と書く。

| 観点 | 一覧 | 行き先 |
|---|---|---|
| 効き | `analyze.txt` の変異スコア・生き残り | タスクにしない（変えた所は Pull Request ごとの Mutation PR が見る） |
| 重なり | `delete` | 空なら何もしない（前回が無い・2回続けて候補になったものが無い）。あれば、記録する issue を親にして、消す段階を作り、記録する issue の完了の条件に「消す段階が全部閉じている」の行を足す（下の「消す段階」） |
| 隔離 | `isolation` | あれば、1つのタスクに並べて起こす。やることは run-checks/SKILL.md「実行順をばらす」の汚した側の探し方 |
| 書き方 | `writing.zero`・`writing.broad_only` | あれば、1つのタスクに並べて起こす。やることは testing-review.md の書き方（1本ずつ3問へ通し、型として決まったものを「消すべきテストの型」と構造の検査に足す） |

**消す段階**（.claude/skills/file-issue/SKILL.md「段階に分ける」）:

- テストのファイルの並びで、1段階あたりテスト関数の行（`lines` の和）が約600行までに分ける。
- 段階の本文のやることに、消すテスト関数の表（テスト関数・行数・高さ・`mutant`・`kept_test`）と、次の確かめを書く。
  1. 表のテスト関数を消す。
  2. 表の `mutant` を1行ずつ `only.txt`（run-checks/SKILL.md「変異テストでテストの効きを測る」の一覧の口）に書いて作業ブランチへ push し、
     `gh workflow run mutation.yml -R ridecompass/ride-compass --ref master -f ref=<作業ブランチ>` で回す。
     成果物 `mutation-*` の `results.jsonl` で表の変異が全部 `killed` で、`kills/` にその行の `kept_test` があることを見る。
  3. `only.txt` を消してから Pull Request を出す。テスト全体が通ることは Pull Request の CI が見る。CI で
     落ちたときは testing-review.md「重なり」のとおりにする。
  4. Pull Request の本文の検証に、testing-review.md「消す・まとめる前に、残す側が落ちるかを見る」の表を、2 の変異と結果で書く。

### 6. 記録して終える

1. 記録する issue へコメントする: 実行の id と URL・測った版・比べた前回の版・ジョブごとの実際の時間（空き待ちと分けて）と
   起こすときに動いていた実行の数・`summary.md` の表・5 で起こした（コメントを足した）タスクの番号・3 で止めたならその理由。
   成果物は消える（保持の日数は run-checks/SKILL.md「変異テストでテストの効きを測る」）ので、数はコメントに残す。
2. 記録する issue の完了の条件の済んだ行にチェックを付ける（全部済めばゲートが閉じる）。
   消す段階を作ったときは「消す段階が全部閉じている」の行が残るので付けず、段階が全部閉じたあとで担当が確かめて付ける
   （file-issue「段階に分ける」）。どちらも、終えたら持ちを手放す（dev-session「持つ」）。
3. ユーザーへ報告する: 前回の記録する issue の 1 のコメントと比べた観点ごとの数の違いと、そこから言える結論を先に、次に起こしたタスク・
   止めたならその理由。
