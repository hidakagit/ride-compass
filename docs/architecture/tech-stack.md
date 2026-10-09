# 技術選定・実行環境の制約

コードからは導けない制約（版を上げられない理由・本番の設定を既定から変えた理由・デプロイの前後関係）だけを書く。
依存ライブラリの版・デプロイ・実行環境に触る変更は、着手前にここを読む。

## 採用しているもの

| 領域 | 採用 | 備考 |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + MapLibre GL JS + React | バージョンの正本は`frontend/package.json` |
| Frontendスタイリング | Tailwind CSS + Radix UI + `frontend/src/components/ui/`（CSS Modulesは使わない） | 使い分け基準・Design Token・意図的に作らないものは[frontend-design-system.md](../modules/frontend/frontend-design-system.md) |
| Frontendのデータ取得 | TanStack Query（`@tanstack/react-query`） | 取得の共有・取り直し・状態の骨格。MIT（依存の`@tanstack/query-core`も同じ）で商用で使える。対応するReactは18・19（`peerDependencies`）。使い方は[page-composition.md](../modules/frontend/page-composition.md)「データ取得の骨格」 |
| FrontendのAPIの呼び出し | openapi-fetch（`openapi-typescript`の生成物からパス・問い合わせ・本文・応答の型を推論する） | MIT（依存の`openapi-typescript-helpers`も同じ）で商用で使える。版の制約は下記。使い方は[page-composition.md](../modules/frontend/page-composition.md) |
| Frontendアイコン | lucide-react（汎用の形）＋自前のSVG（このアプリ固有の概念の形） | 振り分けと線の太さのそろえ方は`frontend/src/components/ui/icons/icons.tsx`。lucideはISC（一部のアイコンはFeather由来でMIT）で商用で使える |
| Backend | Python + FastAPI | バージョンの正本は`backend/requirements.txt` |
| DB | PostgreSQL + PostGIS | 生データ層・派生層・MVT生成（`ST_AsMVT`）の唯一の系統。**取込範囲外は「データ未整備」として扱い、外部APIへのフォールバックを持たない**。ルート生成には`DATABASE_URL`への実接続が必須 |
| ルーティング | 自前のRoad Graph単一構成 | 外部ルーティングAPIへの依存は無い。[route-generation.md](route-generation.md) |
| 地図タイル | OpenFreeMap（APIキー不要）をbackendがプロキシ＋ファイルキャッシュ | 下記「地図タイルプロバイダ」 |
| 天候（予報） | 気象庁MSM（Open-MeteoがAWS Open Dataで公開する前処理済み`.om`をローカル同期） | 外部の気象予報APIを実行時に叩かないため、レート制限・クォータの制約を受けない |
| 天候（実測）・防災 | 気象庁の公開API（アメダス・警報・ナウキャスト・キキクル・洪水予報）・環境省WBGT | 予報と統合しない。数値予報モデルの出力は公式発表の代わりにならない |
| 標高 | 国土地理院DEMタイル（APIキー不要、日本国内限定） | 評価の材料（勾配）は取込バッチだけが叩き、**ルート生成・評価が実行時に取りに行く経路は無い**。地図の地形の表示は、backendが実行時に取りに行って中継し、ディスクに持つ |
| 土地被覆 | Esri × Impact Observatory の10m LULC（GeoTIFF） | リポジトリに持たず、デプロイがVMへ取得して読み取り専用でマウントする |
| 立ち寄り先の地点 | Overture Maps の places（GeoParquet）を DuckDB（MIT）で取込の範囲だけ切り出す | 取得と取込のバッチだけが使う（`backend/requirements-batch.txt`）。利用条件と版の入れ替えは[data-sources.md](data-sources.md) |
| 住所の検索 | `jageocoder`（MIT）＋配布の住所の辞書（街区まで・全国。入れて約1.4GB） | 外部の検索サービス・別のサーバーを使わず、backendが手元の辞書を引く。辞書はリポジトリに持たず、デプロイがVMへ取得して読み取り専用でマウントする。版の制約は下記 |
| 管理データの退避先 | Oracle Cloud Object Storage（非公開のバケット） | 本番VMのtimerが取り直せない管理データを置き、バケットのライフサイクルの規則が古いものを消す。仕組みと登録の手順は[deployment-sync.md](../conventions/deployment-sync.md)付録「管理データのバックアップ」 |
| タスクの流れのゲート | Cloudflare Workers（`tools/flow-gate/wrangler.toml`。Webhookを受けるWorkerと、Cloudflare Accessで守る回答フォームのWorker） | アプリの外の運用の道具で、本番の利用者の経路に無い。トークンは下の「秘密の値とトークン」、決まりは[flow.md](../conventions/flow.md) |

