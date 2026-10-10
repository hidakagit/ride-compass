---
name: run-checks
description: "検査とテストを手元・作業ブランチのCI・masterのCIのどこでどう回すか、CIの結論の読み方、開発機でのbackendテスト、変異テスト、E2Eと画面の撮影の走らせ方、テストDBの準備。検査やテストを回す前・CIの結果を読む前に使う。"
---

# テストと検査の回し方

手元とCIで、検査とテストをどこでどう回すかを持つ。何を確かめるか・テストが要るか・書き方は
[testing.md](../../rules/testing.md)と、そこから分けた`testing-*.md`が持つ。

## 手元の検査の回し方

- **手元とCIで同じ答えを2回買わない**: CIはPull Requestで毎回、静的検査（`.github/workflows/ci.yml`のジョブ
  （backend・frontend）がテスト（`pytest`・`npm test`）より前に回す段・`api-contract`のOpenAPI生成物のドリフト・
  `.github/workflows/docs-consistency.yml`の段）とフルスイートを回す（[task-work/SKILL.md](../task-work/SKILL.md)「作る担当」の4・5。
  どの変更で何が走るかは下の「検査の置き場」）。手元では、CIの結論より先に知らないと作業が無駄になる答えだけを、
  その答えに要る最小の範囲で取る。
- **回してよい場面は3つ**。どれでもなければ回さずにpushし、CIの結論を待つ。
  1. **CIが落ちた失敗を再現して直すとき**（[testing.md](../../rules/testing.md)「テストが落ちたときの直し方」）。回すのは落ちた失敗に届く範囲だけ。
  2. **テストそのものを書く・書き換えるとき**（新しいテスト・起こし直し・足場の作り直し）。書いた形をほかのファイルへ
     写す前に、書いたファイルが動くかを見る。回すのは書いた・直したテストファイルだけで、1ファイルを書くたびにそのファイルを回してよい。
  3. **怪しいところがあって、CIの前に念を入れて確かめたいとき**（並べ替えで落ちそうな共有の状態・時計に依存する境界等）。
     回すのはその怪しいところに届くテストだけで、何を怪しんで回したかをPull Requestの本文の検証に書く。
- **回さないもの**: フルスイート（backendの`tests`全体・frontendの`vitest run`全体）と、pushの前の念のための全体。
  1行・1ファイル変えただけで全体を流し直さない。静的検査も、1の再現と下の`tsc`の例外のほかは回さない。
- **コミットの前に、frontendで変えたファイルへ整形をかける**: CIの`format:check`（`frontend/package.json`）が見る
  `src/**/*.{ts,tsx,css}`に当たる変えたファイルへ、`./node_modules/.bin/prettier --write <変えたファイル>`をかけてからコミットする。
  `format:check`（`--check`）は回さない。
- 回すときは、どの場面でも次のとおりにする。
  - **範囲の例**: backend `pytest backend/tests/<テストのファイル> -q`、frontend `./node_modules/.bin/vitest run <該当ファイル>`。
    **frontendのコマンドに`npx`を付けない**。**例外は`tsc --noEmit`**で、プロジェクト全体で1回通す（Next.jsの生成型が無い
    作業ツリーでは、`tsc`の前に`next typegen`を回す）。所要時間と生成型の前提は[setup.md](../../../docs/architecture/setup.md)「テスト」。
  - **静的検査とテストの両方が落ちていれば、静的検査を先に全部直してからテストを回す**。**1件直すたびに回し直さない**——
    出た指摘は全部直してから、次の1回を回す。
  - backendに`ruff format`をかけない（CIは`ruff check`だけを回す）。
  - **影響範囲が自分でも分からないときは、範囲を導出してから絞る**: `pytest backend/tests -q --co`
    （収集のみ）でimportが壊れたファイルを出し、変更したシンボルをgrepして参照元を出し、そこで挙がった
    ファイルだけを実行する。フルスイートを影響範囲の調査に使わない。
  - **1の再現で直すためにソースかテストを変えたら、ソースを読む検査（[testing-structure.md](../../rules/testing-structure.md)「ソースを読む検査は、専用ディレクトリへ置く」）も範囲に含める**
    （backend: `python -m pytest backend/tests/structure -q`、frontend: `./node_modules/.bin/vitest run src/structure`）。
