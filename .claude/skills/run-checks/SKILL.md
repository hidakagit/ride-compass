---
name: run-checks
description: "検査とテストを手元・作業ブランチのCI・masterのCIのどこでどう回すか、CIの結論の読み方、開発機でのbackendテスト、変異テスト、E2Eと画面の撮影の走らせ方、テストDBの準備。検査やテストを回す前・CIの結果を読む前に使う。"
---

# テストと検査の回し方

手元とCIで、検査とテストをどこでどう回すかを持つ。何を確かめるか・テストが要るか・書き方は
[testing.md](../../rules/testing.md)が持つ。

## 手元の検査の回し方

- **手元とCIで同じ答えを2回買わない**: CIはPull Requestで毎回、変更が届く側の静的検査（`.github/workflows/ci.yml`の
  ジョブ（backend・frontend）がテスト（`pytest`・`npm test`）より前に回す段・`api-contract`のOpenAPI生成物のドリフト・
  `.github/workflows/docs-consistency.yml`の段）とフルスイートを回す（[flow.md](../../../docs/conventions/flow.md)「作る担当」の4・5）。
  文書や運用の道具・タスク管理だけの変更では、`ci.yml: changes`ジョブが重い検査を飛ばす（[tech-stack.md](../../../docs/architecture/tech-stack.md)「CIの実行枠（リポジトリがpublicである間の前提）」）。
  masterでは`ci.yml`のbackend〜e2e-scanが通るまでbackend・frontendのデプロイを起動しない（下の「検査の置き場」）。手元では、CIの結論より先に
  知らないと作業が無駄になる答えだけを、その答えに要る最小の範囲で取る。
- **回してよい場面は3つ**。どれでもなければ回さずにpushし、CIの結論を待つ。
  1. **CIが落ちた失敗を再現して直すとき**（[testing.md](../../rules/testing.md)「テストが落ちたときの直し方」）。回すのは落ちた失敗に届く範囲だけ。
  2. **テストそのものを書く・書き換えるとき**（新しいテスト・起こし直し・足場の作り直し）。書いた形をほかのファイルへ
     写す前に、書いたファイルが動くかを見る（1ファイル回して初めて分かる足場の誤りを、全部のファイルへ写してから直さないため）。
     回すのは書いた・直したテストファイルだけで、1ファイルを書くたびにそのファイルを回してよい。
  3. **怪しいところがあって、CIの前に念を入れて確かめたいとき**（並べ替えで落ちそうな共有の状態・時計に依存する境界等）。
     回すのはその怪しいところに届くテストだけで、何を怪しんで回したかをPull Requestの本文の検証に書く。
- **回さないもの**: フルスイート（backendの`tests`全体・frontendの`vitest run`全体）と、pushの前の念のための全体。
  1行・1ファイル変えただけで全体を流し直さない——全体の答えはCIが同じPull Requestで出す。静的検査も、1の再現と
  下の`tsc`の例外のほかは回さない。
- **コミットの前に、frontendで変えたファイルへ整形をかける**: CIの`format:check`（`frontend/package.json`）が見る
  `src/**/*.{ts,tsx,css}`に当たる変えたファイルへ、`./node_modules/.bin/prettier --write <変えたファイル>`をかけてからコミットする。
  これは検査ではなく直しで、CIと同じ答えを先に買わない——答え（落ちる・通る）を見るのではなく、ファイルをCIが通す形に
  書き換えるだけで、中身は変わらず、待ちも要らない。かけないと、整形だけの誤りがPull RequestのCIで初めて落ち、直すための
  取り込み・push・CIの待ちがもう1往復かかる。`src`は全部がprettierの形に揃っている（CIが毎回見る）ので、変えていない行は
  書き換わらない。`format:check`（`--check`）は回さない（答えを見るだけで直さない）。backendは下のとおり`ruff format`をかけない。
