# RideCompass

サイクリング向け周回ルート生成アプリ。backend（FastAPI）+ frontend（Next.js）。構成は docs/architecture/。

タスクは非公開リポジトリ ridecompass/ride-compass-tasks の issue で持つ。進め方は docs/conventions/flow.md。
リファクタリング・機能追加の前に、該当する issue があるかを見る。docs/records/ は 2026-09-28 までの記録で、維持しない。

このファイルは、いつも守る短い決まりと、作業ごとに読む節の表だけを持つ。**作業を始める前に、下の表で当たる行の節を読む。**

## 文書の置き場

| 置き場 | 置くもの |
|---|---|
| CLAUDE.md | 毎回の作業に当てる短い決まりと、読む節の表。長くなるものは docs/ へ出して表から指す |
| docs/conventions/ | 仕事のやり方の規約 |
| docs/architecture/ | 構成・技術選定・外部の制約・設計原則（コードから導けない事実と構造の契約） |
| docs/modules/ | モジュールごとの、今のコードの動き |
| .claude/commands/review.md | 周期レビューの手順。機械で済むチェックは `scripts/review_checks.py` の検知器にする |

- 規約・文書には今の決まりだけを書く。経緯・昔の決まり・失敗例は書かない（それは issue に残る）。
- ルールはリポジトリにだけ置く。Claude の自動の記憶には、開発機の環境の事実だけを置く。

## 出力言語

- **ユーザーへ見せる文は、道具の合間の短い文・進捗・通知（Agent の description・ScheduleWakeup の reason 等）も含めて、すべて日本語で書く。**
  技術用語（ファイル名・コマンド・ライブラリ名）はそのままでよい。英語の文を引くときは `` ` `` かコードブロックで囲む（`scripts/hooks/japanese_only.py` が止める）。
- ユーザーを名前で呼ばない。呼ぶなら「ユーザー」。

## 作業の種類と読む節

当たる行の節を全部読む。節は「ファイル: 節の名前」で指し、ファイル名だけのものは docs/conventions/ にある。文書の末尾の「付録」は、その場面に当たったときだけ読む。

| 作業 | 読む節 |
|---|---|
| タスクを進める（開発機の対話のセッション・裏の作業役も） | flow.md（全文）／pull-requests.md: 作る |
| 新しい仕組みを作る・設計を判断する | docs/architecture/design-principles.md（全文）／.claude/commands/review.md: 判断原則 |
| backend・frontend のコードを足す・変える | docs/modules/README.md: 着手の前に読む（と対象の docs/modules/*.md）／comments.md: ルール・判定基準・残すと決めたものの行き先／logging.md: 基本原則・使う仕組み |
| APIルーター・Pydanticモデル・レジストリ・domain定数・MVT焼き込み値を変える | deployment-sync.md: コミットと同時に揃えるもの |
| 依存の版・デプロイ・実行環境に触る | docs/modules/README.md: このディレクトリが扱わない領域（正本は別にある） |
| キャッシュを足す・変える | caching.md（全文） |
| 外部データソースを使う・使い方を変える | docs/architecture/data-sources.md: 使い方 |
| 評価軸を足す・消す・調整する | deployment-sync.md: コミットと同時に揃えるもの・本番へ効かせたい軸定義の変更は、本番の管理APIへ入れる |
| 指摘・不具合を直す | fixing.md（全文） |
| テストを書く | testing.md: 確かめる高さ・単体で確かめるかを、コードの種類で先に決める・そのテストは要るか（3問を順に）・テストの足場で、本来のNGを覆わない・挙動を変えるなら、テストを先に書く・当たるパターン（パターン1〜）／fixing.md: 書かないテスト |
| テストや検査を回す | testing-operations.md: 手元の検査の回し方・検査の置き場（手元・作業ブランチのCI・masterのCI）・開発機でのbackendテストの回し方／testing.md: テストが落ちたときの直し方（①〜⑥）・警告は既定でエラー |
| 画面を撮る | pull-requests.md: 画面を撮る |
| コミットする・PR を出す | flow.md: コミット／pull-requests.md: 作る（4〜6）／deployment-sync.md: コミットと同時に揃えるもの |
| PR を確かめてマージする | pull-requests.md: 確かめる・競合を解く・PR のあと |
| 本番を読む・書く | flow.md: 開発機の対話のセッション／docs/modules/backend/cross-cutting-infrastructure.md の `run_probe.py` の行／docs/architecture/tech-stack.md: 本番の宛先／deployment-sync.md: 本番へ効かせたい軸定義の変更は、本番の管理APIへ入れる・派生データの作り直し |
| 文書を書く | 上の「文書の置き場」／documentation.md（全文）／comments.md: 残すと決めたものの行き先 |
| 流れの道具（`tools/flow-gate`・担当のワークフロー）を変える | docs/architecture/task-flow.md（全文） |
| 作業ツリーを作る・依存を入れる | docs/architecture/setup.md: 作業ツリーどうしで node_modules を共有しない |
| 周期レビューをする | .claude/commands/review.md（全文） |

## 作業の進め方

- 数分以上かかる処理は、始める前に何を・どの順で・どれくらいかかるか（未計測ならそう言う）を伝え、区切りごとに知らせる。実行中の重い処理を止める・やり直すかはユーザーに問う。Actions の担当は裏の道具を持たないので、終わるまで前に出したまま待つ。
- 長く待つときも黙らず、止まったらその時点で報告する。状態や残りの一覧は、見せる前に読み直す。
- 「◯◯は2か所にある」「唯一の定義だ」のような構造の主張は、grep か AST で数えてから言う。実測の無い数字（所要時間も）は出さず「未計測」と言う。
- 測る前に母集団の定義を書く。0件だったときは、列挙器が拾えない形（参照で渡す関数・文字列で指す属性等）でないかを、既知の1件で検算する。
- ツール・外部サービス・データ源は、公式の文書・ソースを先に読んでから言う・設計する・手順を渡す。標準で済むものは自前で作らない。画面の操作は公式のメニュー名で渡す。
- 仕組み化されたものを先に使う: 規模・churn は `scripts/review_checks.py metrics`、本番 DB の調査は `backend/scripts/run_probe.py`、文書の整合は `scripts/review_checks.py docs`。同じ操作を3回やったら仕組み化を考え、作った道具はどこから呼ぶかまで決める。
- 確かめに要る最小の対象（1ファイル・1関数・1件）だけを回す。手元にある結果を取り直さない。
- 長いスクリプト・ヒアドキュメントは Write でファイルに書いてから実行する（[setup.md](docs/architecture/setup.md)「Windowsの開発機でのBashの長さの上限」）。

## 作業ツリーの安全

並行セッションが同じ作業ツリーを触りうる。

- `git add -A` を使わず、変えたパスを明示してステージし、コミットの前に `git diff --cached --stat` を読む。コミットは作業ブランチの専用の作業ツリーで行う。調べの使い捨ての spec を `frontend/e2e/` へ置かない。
- 自分が変更していないファイルの変更を戻さない（`git checkout --`・`git reset`・`git stash`・`git clean` 等）。対応が要るなら報告してユーザーに確かめる。
- 変更を目的としない作業（調査・レビュー）は専用の `git worktree` で行う。読むだけの調べを Agent に任せるときは Explore を使い、実装を任せるときは `isolation: "worktree"` を付ける。
- 新しいタスクは、今あるタスクのどれにも属さず、今の作業では片付かないものにだけ起こす。進め方の指示（待つ・続ける・順番）は issue にもコミットにもしない。