- **同じ作業ツリーで並行して複数のテストプロセスを走らせない**（下の「テストDBは作業ツリーごとに分かれる」）。

## 検査の置き場（手元・作業ブランチのCI・masterのCI）

同じ検査を2つの層に置かない。

| 層 | 回すもの | 担うこと |
|---|---|---|
| 手元 | 上の「手元の検査の回し方」 | CIの失敗の再現・書いているテストの動作・怪しいところの念押し（どれも届く範囲だけ） |
| 作業ブランチ（`orch/**`）のCI | 必須チェックのワークフロー（名前と、文書や運用の道具・タスク管理だけの変更で重い検査を飛ばす範囲は[tech-stack.md](../../../docs/architecture/tech-stack.md)「CIの実行枠（リポジトリがpublicである間の前提）」。Pull Requestで走り、作業ブランチへのpushでは走らない） | 静的検査とフルスイート（Linuxでの結果）。masterと合わせた版で、masterへ入れてよいかの判定 |
| masterのCI | 同じワークフロー | 作業ブランチで個別に通ったコミットを組み合わせた木の検査。`ci.yml`のbackend〜e2e-scanが通るまでbackend・frontendのデプロイは起動しない（flow-gate・文書の検査は待たない） |
| 本番 | `scripts/prod_route_check.py`（backendを出したあとと毎日1回。[tech-stack.md](../../../docs/architecture/tech-stack.md)「本番でルートを作る確かめ」） | 本物の応答で、ルートを作ってレンズを替える操作が壊れていないか。デプロイを伴わない本番の値の変化も拾う |

- **コミット・pushの直前（gitのフック）には検査を置かない。** 何を見ているかの正本は`scripts/review_checks.py`と各CIの段で、ここへ写さない。

### CIの結論を読む

**masterの結論は、masterの最新コミットに対するものを読む。** masterが赤いままの間は、「CIが通った」を完了の根拠にしない。
実行中の実行は赤に数えない。打ち切り・時間切れで終わった実行は「通った」に数えない。

`gh`が入っていない環境では、ActionsのREST APIを直接読む。そのとき:

- `git credential fill`で取れるトークンを`Authorization: Bearer`で付ける（認証なしは接続元のIPごとに1時間60回までで、
  開発機のすべてのセッションが同じ枠を使う）。トークンは出力・ログ・例外文に出さない。
- 実行はコミットの完全なsha（40桁）で引く（`head_sha`に短いshaを渡すと実行が返らない）。
- 同じコミットに複数の実行が混ざるので、ワークフローごとに`run_number`が最大の1件を採る。
- ジョブのログは署名付きの別のURLへの302で返る。認証の見出しを転送先へ渡さない（Pythonの`urllib`では
  `Request.add_unredirected_header`で付ける）。

### 型検査（mypy）

設定は`backend/mypy.ini`、実行は`backend/`で`python -m mypy`（引数なし。対象は設定の`files`が決める）。
設定の理由はここに書く。

- **対象はapp・scripts・benchmarksで、testsは入れない**（テストの偽物を本物の型の引数へ渡す書き方が誤検知になる）。
- **型注釈の無い関数の中身も見る**（`check_untyped_defs`。見ないと、注釈の無い呼び出し側の食い違いが止まらない）。
- **ファイルやモジュールを検査から外さない。**
- 型情報（`py.typed`）を配っていないライブラリは、まず型のスタブ（typeshedの`types-*`等）を探し、
  あれば本体の版に合わせて`requirements-dev.txt`へ固定する。無いものだけを設定の`ignore_missing_imports`の節へ足す。
- **Linuxとして検査する**（`platform = linux`。本番とCIがLinuxで動くため）。
- `scripts/`は`mypy_path`に入れる（スクリプトは`from _stdio import …`のように同じ場所のモジュールを読む）。
  backendの道具が読むリポジトリ直下の`scripts/`のモジュール（`checkout_freshness.py`）も入れる。
- **`mypy.ini`はASCIIだけで書く**（日本語のWindows（cp932）では非ASCIIの1文字で起動に失敗する）。

### 層の向き（import-linter）