## 地図タイルプロバイダ

`tile.openstreetmap.org`は使わない。bulk／プログラム的アクセスをブロックするポリシーを持ち（`x-blocked`ヘッダーで拒否）、
本番でも開発環境でも安定しない。MapLibre GL JS向けにAPIキー無しで提供されているOpenFreeMapのベクタースタイルを使う。
**利用規約は本番運用の節目ごとに読み直し**（条件は[data-sources.md](data-sources.md)）、必要なら専用プロバイダ（APIキー方式）へ
切り替える。

## `maplibre-gl`のWorkerは自分で配る

`maplibre-gl`はWorkerのスクリプトURLを ``new URL(`./${file}`, import.meta.url)`` という動的テンプレートリテラルで解決し、
Next.jsのバンドラ（Turbopack / Webpack）はこれを静的解析できない。Workerが空のページを読み込み、スタイル処理・タイル取得が
**永久に止まる**（`isStyleLoaded()`が`true`にならない）。

そこで**Workerの実体を`public/`から配り、`setWorkerUrl`でそこを指す**。複製は`frontend/scripts/copy-maplibre-worker.mjs`が
`predev`/`prebuild`/`prebuild:e2e`で`node_modules`から行い、リポジトリには置かない。Workerはsharedチャンクを
**自分のURLからの相対**でimportするため、2本を同じディレクトリへ置く（sharedチャンクはバンドル内と静的配信で二重に配る）。
`configureMaplibreWorker()`（`frontend/src/features/map/maplibreWorker.ts`）は**Mapを作る前に**呼ぶ。

## `@maplibre/maplibre-gl-style-spec`はキャレット無しで完全固定する

このパッケージの`createExpression`は、地図のpaint/filter式が正しいことをテストで確かめる評価器に使っている。地図が実際に
式を評価するのは`maplibre-gl`が内部に持つ同パッケージなので、版がずれるとテストが通る式が実機では別の意味になりうる。
`maplibre-gl`側の依存範囲に収まる版を選び、キャレットで動かないよう固定する。**`maplibre-gl`を上げるときは、上げた先が
要求する範囲にこの固定版が収まっているかを併せて確かめる。**

## `openapi-fetch`は0.16系に留める