- 回すときは、どの場面でも次のとおりにする。
  - **範囲の例**: backend `pytest backend/tests/<テストのファイル> -q`、frontend `./node_modules/.bin/vitest run <該当ファイル>`。
    **frontendのコマンドに`npx`を付けない**（ツールはローカルにあり、`npx`は毎回パッケージ解決をやり直す）。**例外は`tsc --noEmit`**で、
    型の波及を1ファイルへ絞れないためプロジェクト全体で1回通す（Next.jsの生成型が無い作業ツリーでは、`tsc`の前の
    `next typegen`を飛ばすと落ちる）。所要時間と生成型の前提は[setup.md](../../../docs/architecture/setup.md)「テスト」。
  - **静的検査とテストの両方が落ちていれば、静的検査を先に全部直してからテストを回す**——消したシンボルの死んだ参照を
    最後に見つけてテストを回し直さないため。**1件直すたびに回し直さない**——出た指摘は全部直してから、次の1回を回す。
  - backendに`ruff format`をかけない（CIは`ruff check`だけを回し、リポジトリのコードは`ruff format`の形に揃っていない。
    かけると変えていない行まで書き換わる）。
  - **影響範囲が自分でも分からないときは、範囲を導出してから絞る**: `pytest backend/tests -q --co`
    （収集のみ）でimportが壊れたファイルを出し、変更したシンボルをgrepして参照元を出し、そこで挙がった
    ファイルだけを実行する。フルスイートを影響範囲の調査に使わない。
  - **1の再現で直すためにソースかテストを変えたら、ソースを読む検査（[testing.md](../../rules/testing.md)「ソースを読む検査は、専用ディレクトリへ置く」）も範囲に含める**:
    全ソース・全テストを母集団にするのでどの変更にも届くが、importを辿っても
    シンボルをgrepしても出てこない（backend: `python -m pytest backend/tests/structure -q`、
    frontend: `./node_modules/.bin/vitest run src/structure`）。
- **同じ作業ツリーで並行して複数のテストプロセスを走らせない**——テストDBは作業ツリーごとに1つで、それを取り合って止まる
  （下の「テストDBは作業ツリーごとに分かれる」）。

## 検査の置き場（手元・作業ブランチのCI・masterのCI）

同じ検査を2つの層に置かない。置くと同じ答えを2回買い、遅い方の層の待ちがそのまま作業の
待ちになる。

| 層 | 回すもの | 担うこと |
|---|---|---|
| 手元 | 上の「手元の検査の回し方」 | CIの失敗の再現・書いているテストの動作・怪しいところの念押し（どれも届く範囲だけ） |
| 作業ブランチ（`orch/**`）のCI | `ci.yml`の全ジョブと`docs-consistency.yml`・`claude-gate.yml`（Pull Requestで走る。作業ブランチへのpushでは走らない。文書や運用の道具・タスク管理だけの変更では`ci.yml: changes`ジョブが重い検査を飛ばす） | 静的検査とフルスイート（Linuxでの結果）。masterと合わせた版で、masterへ入れてよいかの判定 |
| masterのCI | 同じ`ci.yml`と`docs-consistency.yml`・`claude-gate.yml` | 作業ブランチで個別に通ったコミットを組み合わせた木の検査。`ci.yml`のbackend〜e2e-scanが通るまでbackend・frontendのデプロイは起動しない（flow-gate・文書の検査は待たない。**本番へ出る前の門はここ**） |

- **コミット・pushの直前（gitのフック）には検査を置かない。** CIと同じ検査をpushの直前に置くと、作業ブランチへのpushの
  たびに手元で同じ答えを買い直す。何を見ているかの正本は`scripts/review_checks.py`と各CIの段で、ここへ写さない。

### CIの結論を読む

**masterの結論は、masterの最新コミットに対するものを読む。** 古いコミットで落ちたまま最新で直って
いる失敗を数え続けると、赤そのものが無視されるようになる。逆に、masterが赤いままの上では新しい赤が
埋もれ、「CIが通った」を完了の根拠にできない。実行中の実行は結論が出ていないので赤に数えない。
打ち切り・時間切れで終わった実行は、成功していない以上「通った」に数えない。

`gh`が入っていない環境では、ActionsのREST APIを直接読む。そのときの事実:

- 認証なしの問い合わせは接続元のIPごとに1時間60回までで、開発機のすべてのセッションが同じ枠を使う。
  `git credential fill`で取れるトークンを`Authorization: Bearer`で付ける。トークンは出力・ログ・例外文に出さない。
- 実行はコミットの完全なsha（40桁）でしか引けない（`head_sha`に短いshaを渡すと実行が返らない）。
- 同じコミットに複数の実行が混ざる（手動の再実行・同じブランチへ続けたpush）。`created_at`が同じ秒の
  実行どうしは並び順が保証されないので、ワークフローごとに`run_number`が最大の1件を採る。