backendの層（[directory-layout.md](../../../docs/architecture/directory-layout.md)「backend」）の向きを、
下の層が上の層を読んだ時点で止める。設定は`backend/.importlinter`、実行は`backend/`で`lint-imports`
（引数なし）。同じ設定に、`domain/`が外部の書式を読む道具を読んだら止める`forbidden`契約も置く
（`include_external_packages = True`なので、禁じる先に標準ライブラリの`io`も書ける。禁じられるのは最上位の名前だけ）。

- **契約を緩める指定（`ignore_imports`）を足さない**。越境は、読む側を正しい層へ移すか、共有したいものを下の層へ下ろして解く。
- **`.importlinter`はASCIIだけで書く。**

### 使われないコード（knip）

frontendで、入口（Next.jsのファイル規約・vitestとPlaywrightの設定・`package.json`のスクリプト）から辿れない
ファイル・export・依存と、宣言せずに読んでいる依存を止める。設定は`frontend/knip.json`、実行は`frontend/`で`npm run knip`。

- **入口を足すのは、knipが既定で見つけない設定と手動の道具だけ**（例: `-c`で指定して使う
  `playwright.live.config.ts`）。**無視の指定（`ignore`系）を足さない**——指摘は、消すか、入口として宣言するかの
  どちらかで解く。
- 同じファイルの中だけで使う名前も`export`を外す対象にする（既定のまま）。

## 開発機でのbackendテストの回し方

開発機でbackendのテストを回すか・どの範囲を回すかは、上の「手元の検査の回し方」が決める（フルスイートは回さない）。
回すファイルにDBを使うテストと使わないテストが混ざるときは、次の2本に分ける。

```bash
# DBを使わないぶんを並列で（PYTHONUTF8=1を付ける）
PYTHONUTF8=1 backend/.venv/Scripts/python.exe -m pytest backend/tests/<テストのファイル> backend/tests/<テストのファイル> -q -m "not postgis" -n auto

# DBを使うぶん（完了の条件には含めない。下の「テストDBは作業ツリーごとに分かれる」の`-m postgis`の段落）
backend/.venv/Scripts/python.exe -m pytest backend/tests/<テストのファイル> backend/tests/<テストのファイル> -q -m postgis
```

### 変更が届くテストを選ぶ（pytest-testmon）

`--testmon`を付けて流すと、**渡した範囲のうち、前回から変わった行を通るテストと記録の無いテストだけ**を流す
（記録は`backend/.testmondata`。作業ツリーごとで、コミットしない）。

```bash
PYTHONUTF8=1 backend/.venv/Scripts/python.exe -m pytest backend/tests/<テストのファイル> backend/tests/<テストのファイル> -q --testmon
```

- **渡した範囲の外は選ばない。** 候補のファイルは今までどおり導き（上の「手元の検査の回し方」の
  grepと`--co`）、testmonはその中から変わった行に届かないテストを外すのに使う。
- Python以外のファイル（生成物のJSON等）と網の向こうにあるもの（テストDBの中身）は追わない。それらだけを変えたときは
  `--testmon`を外して流す。
- CIは使わない（毎回全件を流す）。

### 実行順をばらす（pytest-randomly）

入っているだけで働き、モジュールの並びと、モジュールの中の並びを混ぜる（違うモジュールのテストを交ぜ合わせはしない）。
**並びが変わった回にだけ落ちる失敗は、実装の欠陥ではなく、テストの隠れた順序依存として直す**（直す向きは
[testing-review.md](../../rules/testing-review.md)「テストを変異テストで見直す」の隔離）。

- CIで落ちた並びは、手元で`--randomly-seed=<runのID>`を付けると同じ並びになる（CIはrunのIDを種に渡す。
  `.github/workflows/ci.yml`）。`-n`を付けずに流すと、ワーカーの中の順まではCIと揃わない。
- 手元の回の種は、実行の見出しに`Using --randomly-seed=…`と出る（`-q`では出ない）。
- 前回と同じ並びは`--randomly-seed=last`、混ぜずに流すのは`-p no:randomly`。

**汚した側の探し方**（落ちたテスト1本＝汚される側について）:

1. 汚される側だけを`-p no:randomly <テストのid>`で回し、通ることを見る。単独で落ちるなら向きが逆で、ふだん通るのは前に走った
   テストが状態を用意しているから（頼っている側）。下の2〜4で用意している側を探し、テストが自分で用意する形に直す。
2. `-n`を付けずに`--randomly-seed=<種> --collect-only -q`で、その種の1つのプロセスでの並びを出し、汚される側より前の id を
   ファイルへ書く。同じ種で`-n`を付けずに回し、汚される側が落ちることを見る（落ちなければ、CIのワーカーの分け方で前に来たテストが
   違う。別の種を試す）。
3. 前の id の半分と汚される側を、`-p no:randomly @<ファイル>`（1行に1つの id。書いた順のまま回る）で回す。落ちた半分に汚す側が
   いるので、それを次の候補にして、1本になるまで繰り返す。どちらの半分でも落ちないなら、汚すのは2本以上の組なので、
   前から1本ずつ外して、落ちなくなる所を探す。
4. 汚す側が残す状態（モジュールの変数・プロセスに残る記録・DB の行・環境変数）を見つけ、汚す側が自分で片付ける形
   （フィクスチャの後始末・`monkeypatch`）に直す。汚される側に片付けを足して隠さない。

### 止まったテストを落とす（pytest-timeout）

`backend/pytest.ini`の`timeout`が1件あたりの上限（秒。fixtureの準備・本体・後片付けの合計）で、超えたテストを落とす。

- 開発機（Windows）では、時間切れで**プロセスごと終わる**（後片付けも以降のテストも走らない）。テストDBに残った行は、
  次の実行でそのファイルのエンジンの準備（`tests/conftest.py: road_graph_engine`）が消す。
- CI（Linux）はシグナル方式: 時間切れのテストだけが失敗になり、後片付けも走って残りへ進む。
- 上限は、`--durations`で測ったふだんの1件の最長の数倍に置く（値の根拠は`backend/pytest.ini`のコメント）。
  1件だけ長いと分かっているテストは`@pytest.mark.timeout(<秒>)`で個別に上げる。

### テストDBは作業ツリーごとに分かれる

`tests/conftest.py: postgis_database_url`が、チェックアウトの場所からDB名を導き
（`ridecompass_test_<ディレクトリ名>_<パスのダイジェスト>`）、無ければ作る。表が宣言と違う形になっていれば、
ファイルごとのエンジンの準備（`tests/conftest.py: road_graph_engine`）が`scripts/schema_gap.py`で差を測って作り直すので、
壊れ方の確かめ（[testing-review.md](../../rules/testing-review.md)「消す・まとめる前に、残す側が落ちるかを見る」）で実装や宣言を戻したあとに、テストDBを手で戻さなくてよい。

環境ごとに必要な作業（開発機で一度だけ付ける権限・拡張）と、作業ツリーを消したあとの残骸の片付けは付録にある。

**postgisを並列化しても速くならない**: DBを使うテストは`xdist_group(name="postgis")`により1ワーカーへ固定される。
縮めるには**ワーカーごとに**DBを分ける必要があり、それ自体が別タスク。

**`-m postgis`はCIが通し**、完了条件には含めない（手元で回すかは上の「手元の検査の回し方」）。作業ツリー専用のDBを
作れない環境では共有の`ridecompass_test`へ退避するため、並行セッションと衝突しうる。

## 変異テストでテストの効きを測る

今のテストが、実装の1か所の書き換え（`<` を `<=` に・`+` を `-` に等）を見つけられるかを測り、テストを消す・足す判断の
材料にする（結果から何を足す・消す・直すかは [testing-review.md](../../rules/testing-review.md)「テストを変異テストで見直す」）。台本は `backend/scripts/mutation/`（各ファイルの先頭に使い方）、回すのは
`.github/workflows/mutation.yml`（手で起こす）。

```bash
gh workflow run mutation.yml -R hidakagit/ride-compass --ref master -f ref=<測る版> -f count=0 -f stop_after=150
```

- **測る版と台本は `ref` から読む**。台本を直した作業ブランチを `ref` に渡せば、ワークフローを変えずに直した台本で回る。
  `count` は1本あたりの件数（`0` で全部。通しで動くかの試しは `5`）。