0.17系は応答・本文の型を`Readable`/`Writable`（`openapi-typescript-helpers`）で包み直し、**タプルが配列になる**（契約の
`[number, number][]`が`number[][]`として届く）。このアプリの契約は折れ点・分布の階級などでタプルを使うので、推論した応答を
生成物の型（`components["schemas"]`）へ渡すと型検査で落ちる。上流の報告は
[openapi-ts/openapi-typescript#2632](https://github.com/openapi-ts/openapi-typescript/issues/2632)。`package.json`の`^0.16.0`は
0.x系のキャレットなので0.17へは上がらない。**上げるときは、上げた先でタプルを含む応答（例:
`/api/admin/axis-definitions/preview-distribution`の`bins`）の推論した型がタプルのままかを`tsc --noEmit`で確かめる。**

## `jageocoder`は辞書の版が読める版に留める

配布の住所の辞書は、ファイル名の末尾（`_v22`等）で読める`jageocoder`の版が決まっている（`_v22`は2.2.xだけ。辞書に同梱の
READMEの「データ形式について」）。`requirements.txt`は2.2.xで固定してある。**辞書の版を変えずに`jageocoder`だけを上げない**——
CIのテストは足場がその版で書いた小さな辞書を引くので通り、本番の配布の辞書を開いたときに初めて食い違う。上げるときは、
上げた先が読む`_v<NN>`の配布があることを配布の一覧で見て、辞書の版と一緒に上げる（手順は[data-sources.md](data-sources.md)
「版を持つ配布物の入れ替え」）。

## DependabotのPull Requestは、同じ版を取り込んだタスクが閉じる

Dependabotは、masterが同じ版になってもPull Requestを閉じないことがある（閉じる条件は公式の文書に無い）。依存の版上げを
取り込むタスクは、同じ版を出しているDependabotのPull Requestをissueの本文に番号で名指し、完了の条件に
「dependabot の #<番号> が閉じている」を書く（自動モードの判定は、issueが名指したDependabotのPull Requestだけを担当が
閉じてよいものと読む。`tools/flow-gate/settings.json`の`autoMode`）。閉じるのは作る担当で、マージのあとの残りとして済ませる:
`gh pr view <番号> -R hidakagit/ride-compass --json state`が`OPEN`なら
`gh pr close <番号> -R hidakagit/ride-compass --comment "<取り込んだ Pull Request> で同じ版を取り込んだ"`で閉じる。

## Windows: `uvicorn --reload`の多重プロセス

Windowsでは`uvicorn --reload`がリローダーの親プロセスとワーカーの子プロセス（`multiprocessing.spawn`）に分かれる。親だけを
`taskkill`すると子が同じポートに残り、**古い設定・古いコードのまま応答し続ける**。`.env`は`--reload`の監視の外なので、変えたら
完全に起動し直す。挙動が古いままに見えたら、`netstat -ano | findstr :8000`でそのポートを握っている全PIDを`taskkill /F /PID <PID>`で
終えてから起動し直す（`restart-dev.bat`はこのkillを含めて起動し直す）。

## 本番の宛先（frontendのオリジンからbackendへ届くのは一部だけ）

| | 宛先 | 中身 |
|---|---|---|
| frontend | `https://ride-compass-frontend.onrender.com` | Render。backendのCORSの許可に無ければ、`deploy-backend.yml`がデプロイのたびに足す |
| backend | `https://193-123-166-150.sslip.io` | Oracle Cloud VM。VMのnginxがTLS（certbot）を終端し、`127.0.0.1:8000`のコンテナへ渡す。名前はVMの公開IPをsslip.ioで引けるようにしたもので、**IPが変わると宛先も変わる** |

**画面がbackendを呼ぶ宛先はリポジトリに無い。** ブラウザからのAPIは`NEXT_PUBLIC_API_URL`、タイルは
`NEXT_PUBLIC_TILE_BASE_URL`（[static-map-layers.md](../modules/frontend/static-map-layers.md)）で、どちらもRenderのダッシュボードの
環境変数にあり、ビルドのときにJSへ埋め込まれる。

**frontendのオリジンからbackendへ届くのは、`frontend/next.config.ts`のrewritesにあるタイル類と、管理画面の転送
（`/admin/api/…`→backendの`/api/admin/…`、Basic認証をサーバー側で付ける）だけ。** それ以外のAPI（例: `/api/axis-catalog`・
`/health`）をfrontendのオリジンへ投げるとNext.jsのHTMLの404が返る（backendの404はJSON）。本番のAPIを手で叩く・道具から引く
ときは、backendの宛先へ直接投げる。frontend自身の口（`/api/version`）はfrontendのオリジンにだけある。

**手元の道具は、backendの宛先を`backend/.env.oracle.local`の`BACKEND_ORIGIN`から読む**（読み方は`backend/scripts/_prod_env.py`。
例: `axis_apply.py`）。道具のコードに宛先を書き込まない——IPが変わったとき、直すのを各自の`BACKEND_ORIGIN`だけにするため。

## デプロイの反映確認（backend/frontendで注入元が異なる）

デプロイが反映されたかを、どこからでも確かめられるよう、両方にデプロイの識別情報を返す口を置いている。

| | 稼働先 | `commit`の注入元 |
|---|---|---|
| frontend | Render | `RENDER_GIT_COMMIT`（Renderが自動で入れる） |
| backend | Oracle Cloud VM | デプロイワークフローがVM上で`git rev-parse HEAD`を実行し、`GIT_COMMIT`として`docker run`へ渡す |

ローカル開発ではどちらも`null`になる。`started_at`（プロセス起動時刻、モジュール読み込み時に一度だけ評価）で、`commit`が
変わっていなくても再起動が起きたかを確かめられる。確かめ方は、`GET /health`（backend）と`GET /api/version`（frontend）の
`commit`を手元の`git rev-parse HEAD`と突き合わせる。frontendの版は、画面のメニューの「バージョン表示」でも見られる
（`commit`の頭8文字）。

**backendのデプロイは、masterのCIが通ったコミットを、本番プロセスに届く変更があるときだけ出す。** `ci.yml`の
`deploy-backend`が、masterへのpushでbackend・api-contract・frontend・e2e・e2e-scanのジョブが通ったときだけ
`deploy-backend.yml`を呼ぶ（flow-gate・文書の検査は待たない）。呼ばれた側は、本番で動いているコミット（コンテナの
`GIT_COMMIT`）からCIを通ったコミットまでの差分を`scripts/deploy_backend_gate.py`で見て、出すかを決める。

- **差分の起点は直前のpushではなく、本番で動いているコミット**。CIが赤で出せなかった変更も、次にCIを通ったコミットで出る。
- **出すのはCIを通ったそのコミットで、masterの先端ではない**（先端はCIを通っていないことがある）。本番のコミットより古い
  CIの実行は出さない。判定とデプロイは1つのジョブで1本ずつ走る。
- **入れ替えたコンテナが、今ビルドしたコミットとして`/health`に応答するまで待つ**（`docker run -d`は起動の成否を見ない）。
  上限（60秒）までに応答しなければ、コンテナの状態と再起動回数・ログの末尾を出してジョブを失敗させる。応答までの秒数は
  毎回ジョブのログに出るので、起動が遅くなる変更を入れたら、その秒数を見て上限を決め直す。
- **入れ替えたあと、本番のスキーマと出したコードのORMの宣言の差を測る**（同じイメージで`scripts/schema_gap.py`）。差が1件でも
  あればジョブを失敗させ、差の行をログに出す。積み上げ式のmigrationは持たず、差は人が本番で埋める。新しいコードが書く列は
  出す前、古いコードが読む列を消す・新しいコードが宣言した表を作るのは出した後に埋める。**測るのは入れ替えの後で、出すのは
  止めない**（出した後に埋める差がデプロイを止めないように）。差を埋めるまで、デプロイは毎回赤になる。
- **探索のJIT（numba）のコンパイル結果はイメージの組み立てで焼く**（`backend/Dockerfile`の`compile_search_kernels`）。
  焼かないと、置き場がコンテナの書き込み層なので入れ替えで消え、デプロイ後の最初のルート生成がコンパイルを払う。
  **numbaのキャッシュは、組み立てた機械のCPUの型（LLVMのtriple・CPU名・CPUの機能）と、元のファイルの更新時刻・大きさが
  実行時と一致するときだけ読まれる**（numbaの`core/caching.py`: 索引の鍵に`codegen.magic_tuple()`、索引の印に`st_mtime`・
  `st_size`）。今はVMの上で組み立ててそのVMで動かすので一致する。**組み立てを別の機械（CIのランナー等）へ移すときは、実行する
  機械で1回コンパイルする段を別に置く**（移しただけではエラーも出ずに焼いたものが読まれなくなる）。
- 反映はpushからCIの所要だけ遅れる。急ぎの修正でも待つ。待たずに出す手段は`deploy-backend.yml`の手動起動
  （`workflow_dispatch`）で、選んだrefの先端を判定なしで出す。

振り分けの一覧（`deploy_backend_gate.py: DEPLOY_PATHS`と`deploy_backend_gate.py: NOT_DEPLOYED`。gitのpathspecとして
`git diff --name-only`に当てる）は`backend/**`から、イメージに入らないもの（テスト・lint設定等）と、イメージには入るが本番
プロセスが読まないもの（`export_openapi.py`とそれだけが読む表示値の宣言）を外している。表示値の変更は生成物
（`frontend/src/types/generated/`）を経由してfrontendのデプロイで画面へ届く。**外したモジュールを本番側がimportすると、その
変更だけが本番へ届かなくなる**（エラーにならず古い値で動き続ける）。`backend/tests/structure/test_deploy_exclusions.py`が
その一覧とDockerfileから母集団を導いてこれを検査する。

**frontend（Render）のデプロイも、masterのCIが通ったコミットを出す。** `ci.yml`の`deploy-frontend`が、`deploy-backend`と
同じ条件で`deploy-frontend.yml`を呼び、呼ばれた側がRenderのデプロイフックへそのコミットを`ref`で渡す（Render公式の
[Deploy Hooks](https://render.com/docs/deploy-hooks)。フックのURLはリポジトリの秘密`RENDER_FRONTEND_DEPLOY_HOOK_URL`）。

- **Renderの自動デプロイは Off にしてある**（ダッシュボードのサービスの Settings → Auto-Deploy）。「After CI Checks Pass」は
  連携したブランチの**最新のコミットだけ**を、そのコミットのチェックが全部終わってから出す（Render公式の
  [Deploys](https://render.com/docs/deploys)。待つチェックは選べない）ので、担当や見回りが`workflow_dispatch`で長く動く間は
  何も出ない。フックで`ref`を渡して出すと、Renderはそのサービスの自動デプロイを Off にする（同じ文書の「Deploying a specific commit」）。
- **出すかは本番の`/api/version`の`commit`で決める。** CIを通ったコミットが本番のコミットか、その祖先なら出さない。本番の
  コミットが読めない・履歴に無いときは出す。backendと違い変更のパスでは振り分けず、重い検査が走ったmasterのコミットは全部
  出す（文書やタスク管理だけの変更は`ci.yml`の`changes`が重い検査ごと飛ばすので、デプロイも起動しない）。
- **出したあと、本番の`/api/version`がそのコミットになるまで待つ。** Renderは最後に頼まれたデプロイを出す（同じ文書の
  「Handling overlapping deploys」）ので、待たないと古いコミットが新しいコミットを上書きしうる。判定・フック・待ちは1つの
  ジョブで1本ずつ走る。上限（30分）までに変わらなければジョブを落とす（Renderのビルドか起動の失敗で、ダッシュボードの
  Events に出る）。変わるまでの秒数は毎回ジョブのログに出る。
- 待たずに出す手段は`deploy-frontend.yml`の手動起動（`workflow_dispatch`）で、選んだrefの先端を判定なしで出す。

**タイルプロパティを削除する変更は、frontendを先に（または同時に）デプロイする。** backendとfrontendは別々にデプロイされ、
反映は同期しない。プロパティの**追加**は常に後方互換（旧フロントは知らないプロパティを無視する）だが、**削除**を含む世代を
backendが先に配ると、そのプロパティの有無を見ている旧フロントの凡例フィルタが全地物に一致し、対象レイヤーが一時的に
「不明」表示になる。

## CIの実行枠（リポジトリがpublicである間の前提）

**GitHub Actionsの実行時間は、リポジトリがpublicである間は課金も分数の上限も無い**（公式の
[Actionsの課金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)。publicリポジトリで標準の
GitHubホストランナーを使う実行は無料）。残る制約は[Actionsの制限](https://docs.github.com/en/actions/reference/limits)で、
Freeプランでは同時に動くジョブの数と1ジョブの実行時間（6時間）に上限がある。同時実行の上限を超えた分は、空くまで待つ。

この前提の上で、CIは次のように組んである。

- どの出来事でCIが走るかはdocs/conventions/testing-operations.md「検査の置き場（手元・作業ブランチのCI・masterのCI）」が持つ。
  作業ブランチへのpushでは走らせない（検査はPull Requestの実行で済む）。backendの本番へのデプロイは、masterへのpushでCIが
  通ったときだけ`ci.yml`から呼ばれる（上の「デプロイの反映確認」）。
- `ci.yml`は、同じref（master・Pull Requestごと）の実行を1本ずつ動かし、待ちは一番新しい1件だけにする（`concurrency`。後の
  コミットは前の変更を全部含むため）。Pull Requestは新しいpushで走っている実行も打ち切り、masterは走っている実行を最後まで
  走らせる（デプロイが同じ実行の中で走るため）。打ち切った実行のコミットにはCIの結論が残らないので、結論は最新のコミットで
  読む（docs/conventions/testing-operations.md「CIの結論を読む」）。数十秒で終わる`docs-consistency.yml`・`claude-gate.yml`には
  置かない。
- ジョブの分け方・キャッシュ・文書や運用の道具だけの変更で重い検査を飛ばす範囲（`ci.yml: changes`ジョブの`case`）は、
  所要時間と同時実行の枠で決める（理由は各ワークフローのコメント）。
- **masterのpushの`changes`は、成功で終わった実行のコミットと比べる**（masterの祖先のうちpushの実行が成功で終わった一番近い
  コミット）。直前のコミットと比べると、直前の実行が失敗・取り消しで終わった変更が、検査もデプロイもされないまま次の文書
  だけの変更に飛ばされる。
- **タスク管理は製品のCIと分ける。** タスク管理の置き場（`.github/taskflow-paths`。ゲートの`tools/flow-gate/`と担当の
  ワークフロー）の検査とゲートの公開は`claude-gate.yml`が持ち、`ci.yml`はその置き場を読まない。そのため`ci.yml: changes`は
  その置き場だけの変更で重い検査を飛ばし、backend・frontendのデプロイも起動しない。総量の計測
  （`scripts/review_checks.py: TASKFLOW_PREFIXES`）も同じファイルから置き場を読む。
- **ワークフローは`paths`で飛ばさず、いつも起こす。** コードのリポジトリは、master へ入れる前に必須チェック（`ci.yml`の
  `ci-ok`・`docs-consistency.yml`のジョブ・`claude-gate.yml`の`flow-gate`）が通ることを求め、ワークフローごと飛ばすと必須
  チェックが Pending のまま残ってマージできない（公式の「Troubleshooting required status checks」）。重い検査を飛ばすのは
  `changes`ジョブが決め、ジョブの`if`で飛ばしたものはスキップとして必須チェックを通る。
- **飛ばす範囲は、その検査が読む対象から導く。** 飛ばしてよいのは、`ci.yml`のどの検査も読まないパスだけ。文書を読むテストを
  足したら、読む範囲がディレクトリに限られるなら`changes`の`case`でそこを先に当てて入れ直し、全ての文書を読むなら常に走る
  `docs-consistency.yml`でも走らせる。飛ばす運用の道具（`scripts/`の一部）をテストやデプロイが読むようにしたら、`case`から
  その行を外す。飛ばす道具の静的検査は`docs-consistency.yml`が常に走らせる。

**privateにするときは、切り替えの前にこの節を見直す。** 公式の同じページによれば、Freeプランのprivateリポジトリは標準
ランナーで月2,000分までで、支払い方法が未登録なら使い切った時点で実行が止まる（登録済みなら超過分が課金される）。見直すのは、
Pull RequestごとにCIを走らせるか、古い実行を打ち切るか（`concurrency`）、重い検査を飛ばす範囲（`ci.yml: changes`）、
ジョブの分け方とキャッシュ。検査の門をCIだけに置いているので、分数が尽きると検査が止まる。

## 秘密の値とトークン

**どのトークンが誰の名義で、どこへ届き、どこで使われているかは、この表だけが持つ**（GitHub・Cloudflareの画面にもコードにも
まとまって無い）。値はここに書かない。トークンを作る前に、この表で今あるものを使えないかを見る。トークンを作る・消す・
権限や届く範囲を変えるときは、同じ変更でこの表を直す。どの名義でどこへ書くかは[task-flow.md](task-flow.md)「名義」が持つ。

| 入れた場所 | 名前 | 中身（作った人・Resource owner・届く範囲・権限・期限） | 使う所 |
|---|---|---|---|
| hidakagit/ride-compassのActionsの秘密の値 | `CODE_TOKEN` | hidakagitが作ったfine-grained `ride-compass-actions`。Resource ownerはhidakagitで、届くのはhidakagit/ride-compassだけ。Actions・Contents・Issues・Pull requests・Variables・Workflowsは読み書き（Workflowsは担当が`.github/workflows/`をpushするため）、Commit statusesは読むだけ。期限は未記録 | `claude-task.yml`（checkout・Claudeの連携・ghの既定）・`claude-dispatch.yml`（盤面を読み担当を起こす・次の見回りを起こす） |
| 同 | `FLOW_BOT_TOKEN` | hidakagit-botが作ったfine-grained。届くのはridecompass/ride-compass-tasksだけ。Contentsは読み書き。期限2027-09-29 | 担当と流れの道具が置き場へ書く。開発機ではユーザー環境変数の同じ名前 |
| 同 | `CLAUDE_CODE_OAUTH_TOKEN` | Claudeの契約のトークン（GitHubのトークンではない） | `claude-task.yml` |
| 同 | `CLOUDFLARE_API_TOKEN`・`CLOUDFLARE_ACCOUNT_ID` | Cloudflare | ゲートと回答フォームの公開（`claude-gate.yml`） |
| 同 | `ORACLE_VM_HOST`・`ORACLE_VM_SSH_KEY` | 本番のVM | backendのデプロイ |
| 同 | `RENDER_FRONTEND_DEPLOY_HOOK_URL` | Render | frontendのデプロイ |
| ゲートのWorker（`ridecompass-gate`） | `APP_ID`・`APP_KEY`・`WEBHOOK_SECRET` | GitHub Appの鍵とWebhookの秘密 | ゲート |
| 回答フォームのWorker（`ride-compass-answer`） | `APP_ID`・`APP_KEY`・`FORM_TOKEN` | `FORM_TOKEN`はhidakagitが作ったfine-grained `ridecompass-answer-form-2`。Resource ownerはridecompassで、届くのはridecompass/ride-compass-tasksだけ。期限2027-09-29 | 回答フォームの答えをhidakagitの名義で書く |

## DBの版（本番が正本）

**本番DBの版が正本で、CIと`docker-compose.yml`はそれに従う。本番の版を上げたら、同じ変更でCIと`docker-compose.yml`も
上げる**（CIが本番と違う版で合否を決めると、関数・プランナーの挙動の差がCIで通って本番で違う形になる）。

| | PostgreSQL | PostGIS | 入れ方 |
|---|---|---|---|
| 本番 | 18 | 3.6 | Oracle Cloud VM（Ubuntu 24.04・aarch64）へ、PostgreSQL公式のaptリポジトリ（PGDG）のパッケージ |
| CI（`ci.yml`のbackendジョブ） | 18 | 3.6 | `ubuntu-24.04-arm`ランナーへ、本番と同じ配布元・同じパッケージ名で入れる |
| ローカル・クラウドのセッション（`docker-compose.yml`） | 18 | 3.6 | `postgis/postgis:18-3.6`イメージ（Debian） |

- **揃えるのはメジャー版まで。** パッチ・マイナーは同じ配布元の最新に追従する（CIは実行のたびにその時点の最新、本番はVMで
  aptを更新した時点の版）。本番の実際の版は`backend/scripts/run_probe.py --in-container`で`SELECT version()`・
  `postgis_full_version()`を引いて確かめる。CIの版は実行ごとの注釈（`DB`）に出る。
- **DB側のGEOS・PROJ（PostGISの空間演算・座標変換）も、本番・CIともPGDGの版**（`libgeos-c1t64`・`libproj25`・`proj-data`）。
  Ubuntu本体のアーカイブにも同じパッケージ名の古い版があり、PGDGの`postgresql-18-postgis-3`はどちらでも入る。**本番でaptを
  更新するとGEOS・PROJも進む**——CIは実行のたびにPGDGの最新を入れるので、本番のaptを長く止めるとCIだけが先へ進む。本番の
  GEOS・PROJの版も`postgis_full_version()`で読める。
- 開発機（Windows）は別の配布物で、版が揃わない。GEOS・PROJの挙動差が効く検査（土地被覆の帯の形等）はCIで判定する。
- **CIのbackendジョブは本番と同じaarch64で動かす。** `postgis/postgis`のイメージはamd64しか配っていない（Docker Hubの説明の
  「Supported architecture」）ので、arm64のランナーではサービスコンテナにできず、ランナーへ直接入れる。GitHubの標準ランナーの
  arm64は、リポジトリがpublicである間は無料（上の「CIの実行枠」）。
- CIは`backend/Dockerfile`のイメージではなく、ランナーのPython（`setup-python`）でテストする。Pythonの依存はwheelが自前の
  ライブラリ（GEOS・PROJ等）を同梱するので本番と同じになるが、**wheelに同梱されないOSのライブラリ**（例: rasterioが要る
  `libexpat`）の差はCIでは見えず、`deploy-backend.yml`がコンテナを入れ替える前の`import app.main`で止まる。
- データ形式はメジャー版の間で互換が無く、旧版のボリュームは新しい版で開けない。

## 本番PostgreSQLの設定（既定から変えたものと、その理由）

既定から変えた設定はここへ理由つきで残す。**理由の無い設定変更を増やさない**。

**`jit = off`**（`ALTER DATABASE`で両DBへ設定）。材料を引くクエリは材料ごとにCASE式を並べるので式が非常に多く、JITの
コンパイル代が実処理より高くつく（`jit_above_cost`が見る推定コストは式の数でも上がり、行数がそこそこのクエリでも発動する）。
`ALTER DATABASE`の設定は**新規接続から効く**ので、稼働中のコンテナの既存接続には次のデプロイまで反映されない。

## 本番Redisの設定

Redisは「TTL付きキャッシュ、または実データ源へのフォールバックが必ず効くcache-aside」専用の層で、**正本データを持たない**
（方針は[caching.md](../conventions/caching.md)）。本番はOracle Cloud VMへネイティブに入れる（backendコンテナが
`--network=host`なので追加の設定なしで届く）。ローカル開発は`docker-compose.yml`のredisサービス。

`/etc/redis/redis.conf`へ`maxmemory 2gb`・`maxmemory-policy volatile-lru`を設定する（VM全体のメモリをPostgreSQL・backend
コンテナと分け合う配分）。**上限を外さない**（用途を広げたときに同居するVM全体のメモリを圧迫する）。キーはすべてTTL付きなので
`volatile-lru`（TTL付きキーの中からLRUで退避）を選ぶ。

## Docker構成

`docker-compose.yml`（ルート直下）がローカル開発用に frontend / backend / postgres（`postgis/postgis`）/ redis を定義する。
名前付きの永続化ボリュームはpostgresだけが持ち、backendはタイルの永続キャッシュを残すためにホストのディレクトリ
（`backend/data`）を載せる。クラウドのセッション（Claude Code on the web）はこのうちpostgres・redisだけを使い、backend・
frontendはネイティブで動かす（[setup.md](setup.md)「クラウドのセッション」）——クラウドでは外への通信がホストのプロキシ経由で
しか通らず、`apt-get`・`npm ci`を含むbackend・frontendのイメージはビルドの途中で止まる（イメージの取得はdockerdが行うので通る）。

本番はこの構成を使わない——backendはOracle Cloud VM上のDockerコンテナ、frontendはRender、PostgreSQLとRedisはVMへネイティブに置く。