- ジョブのログは署名付きの別のURLへの302で返り、転送先は転送された認証の見出しを拒む。リダイレクトで
  見出しを引き継ぐクライアント（Pythonの標準ライブラリの`urllib`等）では、認証の見出しを転送先へ渡さない
  （`Request.add_unredirected_header`で付ける）。

### 型検査（mypy）

backendの型検査は、関数が受け取ると宣言した型と、呼び出し側が実際に渡す値の食い違いを止める。
個数が合っていて型だけが違う呼び出し（例: 枝の一覧を受ける関数へidの一覧を渡す）は、
テストが通る経路を踏まない限り本番のデータで走らせるまで見つからない。設定は
`backend/mypy.ini`、実行は`backend/`で`python -m mypy`（引数なし。対象は設定の`files`が決める）。

- **対象はapp・scripts・benchmarksで、testsは入れない。** テストはテスト用の偽物を本物の型の
  引数へ渡す書き方が大半で、型の食い違いとしては誤検知になる。
- **型注釈の無い関数の中身も見る**（`check_untyped_defs`）。見ないと、注釈の無い呼び出し側が
  宣言と違う型を渡しても止まらない。
- **ファイルやモジュールを検査から外さない。** 既存の指摘があるファイルを外すと、そのファイルの
  中の新しい食い違いも一緒に止まらなくなる。
- 型情報（`py.typed`）を配っていないライブラリは、まず型のスタブ（typeshedの`types-*`等）を探し、
  あれば本体の版に合わせて`requirements-dev.txt`へ固定する。無いものだけを設定の
  `ignore_missing_imports`の節へ足す（そこから来る値は型が分からないものとして扱われ、
  そのライブラリへの呼び出しは照合されない）。
- **Linuxとして検査する**（`platform = linux`）。本番とCIはLinuxで動き、Linuxにしか無い関数
  （`os.getloadavg`等）を使うコードが開発機でだけ指摘になるのを避ける。
- `scripts/`は`mypy_path`に入れる。スクリプトは`python scripts/<名前>.py`で実行され、
  `scripts/`自身が`sys.path`の先頭に入るため、同じ場所のモジュール（`_stdio.py`等）を
  `from _stdio import …`で読む。mypyにも同じ解決をさせないと読めない。
  backendの道具が読むリポジトリ直下の`scripts/`のモジュール（`checkout_freshness.py`）も同じ理由で入れる。
- **`mypy.ini`はASCIIだけで書く。** mypyは設定ファイルをOSの既定の文字コードで読み、日本語の
  Windows（cp932）では非ASCIIの1文字で起動に失敗する。設定の理由はここに書く。
- 解析結果は`backend/.mypy_cache/`に残り、2回目以降は変わったファイルだけを見直す。
  作業ツリーごとの初回は保存が無く、開発機で40〜70秒かかる（2回目以降は2〜4秒）。

### 層の向き（import-linter）

backendの層（[directory-layout.md](../../../docs/architecture/directory-layout.md)「backend」）の向きを、
下の層が上の層を読んだ時点で止める。設定は`backend/.importlinter`、実行は`backend/`で`lint-imports`
（引数なし）。同じ設定に、`domain/`が外部の書式を読む道具を読んだら止める`forbidden`契約も置く
（禁じる先に標準ライブラリの`io`を書けるのは`include_external_packages = True`のため。grimpは
これが真のとき標準ライブラリも外部のパッケージとして数える。禁じられるのは最上位の名前だけ）。

- **契約を緩める指定（`ignore_imports`）を足さない**——足すと、その向きの新しい越境も一緒に止まらなく
  なる。越境は、読む側を正しい層へ移すか、共有したいものを下の層へ下ろして解く。
- **`.importlinter`はASCIIだけで書く。** import-linterはINIの設定ファイルをOSの既定の文字コードで読む
  （`mypy.ini`と同じ）。
- 解析結果は`backend/.import_linter_cache/`に残る（中に自分を無視する`.gitignore`を置くので、
  コミットには入らない）。

### 使われないコード（knip）

frontendで、入口（Next.jsのファイル規約・vitestとPlaywrightの設定・`package.json`のスクリプト）から辿れない
ファイル・export・依存と、宣言せずに読んでいる依存（別の依存が偶然入れているもの）を止める。設定は
`frontend/knip.json`、実行は`frontend/`で`npm run knip`。