- **一覧の口**: 測る版の `backend/scripts/mutation/` に一覧を置くと、その変異だけを回す。
  - `only.txt`: 記録のテスト（その関数を通るテスト）で回す。テストを消したあと、消したテストが見つけていた変異を残る側が
    落とすかを確かめるときに使う。
  - `recheck.txt`: テスト全体を当てる。生き残りのうち読み込みのときに呼ばれる関数の変異を `importtime.py` で拾って当て直すときに使う。
  - `baseline.txt`: 変異を入れずに、関数ごとに同じテストの組み合わせを同じ並びで2回回す（基準。行は関数の名前か、全部なら `*`）。
    基準で落ちるテストは、テストどうしの依存や揺れで落ちていて、変異の回で落ちても見つけたとは言えない。
  - どれも master へ入れない。
- **Pull Request ごと**: `backend/app` を変えた Pull Request では `.github/workflows/mutation-pr.yml` が自動で走り、変えた関数の変異と
  その基準だけを回して、生き残りを変えた行への注記と実行の要約に出す（`diff_scope.py`・`pr_plan.py`・`report_pr.py`）。必須の
  チェックではない。読み方は .claude/skills/task-work/SKILL.md「作る担当」の5。
- **結果は成果物 `mutation-<番号>`**（14日で消える）。`gh run download <実行の id> -R hidakagit/ride-compass -D <場所>` で取り、
  測った版のチェックアウトの `backend/` で `python scripts/mutation/analyze.py <場所> [当て直しの成果物の場所]` を打つ
  （層ごとの変異スコア・テスト1本ごとの発見と重なり）。残したい数字は issue に書く。
- **1本のランナーが「The runner has received a shutdown signal」で止まったら**、Actions の画面の「Re-run failed jobs」で、
  その本だけを同じ入力でやり直す。同じ所で止まり続けるなら、ジョブの記録の「始め」の行で走っていた変異を見る。
- **開発機では回さない**。
- **測れない形**: 関数の外（モジュールの直下の表・定数・既定値）、`app/domain/routing.py`とログ・警告の行（`setup.cfg`で外している）、
  部分どうしのつなぎの食い違い（1つの関数の中の書き換えではないもの）。そこを確かめるテストは、変異を見つけないように
  見えても要らないとは言えない。

## E2E・画面の撮影の走らせ方

何をE2Eで見るか・書き方は[testing-e2e.md](../../rules/testing-e2e.md)パターン4が持つ。

- **`npm run test:e2e`**（`npm run build:e2e`→`playwright test`）。CIのe2eジョブも同じコマンドを使う。`build:e2e`は型の検査を
  外した本番ビルドで（`next.config.ts`の`typescript.ignoreBuildErrors`）、型はCIの`frontend`ジョブの`tsc --noEmit`が見る。
- **全状態の走査（`e2e/all-states.spec.ts`）は、CIでは別ジョブ（`e2e-scan`）で走らせ、
  それ以外のspecは`e2e`ジョブで走らせる。** 走査は幅 × 段階ごとに1本で、`e2e-scan`は幅ごとに段階の数のジョブへ
  分ける（`--shard`）。masterへのpushとPull Requestのどちらでも走る。CIで落ちた走査を手元で再現するときは
  `./node_modules/.bin/playwright test e2e/all-states.spec.ts -g "全状態の走査: <幅> / <段階>"`を回す。
- CIの`e2e`と`e2e-scan`は、Playwrightの公式のcontainerのimageの中で走り、ブラウザを取り込まない。imageの版は
  `frontend/package-lock.json`の`@playwright/test`の版に揃う（決め方は`ci.yml`の先頭）。
- 起動するのは、本番Dockerfileと同じ`node .next/standalone/server.js`
  （`npm run start:standalone`。`scripts/prepare-standalone.mjs`がDockerfileのCOPYと同じ静的ファイルの配置を作る）。
  `next start`・`next dev`は使わない。
- `playwright.config.ts: webServer`は**起動だけ**を行う。E2E専用のポートを使い、**既に動いているサーバーを使い回さない**
  （同じポートが塞がっていれば起動の時点で失敗する）。