- **入口を足すのは、knipが既定で見つけない設定と手動の道具だけ**（例: `-c`で指定して使う
  `playwright.live.config.ts`）。**無視の指定（`ignore`系）を足さない**——指摘は、消すか、入口として宣言するかの
  どちらかで解く。無視を足すと、その範囲の新しい未使用も一緒に止まらなくなる。
- 同じファイルの中だけで使う名前も`export`を外す対象にする（既定のまま）。

## 開発機でのbackendテストの回し方

開発機でbackendのテストを回すか・どの範囲を回すかは、上の「手元の検査の回し方」が決める（フルスイートは回さない）。
回すファイルにDBを使うテストと使わないテストが混ざるときは、次の2本に分ける。

```bash
# DBを使わないぶんを並列で（PYTHONUTF8=1が無いとワーカー起動が落ちる）
PYTHONUTF8=1 backend/.venv/Scripts/python.exe -m pytest backend/tests/<テストのファイル> backend/tests/<テストのファイル> -q -m "not postgis" -n auto

# DBを使うぶん（完了の条件には含めない。下の「テストDBは作業ツリーごとに分かれる」の`-m postgis`の段落）
backend/.venv/Scripts/python.exe -m pytest backend/tests/<テストのファイル> backend/tests/<テストのファイル> -q -m postgis
```

**`PYTHONUTF8=1`が要る理由**: 付けないと`execnet`のワーカーが
`UnicodeEncodeError: ... surrogates not allowed`で即死し、親が
`EOFError: expected 1 bytes, got 0`のINTERNALERRORになる。リポジトリのパスに含まれる
非ASCII文字がサロゲート化するためで、UTF-8モードにすると解消する。

### 変更が届くテストを選ぶ（pytest-testmon）

`--testmon`を付けて流すと、テストごとに通った行を記録し（`backend/.testmondata`。作業ツリーごとで、
コミットしない）、次に`--testmon`を付けた実行では、**渡した範囲のうち、前回から変わった行を通るテストと
記録の無いテストだけ**を流す。記録はその作業ツリーで`--testmon`付きで流した分だけ溜まり、作業ツリーを
使い回す間は残る。

```bash
PYTHONUTF8=1 backend/.venv/Scripts/python.exe -m pytest backend/tests/<テストのファイル> backend/tests/<テストのファイル> -q --testmon
```

- **渡した範囲の外は選ばない。** 候補のファイルは今までどおり導き（上の「手元の検査の回し方」の
  grepと`--co`）、testmonはその中から変わった行に届かないテストを外す。実測: 3ファイル73件を記録した後の
  2回目は73件すべてを外し、`domain/geo.py`の関数1本を書き換えると、その関数を通る7件だけを流した。
- **追わないもの**（公式）: Python以外のファイル（生成物のJSON等）と、網の向こうにあるもの（テストDBの
  中身もこちら）。それらだけを変えたときは`--testmon`を外して流す。
- 記録を取る実行は、通った行を測るぶん遅い（上の3ファイルで4.5秒→6.3秒）。
- CIは使わない（毎回全件を流す）。

### 実行順をばらす（pytest-randomly）

入っているだけで働く。モジュール→クラス→関数の順に、それぞれの中で並びを混ぜ、各テストの前に
`random`（とnumpyの旧い乱数）の種を決まった値へ戻す。**前のテストが残した状態に頼るテストは、並びが
変わった回に落ちる**——その失敗は実装の欠陥ではなく、テストの隠れた順序依存である。

- 混ぜるのはモジュールの中だけで、モジュールをまたいでテストを混ぜ合わせない。ファイル単位でエンジンと
  イベントループを共有するPostGIS統合テスト（[testing.md](../../rules/testing.md)パターン2）の前提はそのまま成り立つ。
- 種は実行の見出しに`Using --randomly-seed=…`と出る（`-q`では出ない）。CIはrunのIDを種に渡している
  （`.github/workflows/ci.yml`）ので、CIで落ちた並びは手元で`--randomly-seed=<runのID>`を付けると
  同じ並びになる。CIはその並びを複数のワーカーへ配るため、手元で`-n`を付けずに1本で流すと、
  ワーカーの中の順まではCIと揃わない。
- 前回と同じ並びは`--randomly-seed=last`、混ぜずに流すのは`-p no:randomly`。

### 止まったテストを落とす（pytest-timeout）

`backend/pytest.ini`の`timeout`が1件あたりの上限（秒。fixtureの準備・本体・後片付けの合計）で、
超えたテストを落とす。**条件に合う入力が無いまま探索が終わらない、のような止まり方をCIの実行時間の
上限まで待たずに、どのテストが止まったかとして出す。**

- CI（Linux）はシグナル方式: 時間切れのテストだけが失敗になり、後片付けも走って残りへ進む。
- 開発機（Windows）はスレッド方式: 時間切れで全スレッドのスタックを出し、**プロセスごと終わる**
  （後片付けは走らない。以降のテストも流れない）。テストDBに残った行は、次の実行でそのファイルの
  エンジンの準備（`tests/conftest.py: road_graph_engine`）が消す。
- デバッガが動いている間は発火を避ける（公式）。
- 上限は、`--durations`で測ったふだんの1件の最長の数倍に置く（どの環境の最長の何倍かと値の根拠は
  `backend/pytest.ini`のコメント）。1件だけ長いと分かっているテストは`@pytest.mark.timeout(<秒>)`で個別に上げる。

### テストDBは作業ツリーごとに分かれる

並行セッション（複数のClaude Code・複数の作業ツリー）が同じDBの同じ行を書き換えると、
**変更と無関係なテストが落ちる**。落ちたファイルを単独で回すと通るため、毎回切り分けに
時間を取られ、慣れると逆に本物の回帰を「どうせ競合」と見送る。

そこで`tests/conftest.py: postgis_database_url`が、チェックアウトの場所からDB名を導き
（`ridecompass_test_<ディレクトリ名>_<パスのダイジェスト>`）、無ければ作る。同じ作業ツリー
では同じDBを再利用するので、PostGIS拡張とテーブルの作成を毎回払わない。
再利用する表が前の実行で宣言と違う形になっていれば（表を入れ替える実装・ORMの宣言を一時に壊して回した等）、ファイルごとの
エンジンの準備（`tests/conftest.py: road_graph_engine`）が`scripts/schema_gap.py`で差を測り、表を消して今の宣言から作り直す。
壊れ方の確かめ（[testing.md](../../rules/testing.md)「そのテストは要るか（3問を順に）」）で実装や宣言を戻したあとに、テストDBを手で戻さなくてよい。

環境ごとに必要な作業（開発機で一度だけ付ける権限・拡張）と、作業ツリーを消したあとの残骸の片付けは付録にある。

**postgisを並列化しても速くならない**: DBを使うテストは`xdist_group(name="postgis")`により
1ワーカーへ固定される（同じDBへの同時TRUNCATEを避けるための設計、後述）。実測で直列6分20秒
（2,189件）に対し`-n auto --dist loadgroup`は7分00秒——postgisの285件が4分23秒を占め、残りを
並列化しても全体は縮まずワーカー起動のぶん増える。縮めるには**ワーカーごとに**DBを分ける
必要があり（作業ツリーごとの分離とは別の軸）、それ自体が別タスク。

**`-m postgis`はCIが通し**、完了条件には含めない（手元で回すかは上の「手元の検査の回し方」）。手元で回す場合、作業ツリー専用のDBを作れない環境では共有の`ridecompass_test`へ
退避するため、並行セッションと衝突しうることに注意する（この節の初め）。
DBを使うテストを手元で回さずに実装を変えてテストを直し忘れると、気づくのはCIになる——**CIが担うのはここ**で、手元で
先回りして通すことでは置き換えない。

## 変異テストでテストの効きを測る

今のテストが、実装の1か所の書き換え（`<` を `<=` に・`+` を `-` に等）を見つけられるかを測る。テストを消す・足す判断の
材料にする（tasks#661）。台本は `backend/scripts/mutation/`（各ファイルの先頭に使い方）、回すのは
`.github/workflows/mutation.yml`（手で起こす。CI の backend と同じ arm64・4コアのランナーを8本並べる）。

```bash
gh workflow run mutation.yml -R hidakagit/ride-compass --ref master -f ref=<測る版> -f count=0 -f stop_after=150
```

- **測る版と台本は `ref` から読む**。台本を直した作業ブランチを `ref` に渡せば、ワークフローを変えずに直した台本で回る。
  `count` は1本あたりの件数（`0` で全部。通しで動くかの試しは `5`）。