- specだけを直して回し直すときは、直前のビルドを使って`./node_modules/.bin/playwright test e2e/<ファイル>`でよい。
  `frontend/src`を変えたら`npm run test:e2e`からやり直す。
- アプリを開かないspec（`playwright.no-server.config.ts: testMatch`）は、ビルドもサーバーの起動も無しで
  `./node_modules/.bin/playwright test -c playwright.no-server.config.ts`で回せる。CIは`playwright.config.ts`でこれらも回す。
- 開発機ではworkers=1で走る（`playwright.config.ts`）。
- **実データ・実backendで見る系統は、`frontend/e2e-live/`に置き、`playwright.live.config.ts`で
  走らせる。CIには載せない。** モックで決定的に回す`frontend/e2e/`と同じ場所に混ぜない。
  - **見るもの**: モック（`e2e/fixtures.ts: installApiMocks`）が本物の代わりに返しているもの——
    基礎地図・タイル・軸カタログ・ルート生成・気象——に本物が来たときにだけ起きる壊れ方（描かれない・
    値が来ない・押すと例外で開かない）。1シナリオ＝1枚のページ＝1本の幹で、重い段取り（開く・生成）を
    1回だけ払い、その先の枝をまとめて見る。枝は見終えたら戻し、戻ったかは`e2e/states.ts`の指紋で
    確かめる。枝の失敗は他の枝を止めない。当てる相手（公開軸・レイヤー）はカタログと宣言から取り、
    手で名指ししない。期待値は値ではなく性質（1件以上ある・2つの出どころが食い違わない・エラー0件）で書く。
    実世界で無いのが正当なもの（踏切の無い範囲・雨の無い日）は判定せず「該当なし（理由）」をログへ出す。
    backendが上流の失敗として返した502・503・504と、`/api/debug/stats`の外部呼び出しのエラーの増分は、
    合否に入れず「外部要因」として必ずログへ出す。
  - **前提**（`e2e-live/global-setup.ts`が最初に確かめ、欠けていれば「前提不成立: 直し方」で止める）:
    開発DBへ向けたbackendを手元で起動しておく（設定からは起動しない）。そのbackendは
    `BASEMAP_PUBLIC_BASE_URL=http://localhost:3200/api/basemap`と、`CORS_ALLOWED_ORIGINS`に
    `http://localhost:3200`を足して起動する。起点は`E2E_LIVE_POINT=緯度,経度`で開発DBの取込範囲の中を与える
    （既定はアプリの既定地点で、範囲外なら前提不成立で止まる）。予報（MSM）が古ければ、時刻を入力に取る枝は「該当なし」になる。
  - **backendの起動は`python backend/scripts/serve_e2e_live.py`**（作業ツリーから。裏で走らせて出力を読む）。
    本体のチェックアウトの`backend/.env`を読み、上の基礎地図のURLとCORS（カンマ区切り）の2つだけを起動の環境に足して
    （`.env`のファイルは書き換えない）、作業ツリーのコードを本体の`backend/.venv`で起動する。
    `/health`が返ると、向け先と起点を埋めたビルドと実行のコマンド、止め方（backendのpid）を出す。
  - **手順**: 起動の出力のとおり、`cd frontend && NEXT_PUBLIC_API_URL=<backend> BACKEND_INTERNAL_URL=<backend> npm run build` →
    `cd frontend && E2E_LIVE_API=<backend> E2E_LIVE_POINT=<緯度,経度> ./node_modules/.bin/playwright test -c playwright.live.config.ts <シナリオ>`
    をシナリオごとに1回。backendの向け先を変えたらビルドし直す（`NEXT_PUBLIC_API_URL`と`BACKEND_INTERNAL_URL`はビルドに埋め込まれる）。
  - **誰がいつ回すか**: 地図の描き方（`features/map/scene/`等）・タイルへ焼く値・軸カタログ・動的値の
    配信・気象の描き方・ルート生成の応答に触る変更の担当が、**Pull Requestを出す前に1回**回し、
    実行したコマンドと結果（落ちた枝・「該当なし」・「外部要因」）をPull Requestの本文の検証へ書く。回せない環境（開発DBも
    手元のbackendも無い担当のランナー・クラウドのセッション等）・当たるファイルを変えたが描き方にも応答にも触らない変更では、
    回さない理由を`e2e-live`の語を添えて同じ所へ書く。触らない変更では回さない。門にはしない（CIに載せない）。