- **全部の変異（app の約21,000件）で、1本あたり約55分**（2026-10-09 の実測。準備約3分・回す約48分）。
- **一覧の口**: 測る版の `backend/scripts/mutation/` に一覧を置くと、その変異だけを回す。
  - `only.txt`: 記録のテスト（その関数を通るテスト）で回す。テストを消したあと、消したテストが見つけていた変異を残る側が
    落とすかを確かめるときに使う。
  - `recheck.txt`: テスト全体を当てる。読み込みのときに呼ばれる関数の変異は、mutmut の記録からテストが漏れて生き残りに
    見えるので、生き残りから `importtime.py` で拾って当て直す。
  - どちらも一度きりの入力なので、master へ入れない（入れると、以後の測りがその一覧だけになる）。
- **結果は成果物 `mutation-<番号>`**（14日で消える）。`gh run download <実行の id> -R hidakagit/ride-compass -D <場所>` で取り、
  測った版のチェックアウトの `backend/` で `python scripts/mutation/analyze.py <場所> [当て直しの成果物の場所]` を打つ
  （層ごとの変異スコア・テスト1本ごとの発見と重なり）。残したい数字は issue に書く。
- **1本のランナーが「The runner has received a shutdown signal」で止まったら**、Actions の画面の「Re-run failed jobs」で、
  その本だけを同じ入力でやり直す。メモリを食い尽くす変異がランナーごと止めた形で、`runner.py` が1件ごとに掛けるメモリの上限で
  止まらなくなったはず。同じ所で止まり続けるなら、ジョブの記録の「始め」の行で走っていた変異を見る。
- **開発機では回さない**。mutmut 3.8.0 は Windows を断り（`gen.py` が読み込みの照らしだけを避ける）、回せても1件あたり
  約9秒（Actions は約1.1秒）で、全部で約50時間かかる。
- **測れない形**: 関数の外（モジュールの直下の表・定数・既定値）、`app/domain/routing.py`（numba の JIT が差し込みを翻訳
  できないので外している。`setup.cfg`）、部分どうしのつなぎの食い違い（1つの関数の中の書き換えではないもの）。そこを
  確かめるテストは、変異を見つけないように見えても要らないとは言えない。

## E2E・画面の撮影の走らせ方

何をE2Eで見るか・書き方は[testing.md](../../rules/testing.md)パターン4が持つ。

- **`npm run test:e2e`**（`npm run build:e2e`→`playwright test`）。CIのe2eジョブも同じ
  コマンドを使う。`build:e2e`は型の検査を外した本番ビルドで（`next.config.ts`の`typescript.ignoreBuildErrors`）、
  型はCIの`frontend`ジョブの`tsc --noEmit`が見る。本番のimage（`Dockerfile`の`npm run build`）は型を検査する。
- **全状態の走査（`e2e/all-states.spec.ts`）は、CIでは別ジョブ（`e2e-scan`）で走らせ、
  それ以外のspecは`e2e`ジョブで走らせる。** 走査は幅 × 段階ごとに1本で、`e2e-scan`は幅ごとに段階の数のジョブへ
  分ける（`--shard`）。masterへのpushとPull Requestのどちらでも走る。CIで落ちた走査を手元で再現するときは
  `./node_modules/.bin/playwright test e2e/all-states.spec.ts -g "全状態の走査: <幅> / <段階>"`を回す。
- CIの`e2e`と`e2e-scan`は、Playwrightの公式のcontainerのimageの中で走り、ブラウザを取り込まない。imageの版は
  `frontend/package-lock.json`の`@playwright/test`の版に揃う（決め方は`ci.yml`の先頭）。
- 起動するのは、本番Dockerfileと同じ`node .next/standalone/server.js`
  （`npm run start:standalone`。`scripts/prepare-standalone.mjs`がDockerfileのCOPYと同じ
  静的ファイルの配置を作る）。`next start`・`next dev`は使わない——standalone構成に固有の
  配置ずれを捕まえられず、devは初回コンパイルの待ち時間が読めない。
- `playwright.config.ts: webServer`は**起動だけ**を行う。E2E専用のポートを使い、
  **既に動いているサーバーを使い回さない**（devサーバーや古いビルドを試してしまうため）。
  同じポートが塞がっていれば起動の時点で失敗する。
- specだけを直して回し直すときは、直前のビルドを使って
  `./node_modules/.bin/playwright test e2e/<ファイル>`でよい。`frontend/src`を変えたら
  `npm run test:e2e`からやり直す（直前のビルドは変更前のコードである）。
- アプリを開かないspec（`playwright.no-server.config.ts: testMatch`）は、ビルドもサーバーの起動も無しで
  `./node_modules/.bin/playwright test -c playwright.no-server.config.ts`で回せる。CIは`playwright.config.ts`でこれらも回す。
- 開発機ではworkers=1で走る（`playwright.config.ts`）。1つのサーバーへ複数のChromiumが
  同時に地図を読みに行くと、ページ遷移とフックが30秒の枠を超える。
- **実データ・実backendで見る系統は、`frontend/e2e-live/`に置き、`playwright.live.config.ts`で
  走らせる。CIには載せない**（CIのランナーには開発DBも手元のbackendも無い）。モックで決定的に
  回す`frontend/e2e/`とは目的が違うので、同じ場所に混ぜない。
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
    `http://localhost:3200`を足して起動する（E2Eのオリジン。基礎地図のURLとブラウザからの直接の
    取得がこのオリジンに向く）。起点は`E2E_LIVE_POINT=緯度,経度`で開発DBの取込範囲の中を与える
    （取込範囲はリポジトリに記録が無い。既定はアプリの既定地点で、範囲外なら前提不成立で止まる）。
    予報（MSM）が古ければ、時刻を入力に取る枝は「該当なし」になる。
  - **backendの起動は`python backend/scripts/serve_e2e_live.py`**（作業ツリーから。裏で走らせて出力を読む）。
    作業ツリーには`.env`が無いので、本体のチェックアウトの`backend/.env`（DBの向け先・土地被覆ラスタのパス等）を読み、
    上の基礎地図のURLとCORS（カンマ区切り）だけを足して、作業ツリーのコードを本体の`backend/.venv`で起動する。
    ポートは8000が使われていれば空いているものを選び、起点は開発DBの区間のうち路面タイルに道が出る点を選ぶ。
    `/health`が返ると、向け先と起点を埋めたビルドと実行のコマンド、止め方（backendのpid）を出す。
  - **手順**: 起動の出力のとおり、`cd frontend && NEXT_PUBLIC_API_URL=<backend> BACKEND_INTERNAL_URL=<backend> npm run build` →
    `cd frontend && E2E_LIVE_API=<backend> E2E_LIVE_POINT=<緯度,経度> ./node_modules/.bin/playwright test -c playwright.live.config.ts <シナリオ>`
    をシナリオごとに1回。`NEXT_PUBLIC_API_URL`と`BACKEND_INTERNAL_URL`
    （Next.jsのサーバーが中継する基礎地図・タイルの行き先）はビルドに埋め込まれるので、backendの向け先を変えたらビルドし直す。
  - **誰がいつ回すか**: 地図の描き方（`features/map/scene/`等）・タイルへ焼く値・軸カタログ・動的値の
    配信・気象の描き方・ルート生成の応答に触る変更の担当が、**Pull Requestを出す前に1回**回し、
    実行したコマンドと結果（落ちた枝・「該当なし」・「外部要因」）をPull Requestの本文の検証へ書く（masterのコミットは
    題名と本文から作られる。[flow.md](../../../docs/conventions/flow.md)「作る担当」の5）。回せない環境（開発DBも手元のbackendも無い担当のランナー・
    クラウドのセッション等）・当たるファイルを変えたが描き方にも応答にも触らない変更では、回さない理由を
    `e2e-live`の語を添えて同じ所へ書く。触らない変更では回さない。門にはしない（CIに載せない）。