- **画面を撮る道具は`frontend/capture/`に置き、`playwright.capture.config.ts`で走らせる。テストではなく、CIに載せない**
  （判定を持たず、画像を出すだけ。Pull Requestの修正前後のキャプチャに使う）。入口は`node scripts/capture.mjs`の1つで、引数と使い方は
  スクリプトの先頭にある。撮影は「開く版」（`--app`: 本番・作業ツリー・git の版）×「応答」（`--api`: e2e のモック
  `frontend/e2e/fixtures.ts: installApiMocks`・本物の backend。`--backend` で選んだパスの頭だけを作業ツリーの backend が返す）×「脚本」
  （`frontend/capture/context.ts: CaptureScript`）に分かれ、手元で起動する版には本番と同じ組の環境変数を渡す。
  見せたい状態（位置・レイヤー・レンズ・凡例・応答の差し替え等）は引数でなく脚本で書く。脚本は受け取る口だけを使い何も読み込まない（だから作業ツリーの外に置ける）。
  地図を開く・レンズを選ぶ・読み終わりを待つ段取りは`e2e-live/live.ts`、画面を進める段取りは
  `e2e/fixtures.ts`・`e2e/states.ts`を使い、書き直さない。地図に描かれた、押すと開くもの（道・点・ルートの区間・乗り換えの帯等）は、
  経度・緯度を渡さずに`e2e/fixtures.ts: clickFeature`で押す。撮れる対象・呼べる段取りを増やすときは口を変えず、地図の当たり判定の
  宣言（scene の`hitTargets`）か、e2e の段取りと応答の雛形（`e2e/fixtures.ts`・`e2e/states.ts`・`src/testing/catalogAxes.ts`）へ足す。

## 付録

作業の前には読まない。テストDBの一度きりの準備と片付け（「テストDBは作業ツリーごとに分かれる」の続き）。

### 環境ごとに必要な作業

| 環境 | 必要な作業 |
|---|---|
| 開発機（ローカルPostgreSQL） | **一度だけ**ロールへ`CREATEDB`を付け、複製元のDBへ拡張を入れる（どちらも下記） |
| CI（GitHub Actions） | 何もしない（`TEST_DATABASE_URL`が優先され、DBと拡張は`ci.yml`の段が実行ごとに作る） |
| 本番（Oracle VM） | 何もしない |

権限を付けない場合は共有DB（`ridecompass_test`）へ退避し、その旨を1行出す。

開発機での手順（PostgreSQLをインストールした機械で1回だけ。`postgres`ロールのパスワードをプロンプトで聞かれる）:

```bash
"/c/Program Files/PostgreSQL/18/bin/psql.exe" -U postgres -d postgres -c "ALTER ROLE ridecompass CREATEDB;"
```

`psql`は絶対パスで呼ぶ。元に戻すときは`NOCREATEDB`を同じ形で流す。
付いたかどうかは`SELECT rolcreatedb FROM pg_roles WHERE rolname='ridecompass';`で確かめる。

拡張はスーパーユーザーで、**複製元になるDBへ一度入れておく**——共有の`ridecompass_test`と、その複製元の
`ridecompass_test_template`の両方へ入れる。何が要るかは`road_graph_repository.py: REQUIRED_EXTENSIONS`が正本で、
足りないときは`create_tables()`が実行すべきコマンドを告げて止まる。

```bash
"/c/Program Files/PostgreSQL/18/bin/psql.exe" -U postgres -d ridecompass_test -c "CREATE EXTENSION IF NOT EXISTS postgis_raster;"
```

### 残骸の片付け

作業ツリーを消してもDBは残る。**どのDBがどの作業ツリーのものかは、DB自身のコメントで見る**——名前から推測しない。

```bash
backend/.venv/Scripts/python.exe backend/scripts/drop_orphan_test_databases.py         # 一覧
backend/.venv/Scripts/python.exe backend/scripts/drop_orphan_test_databases.py --drop  # 落とす
```