- **画面を撮る道具は`frontend/capture/`に置き、`playwright.capture.config.ts`で走らせる。テストではなく、CIに載せない**
  （判定を持たず、画像を出すだけ。Pull Requestの修正前後のキャプチャに使う）。入口は`node scripts/capture.mjs`の1つで、引数と使い方は
  スクリプトの先頭にある。撮影は「開く版」（`--app`: 本番・作業ツリー・git の版）×「応答」（`--api`: e2e のモック
  `frontend/e2e/fixtures.ts: installApiMocks`・本物の backend。`--backend` で選んだパスの頭だけを作業ツリーの backend が返す）×「脚本」
  （`frontend/capture/context.ts: CaptureScript`）に分かれ、手元で起動する版には本番と同じ組の環境変数を渡す（`frontend` が読む環境変数を渡していなければ撮る前に止まる）。
  見せたい状態（位置・レイヤー・レンズ・凡例・応答の差し替え等）は引数でなく脚本で書く。脚本は受け取る口だけを使い何も読み込まないので、
  作業ツリーの外に置ける。地図を開く・レンズを選ぶ・読み終わりを待つ段取りは`e2e-live/live.ts`、画面を進める段取りは
  `e2e/fixtures.ts`・`e2e/states.ts`を使い、書き直さない。地図に描かれた、押すと開くもの（道・点・ルートの区間・乗り換えの帯等）は、経度・緯度を
  渡さずに`e2e/fixtures.ts: clickFeature`で押す（e2e-live も同じものを呼ぶ）。押せる対象は地図の当たり判定の宣言（scene の
  `hitTargets`）を実行時に読むので、当たり判定を足せば口を変えずに撮れる。e2e の段取りと応答の雛形（`e2e/fixtures.ts`・`e2e/states.ts`・
  `src/testing/catalogAxes.ts`）はモジュールごと口に載るので、そこへ足した関数は口を変えずに脚本から呼べる。ブラウザで開く前に、入口が宛先の応答を待ち（休止明けの本番等）、PlaywrightのChromiumと、
  Linuxなら起こすのに要る依存と日本語のフォント（無いと文字が豆腐になる）を入れる。

## 付録

作業の前には読まない。テストDBの一度きりの準備と片付け（「テストDBは作業ツリーごとに分かれる」の続き）。

### 環境ごとに必要な作業

| 環境 | 必要な作業 | 理由 |
|---|---|---|
| 開発機（ローカルPostgreSQL） | **一度だけ**ロールへ`CREATEDB`を付け、複製元のDBへ拡張を入れる（どちらも下記） | DBを作る権限・拡張を入れる権限が既定では無い |
| CI（GitHub Actions） | 何もしない | `TEST_DATABASE_URL`を注入しており、そちらが優先される。DBは`ci.yml`の段が実行ごとのランナーへPostgreSQLを直接入れて作るので、元から分離されている。拡張も同じ段が入れる |
| 本番（Oracle VM） | 何もしない | テストDBは本番に存在しない |

権限を付けない場合も動く——共有DB（`ridecompass_test`）へ退避し、その旨を1行出す。
**分離されないだけで、テストが走らなくなることはない。**

開発機での手順（PostgreSQLをインストールした機械で1回だけ。`postgres`ロールのパスワードを
プロンプトで聞かれる）:

```bash
"/c/Program Files/PostgreSQL/18/bin/psql.exe" -U postgres -d postgres -c "ALTER ROLE ridecompass CREATEDB;"
```

`psql`はPATHに入っていないため絶対パスで呼ぶ。元に戻すときは`NOCREATEDB`を同じ形で流す。
付いたかどうかは`SELECT rolcreatedb FROM pg_roles WHERE rolname='ridecompass';`で確かめる。

拡張はロールの権限では入れられない（スーパーユーザーを要求する）。**複製元になるDBへ一度
入れておけば、作業ツリー専用DBは複製で引き継ぐ**——共有の`ridecompass_test`と、その複製元の
`ridecompass_test_template`の両方へ入れる。何が要るかは`road_graph_repository.py:
REQUIRED_EXTENSIONS`が正本で、足りないときは`create_tables()`が実行すべきコマンドを告げて
止まる（**スキップにはならない**——そこを黙って飛ばすと、そのファイルのテストが1件も走らない
まま緑になる）。

```bash
"/c/Program Files/PostgreSQL/18/bin/psql.exe" -U postgres -d ridecompass_test -c "CREATE EXTENSION IF NOT EXISTS postgis_raster;"
```

### 残骸の片付け

作業ツリーを消してもDBは残る。**どのDBがどの作業ツリーのものかは、DB自身のコメントに
書いてある**——名前から推測しない。

```bash
backend/.venv/Scripts/python.exe backend/scripts/drop_orphan_test_databases.py         # 一覧
backend/.venv/Scripts/python.exe backend/scripts/drop_orphan_test_databases.py --drop  # 落とす
```
