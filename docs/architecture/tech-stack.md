# 技術選定・実行環境の制約

**コードからは導けない制約だけを書く。** 「このバージョンへ上げられない理由」「本番の設定を
既定から変えた理由」「デプロイの前後関係」は、実装には「そうなっている」事実しか残らず、
この文書だけが持つ。依存ライブラリのバージョン・デプロイ・実行環境に触る変更は、
着手前にここを読む。

## 採用しているもの

| 領域 | 採用 | 備考 |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + MapLibre GL JS + React | バージョンの正本は`frontend/package.json` |
| Frontendスタイリング | Tailwind CSS + Radix UI + `frontend/src/components/ui/`（CSS Modulesは使わない） | 使い分け基準・Design Token・意図的に作らないものは[frontend-design-system.md](../modules/frontend/frontend-design-system.md) |
| Frontendのデータ取得 | TanStack Query（`@tanstack/react-query`） | 取得の共有・取り直し・状態の骨格。MIT（依存の`@tanstack/query-core`も同じ）で、商用で使える。対応するReactは18・19（パッケージの`peerDependencies`）。使い方は[page-composition.md](../modules/frontend/page-composition.md)「データ取得の骨格」 |
| FrontendのAPIの呼び出し | openapi-fetch（`openapi-typescript`の生成物からパス・問い合わせ・本文・応答の型を推論する） | MIT（依存の`openapi-typescript-helpers`も同じ）で、商用で使える。版の制約は下記。使い方は[page-composition.md](../modules/frontend/page-composition.md) |
| Frontendアイコン | lucide-react（汎用の形）＋自前のSVG（このアプリ固有の概念の形） | 振り分けと線の太さのそろえ方は`frontend/src/components/ui/icons/icons.tsx`。lucideはISC（一部のアイコンはFeather由来でMIT）で、商用で使える |
| Backend | Python + FastAPI | バージョンの正本は`backend/requirements.txt` |
| DB | PostgreSQL + PostGIS | 生データ層・派生層・MVT生成（`ST_AsMVT`）の唯一の系統。**取込範囲外は「データ未整備」として扱い、外部APIへのフォールバックを持たない**。ルート生成には`DATABASE_URL`への実接続が必須 |
| ルーティング | 自前のRoad Graph単一構成 | 外部ルーティングAPIへの依存は無い。[route-generation.md](route-generation.md) |
| 地図タイル | OpenFreeMap（APIキー不要）をbackendがプロキシ＋ファイルキャッシュ | 下記「地図タイルプロバイダ」 |
| 天候（予報） | 気象庁MSM（Open-MeteoがAWS Open Dataで公開する前処理済み`.om`をローカル同期） | 外部の気象予報APIを実行時に叩かないため、レート制限・クォータの制約を受けない |
| 天候（実測）・防災 | 気象庁の公開API（アメダス・警報・ナウキャスト・キキクル・洪水予報）・環境省WBGT | 予報と統合しない。数値予報モデルの出力は公式発表の代わりにならない |
| 標高 | 国土地理院DEMタイル（APIキー不要、日本国内限定） | 評価の材料（勾配）は取込バッチだけが叩き、**ルート生成・評価が実行時に取りに行く経路は無い**。地図の地形の表示は、backendが実行時に取りに行って中継し、ディスクに持つ |
| 土地被覆 | Esri × Impact Observatory の10m LULC（GeoTIFF） | リポジトリに持たず、デプロイがVMへ取得して読み取り専用でマウントする |
| 住所の検索 | `jageocoder`（MIT）＋配布の住所の辞書（街区まで・全国。入れて約1.4GB） | 外部の検索サービス・別のサーバーを使わず、backendが手元の辞書を引く。辞書はリポジトリに持たず、デプロイがVMへ取得して読み取り専用でマウントする。版の制約は下記 |
| 管理データの退避先 | Oracle Cloud Object Storage（非公開のバケット） | 本番VMのtimerが取り直せない管理データを置き、バケットのライフサイクルの規則が古いものを消す。仕組みと登録の手順は[deployment-sync.md](../conventions/deployment-sync.md)付録「管理データのバックアップ」 |
| タスクの流れのゲート | Cloudflare Workers（`tools/flow-gate/wrangler.toml`。Webhookを受けるWorkerと、Cloudflare Accessで守る回答フォームのWorker） | アプリの外の運用の道具で、本番の利用者の経路に無い。公開するトークンは下の「秘密の値とトークン」、決まりは[flow.md](../conventions/flow.md) |

## 地図タイルプロバイダ

`tile.openstreetmap.org`は使えない。bulk／プログラム的アクセスに対するブロックポリシーを
持ち（`x-blocked`ヘッダーで拒否）、本番はもちろん開発環境でも安定しない。MapLibre GL JS
向けにAPIキー無しで提供されているOpenFreeMapのベクタースタイルを使っている。
**利用規約は本番運用の節目ごとに読み直し**（条件の記録は[data-sources.md](data-sources.md)）、必要なら専用プロバイダ（APIキー方式）へ
切り替える。

## `maplibre-gl`のWorkerは自分で配る

`maplibre-gl`はWorkerのスクリプトURLを ``new URL(`./${file}`, import.meta.url)`` という動的
テンプレートリテラルで解決する。Next.jsのバンドラ（Turbopack / Webpack のいずれも）はこれを
静的解析できず、Workerが空のページを読み込むため、スタイル処理・タイル取得が**永久に止まる**
（`isStyleLoaded()`が`true`にならない）。

そこで**Workerの実体を`public/`から配り、`setWorkerUrl`でそこを指す**。複製は
`frontend/scripts/copy-maplibre-worker.mjs`が`predev`/`prebuild`で`node_modules`から行い、
リポジトリには置かない。Workerはsharedチャンクを**自分のURLからの相対**でimportするため、
2本を同じディレクトリへ置く。代償は**sharedチャンクを二重に配る**こと（バンドル内と
静的配信で1本ずつ）。

`configureMaplibreWorker()`（`frontend/src/features/map/maplibreWorker.ts`）は**Mapを作る前に**
呼ぶ。呼ばないと上の症状に戻る。

## `@maplibre/maplibre-gl-style-spec`はキャレット無しで完全固定する

このパッケージの`createExpression`は、地図のpaint/filter式が正しいことをテストで検証する
ための評価器として使っている。しかし**地図が実際に式を評価するのは`maplibre-gl`が内部に
持つ同パッケージ**である。両者の版がずれると、テストが通る式が実機では別の意味になりうる
（テストの評価器だけが新しい構文を受け付ける等）。`maplibre-gl`側の依存範囲に収まる版を
選び、キャレットで勝手に動かないよう固定する。**`maplibre-gl`を上げるときは、上げた先が
要求する範囲にこの固定版が収まっているかを併せて確認する。**

## `openapi-fetch`は0.16系に留める

0.17.0は応答・本文の型を`Readable`/`Writable`（`openapi-typescript-helpers`）で包み直し、その変換が配列の要素を
取り出して配列へ戻すため、**タプルが配列になる**（契約の`[number, number][]`が`number[][]`として届く）。このアプリの
契約は折れ点・分布の階級などでタプルを使い、推論した応答を生成物の型（`components["schemas"]`）へ渡すと型検査で落ちる。
上流の報告は[openapi-ts/openapi-typescript#2632](https://github.com/openapi-ts/openapi-typescript/issues/2632)で、
直す変更（#2673・#2842）は2026-09-27時点で取り込まれていない。0.16.0は同じ変換を持たず、実行時の実装は
0.17.0と同じ（差は長さ0の応答の判定だけ）。`package.json`の`^0.16.0`は0.x系のキャレットなので0.17へは上がらない。
**上げるときは、上げた先でタプルを含む応答（例: `/api/admin/axis-definitions/preview-distribution`の`bins`）の
推論した型がタプルのままかを`tsc --noEmit`で確かめる。**

## `jageocoder`は辞書の版が読める版に留める

配布の住所の辞書は、ファイル名の末尾（`_v22`等）で読める`jageocoder`の版が決まっている（`_v22`は2.2.xだけ。
辞書に同梱のREADMEの「データ形式について」）。`requirements.txt`は2.2.xで固定してある。**辞書の版を変えずに
`jageocoder`だけを上げない**——CIのテストは足場がその版の`jageocoder`で書いた小さな辞書を引くので通り、本番の
配布の辞書を開いたときに初めて食い違う。上げるときは、上げた先が読む`_v<NN>`の配布があることを配布の一覧で見て、
辞書の版と一緒に上げる（手順は[data-sources.md](data-sources.md)「版を持つ配布物の入れ替え」）。

## Windows: `uvicorn --reload`の多重プロセス

Windowsでは`uvicorn --reload`がリローダー親プロセスとワーカー子プロセス
（`multiprocessing.spawn`）に分かれる。親だけを`taskkill`すると子が孤児化して同じポートに
残り、**古い設定のまま応答し続ける**。`.env`を編集してもAPIの挙動が変わらない場合は、
`netstat -ano | findstr :8000`でそのポートを握っている全PIDを確認し、すべて終了してから
起動し直す。

- `.env`の変更は`--reload`のファイル監視対象外のため、変更後は完全な再起動が要る。
- 複数ファイルを短時間に連続編集すると`watchfiles`の再読み込みが1回分しか発火せず、
  古いコードのまま動き続けることがある。挙動が古いままに見えたら再起動する。

## 本番の宛先（frontendのオリジンからbackendへ届くのは一部だけ）

| | 宛先 | 中身 |
|---|---|---|
| frontend | `https://ride-compass-frontend.onrender.com` | Render。backendのCORSの許可に無ければ、`deploy-backend.yml`がデプロイのたびに足す |
| backend | `https://193-123-166-150.sslip.io` | Oracle Cloud VM。VMのnginxがTLS（certbot）を終端し、`127.0.0.1:8000`のコンテナへ渡す。名前はVMの公開IPをsslip.ioで引けるようにしたもので、**IPが変わると宛先も変わる** |

**画面がbackendを呼ぶ宛先はリポジトリに無い。** ブラウザからのAPIは`NEXT_PUBLIC_API_URL`、タイルは
`NEXT_PUBLIC_TILE_BASE_URL`（[static-map-layers.md](../modules/frontend/static-map-layers.md)）で、どちらも
Renderのダッシュボードの環境変数にあり、ビルドのときにJSへ埋め込まれる。

**frontendのオリジンからbackendへ届くのは、`frontend/next.config.ts`のrewritesにあるタイル類と、管理画面の
転送（`/admin/api/…`→backendの`/api/admin/…`、Basic認証をサーバー側で付ける）だけ。** それ以外のAPI
（例: `/api/axis-catalog`・`/api/region/dynamic-way-values/…`・`/health`）をfrontendのオリジンへ投げると、
Next.jsのHTMLの404が返る（backendの404はJSON）。本番のAPIを手で叩くとき・道具から引くときは、backendの
宛先へ直接投げる。frontend自身の口（`/api/version`）はfrontendのオリジンにだけある。

**手元の道具は、backendの宛先を`backend/.env.oracle.local`の`BACKEND_ORIGIN`から読む**（読み方は
`backend/scripts/_prod_env.py`。例: `axis_apply.py`）。道具のコードに宛先を書き込まない——IPが変わったとき、
道具の側で直すのが各自の`BACKEND_ORIGIN`だけで済むようにするため。振り出しの見回りは、同じ値をコードのリポジトリの
Actionsの変数`BACKEND_ORIGIN`から読む（宛先が変わったらここも書き換える）。

## デプロイの反映確認（backend/frontendで注入元が異なる）

デプロイが実際にサービスへ反映されたかを、デプロイ操作をしたブラウザ以外からでも確認
できるよう、両方にデプロイ識別情報を返すエンドポイントを置いている。

| | 稼働先 | `commit`の注入元 |
|---|---|---|
| frontend | Render | `RENDER_GIT_COMMIT`（Renderが自動で入れる。設定不要） |
| backend | Oracle Cloud VM | デプロイワークフローがVM上で`git rev-parse HEAD`を実行し、`GIT_COMMIT`として`docker run`へ渡す |

ローカル開発ではどちらの環境変数も無いため`null`になる。`started_at`（プロセス起動時刻、
モジュール読み込み時に一度だけ評価）は、デプロイのたびに再起動される運用のため直近
デプロイの目安にもなる——`commit`が変わっていなくても、再起動自体が起きたかを確認できる。

確認は`GET /health`（backend）と`GET /api/version`（frontend）の`commit`を、手元の
`git rev-parse HEAD`と突き合わせる。

**backendのデプロイは、masterのCIが通ったコミットを、本番プロセスに届く変更があるときだけ
出す。** `ci.yml`の`deploy-backend`が、masterへのpushでbackend・api-contract・frontend・e2e・e2e-scanの
ジョブが通ったときだけ`deploy-backend.yml`を呼ぶ——どれかが赤ならデプロイは起動しない（flow-gate・文書の検査は待たない）。呼ばれた側は、本番で
動いているコミット（コンテナの`GIT_COMMIT`）からCIを通ったコミットまでの差分を
`scripts/deploy_backend_gate.py`で見て、出すかを決める。

- **差分の起点は直前のpushではなく、本番で動いているコミット。** CIが赤で出せなかった変更は、
  次にCIを通ったコミットの差分にそのまま含まれて出る（直前のpushとの差分では、テストだけを
  直したコミットがコードの変更を運ばず、その変更が次の変更まで出なくなる）。
- **出すのはCIを通ったそのコミットで、masterの先端ではない**（先端はCIを通っていないことがある）。
  後から終わった古いCIの実行は、本番のコミットより古ければ出さない。判定とデプロイは1つの
  ジョブで1本ずつ走る。
- **入れ替えたコンテナが、今ビルドしたコミットとして`/health`に応答するまで待つ。** `docker run -d`は起動の成否を
  見ないため、起動が止まったまま作り直しや再起動を繰り返すコンテナでもUpのまま成功扱いになる。上限までに応答しなければ、
  コンテナの状態と再起動回数・ログの末尾を出してジョブを失敗させる。応答までの秒数は毎回ジョブのログに出る。上限は60秒で、
  本番の実測（コンテナを入れ替えてから応答まで4秒）の十数倍——起動時に走るのはDBからの軸定義と較正値の読み込みだけで、
  上限に届くのは起動が止まったときに限る。起動が遅くなる変更を入れたら、ログの秒数を見て上限を決め直す。
- **入れ替えたあと、本番のスキーマと出したコードのORMの宣言の差を測る**（同じイメージで`scripts/schema_gap.py`）。
  差が1件でもあればジョブを失敗させ、差の行をログに出す。積み上げ式のmigrationは持たず、差は人が本番で埋める。
  埋めるのは、新しいコードが書く列なら出す前、古いコードが読む列を消す・新しいコードが宣言した表を作るなら出した後で、
  **測るのは入れ替えの後、出すのは止めない**——前で止めると、出した後に埋める差がデプロイを止めて埋められなくなる。
  赤のまま次のデプロイも出る（判定は本番のコミットからの差分で、前の実行の成否を見ない）ので、差を埋めるまで毎回赤になる。
- **探索のJIT（numba）のコンパイル結果はイメージの組み立てで焼く**（`backend/Dockerfile`の`compile_search_kernels`）。
  焼かないと、コンパイル結果の置き場がコンテナの書き込み層のためコンテナの入れ替えで消え、デプロイ後の最初のルート
  生成がコンパイルを払う（本番の都心40kmで初回11.9秒・2回目5.1秒、差の大半がコンパイル）。
  **numbaのキャッシュは、組み立てた機械のCPUの型
  （LLVMのtriple・CPU名・CPUの機能）と、元のファイルの更新時刻・大きさが実行時と一致するときだけ読まれる**
  （numbaの`core/caching.py`: 索引の鍵に`codegen.magic_tuple()`、索引の印に`st_mtime`・`st_size`）。今はVMの上で
  組み立ててそのVMで動かすので一致する。**組み立てを別の機械（CIのランナー等）へ移すと、エラーも出ずに焼いたものが
  読まれなくなり、初回のコンパイルが戻る**——移すときは、実行する機械で1回コンパイルする段を別に置く。
- **CIを待つぶん、反映はpushからCIの所要だけ遅れる。** 急ぎの修正でも待つ。待たずに出す手段は
  `deploy-backend.yml`の手動起動（`workflow_dispatch`）で、選んだrefの先端を判定なしで出す。

振り分けの一覧（`deploy_backend_gate.py: DEPLOY_PATHS`と`deploy_backend_gate.py: NOT_DEPLOYED`。gitのpathspecとして
`git diff --name-only`に当てさせる）は`backend/**`から、イメージに入らないもの（テスト・lint設定等）と、イメージには入るが本番
プロセスが読まないもの（`export_openapi.py`とそれだけが読む表示値の宣言）を外している。
表示値の変更は生成物（`frontend/src/types/generated/`）を経由してfrontendのデプロイで
画面へ届くため、backendのコンテナを入れ替える理由にならない。**外したモジュールを本番側が
importすると、その変更だけが本番へ届かなくなる**（エラーにならず古い値で動き続ける）。
`backend/tests/structure/test_deploy_exclusions.py`がその一覧とDockerfileから母集団を
導いてこれを検査する。

**frontend（Render）のデプロイも、masterのCIが通ったコミットを出す。** `ci.yml`の`deploy-frontend`が、
`deploy-backend`と同じ条件で`deploy-frontend.yml`を呼び、呼ばれた側がRenderのデプロイフックへそのコミットを
`ref`で渡す（Render公式の[Deploy Hooks](https://render.com/docs/deploy-hooks)。フックのURLはリポジトリの秘密
`RENDER_FRONTEND_DEPLOY_HOOK_URL`）。

- **Renderの自動デプロイは Off にしてある**（ダッシュボードのサービスの Settings → Auto-Deploy）。「After CI
  Checks Pass」は連携したブランチの**最新のコミットだけ**を、そのコミットのチェックが全部終わってから出す
  （Render公式の[Deploys](https://render.com/docs/deploys)。待つチェックは選べない）。Claudeの担当や見回りは
  `workflow_dispatch`で動き、起こした時点のmasterの先頭にチェックを付けて長く動くので、それらが動き続ける間は
  何も出ない。フックで`ref`を渡して出すと、Renderはそのサービスの自動デプロイを Off にする（同じ文書の
  「Deploying a specific commit」）。
- **出すかは本番の`/api/version`の`commit`で決める。** CIを通ったコミットが本番のコミットか、その祖先なら出さない
  （後から終わった古いCIの実行）。本番のコミットが読めない・履歴に無いときは出す。backendと違い変更のパスでは
  振り分けない——重い検査が走ったmasterのコミットは全部出す（文書やタスク管理だけの変更は`ci.yml`の`changes`が
  重い検査ごと飛ばすので、デプロイも起動しない）。
- **出したあと、本番の`/api/version`がそのコミットになるまで待つ。** Renderは最後に頼まれたデプロイを出す
  （同じ文書の「Handling overlapping deploys」）ので、待たずに次へ進むと古いコミットが新しいコミットを上書きしうる。
  判定・フック・待ちは1つのジョブで1本ずつ走る。上限（30分）までに変わらなければジョブを落とす——Renderのビルドか
  起動が失敗している（ダッシュボードの Events に出る）。変わるまでの秒数は毎回ジョブのログに出る。
- 待たずに出す手段は`deploy-frontend.yml`の手動起動（`workflow_dispatch`）で、選んだrefの先端を判定なしで出す。

**タイルプロパティを削除する変更はデプロイ順序に制約がある。** backendとfrontendは別
サービスとして独立にデプロイされ、反映タイミングは同期しない。プロパティの**追加**は
常に後方互換（旧フロントは知らないプロパティを無視する）だが、**削除**を含む世代を
backendが先に配信すると、そのプロパティの有無を見ている旧フロントの凡例フィルタが
全地物に一致し、対象レイヤーが一時的に「不明」表示になる。frontendを先に（または
同時に）デプロイする。

## CIの実行枠（リポジトリがpublicである間の前提）

**GitHub Actionsの実行時間は、リポジトリがpublicである間は課金も分数の上限も無い。** GitHubの
公式（[Actionsの課金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)）は、
publicリポジトリで標準のGitHubホストランナーを使う実行を無料としている。残る制約は
[Actionsの制限](https://docs.github.com/en/actions/reference/limits)で、Freeプランでは同時に
動くジョブの数と1ジョブの実行時間（6時間）に上限がある。同時実行の上限を超えた分は失敗せず、
空くまで待つ。

この前提の上で、CIは次のように組んである。

- どの出来事でCIが走るかはdocs/conventions/testing-operations.md「検査の置き場（手元・作業ブランチのCI・masterのCI）」が持つ。
  作業ブランチへのpushで走らせないのは、検査はPull Requestの実行で済み、誰も待たないpushの実行で枠を使わないため。
  backendの本番へのデプロイは、masterへの
  pushでCIが通ったときだけ`ci.yml`から呼ばれる（上の「デプロイの反映確認」）。
- `ci.yml`は、同じref（master・Pull Requestごと）の実行を1本ずつ動かし、待ちは一番新しい1件だけにする（`concurrency`）。
  後のコミットは前の変更を全部含み、古いコミットの実行はデプロイにもマージの判断にも使わないため。Pull Requestは
  新しいpushで走っている実行も打ち切り、masterは走っている実行を最後まで走らせる（デプロイが同じ実行の中で走るので、
  途中で切らない）。打ち切った・待ちから外した実行のコミットにはCIの結論が残らないので、結論は最新のコミットで読む
  （docs/conventions/testing-operations.md「CIの結論を読む」）。数十秒で終わる`docs-consistency.yml`・`claude-gate.yml`には置かない
  （待ちが積もらない）。
- ジョブの分け方・キャッシュ・文書や運用の道具だけの変更で重い検査を飛ばす範囲（`ci.yml: changes`ジョブの
  `case`）は、所要時間と同時実行の枠で決める（理由は各ワークフローのコメント）。
- **タスク管理は製品のCIと分ける。** タスク管理の置き場（`.github/taskflow-paths`。ゲートの`tools/flow-gate/`と
  担当のワークフロー）の検査とゲートの公開は`claude-gate.yml`が持ち、`ci.yml`はその置き場を読まない。そのため
  `ci.yml: changes`はその置き場だけの変更で重い検査を飛ばし、backend・frontendのデプロイも起動しない。
  置き場の定義は、総量の計測（`scripts/review_checks.py: TASKFLOW_PREFIXES`）も同じファイルから読む。
- **ワークフローは`paths`で飛ばさず、いつも起こす。** コードのリポジトリは、master へ入れる前に必須チェック
  （`ci.yml`の`ci-ok`・`docs-consistency.yml`のジョブ・`claude-gate.yml`の`flow-gate`）が通ることを求める。ワークフローごと飛ばすと必須チェックが Pending のまま残り、
  Pull Request がマージできない（公式の「Troubleshooting required status checks」）。重い検査を飛ばすのは
  `changes`ジョブが決め、ジョブの`if`で飛ばしたものはスキップとして必須チェックを通る。
- **飛ばす範囲は、その検査が読む対象から導く。** 飛ばしてよいのは、`ci.yml`のどの検査も読まないパスだけ。
  文書を読むテストを足したら、読む範囲がディレクトリに限られるなら`changes`の`case`でそこを先に当てて入れ直し、
  全ての文書を読むなら常に走る`docs-consistency.yml`でも走らせる。飛ばす運用の道具（`scripts/`の一部）を
  テストやデプロイが読むようにしたら、`case`からその行を外す。飛ばす道具の静的検査は`docs-consistency.yml`が
  常に走らせる。

**privateにしたら、この節の前提が崩れる。** 公式の同じページによれば、Freeプランのprivate
リポジトリは標準ランナーで月2,000分までで、支払い方法が未登録なら使い切った時点で実行が止まる
（登録済みなら超過分が課金される）。privateへ切り替えるときは、切り替えの前に次を見直す:
Pull RequestごとにCIを走らせるか、古い実行を打ち切るか（`concurrency`）、文書・運用の道具
だけの変更で重い検査を飛ばす範囲（`ci.yml: changes`）、ジョブの分け方とキャッシュ。検査の門を
CIだけに置いているため、CIの分数が尽きると検査そのものが止まる。

## 秘密の値とトークン

**どのトークンが誰の名義で、どこへ届き、どこで使われているかは、GitHub・Cloudflareの画面にもコードにも
まとまって無く、この表だけが持つ。** 値はここに書かない。トークンを作る前に、この表で今あるものを使えないかを
見る。トークンを作る・消す・権限や届く範囲を変えるときは、同じ変更でこの表を直す。どの名義でどこへ書くかの
決まりは[flow.md](../conventions/flow.md)「担当」の「名義」が持つ。

| 入れた場所 | 名前 | 中身（作った人・Resource owner・届く範囲・権限・期限） | 使う所 |
|---|---|---|---|
| hidakagit/ride-compassのActionsの秘密の値 | `CODE_TOKEN` | hidakagitが作ったfine-grained `ride-compass-actions`。Resource ownerはhidakagitで、届くのはhidakagit/ride-compassだけ。Actions・Contents・Issues・Pull requests・Variablesは読み書き、Commit statusesは読むだけ。期限は未記録 | `claude-task.yml`（checkout・Claudeの連携・ghの既定）・`claude-dispatch.yml`（盤面を読み担当を起こす・次の見回りを起こす） |
| 同 | `FLOW_BOT_TOKEN` | hidakagit-botが作ったfine-grained。届くのはridecompass/ride-compass-tasksだけ。Contentsは読み書き（担当の手番の記録をリリースへ置く）。期限2027-09-29 | 担当と流れの道具が置き場へ書く・ゲートの公開のあと`refresh.js`。開発機ではユーザー環境変数の同じ名前 |
| 同 | `CLAUDE_CODE_OAUTH_TOKEN` | Claudeの契約のトークン（GitHubのトークンではない） | `claude-task.yml` |
| 同 | `CLOUDFLARE_API_TOKEN`・`CLOUDFLARE_ACCOUNT_ID` | Cloudflare | ゲートと回答フォームの公開（`claude-gate.yml`） |
| 同 | `ORACLE_VM_HOST`・`ORACLE_VM_SSH_KEY` | 本番のVM | backendのデプロイ |
| 同 | `RENDER_FRONTEND_DEPLOY_HOOK_URL` | Render | frontendのデプロイ |
| ゲートのWorker（`ridecompass-gate`） | `APP_ID`・`APP_KEY`・`WEBHOOK_SECRET` | GitHub Appの鍵とWebhookの秘密 | ゲート |
| 回答フォームのWorker（`ride-compass-answer`） | `APP_ID`・`APP_KEY`・`FORM_TOKEN` | `FORM_TOKEN`はhidakagitが作ったfine-grained `ridecompass-answer-form-2`。Resource ownerはridecompassで、届くのはridecompass/ride-compass-tasksだけ。期限2027-09-29 | 回答フォームの答えをhidakagitの名義で書く |

## DBの版（本番が正本）

**本番DBの版が正本で、CIと`docker-compose.yml`はそれに従う。本番の版を上げたら、同じ変更で
CIと`docker-compose.yml`も上げる。** CIが本番と違う版で合否を決めると、関数・プランナーの
挙動の差がCIで通って本番で違う形になる。

| | PostgreSQL | PostGIS | 入れ方 |
|---|---|---|---|
| 本番 | 18 | 3.6 | Oracle Cloud VM（Ubuntu 24.04・aarch64）へ、PostgreSQL公式のaptリポジトリ（PGDG）のパッケージ |
| CI（`ci.yml`のbackendジョブ） | 18 | 3.6 | `ubuntu-24.04-arm`ランナーへ、本番と同じ配布元・同じパッケージ名で入れる |
| ローカル・クラウドのセッション（`docker-compose.yml`） | 18 | 3.6 | `postgis/postgis:18-3.6`イメージ（Debian） |

- **揃えるのはメジャー版まで。** パッチ・マイナーは同じ配布元の最新に追従する（CIは実行の
  たびにその時点の最新、本番はVMでaptを更新した時点の版）。本番の実際の版は
  `backend/scripts/run_probe.py --in-container`で`SELECT version()`・`postgis_full_version()`を
  引いて確かめる。CIの版は実行ごとの注釈（`DB`）に出る。
- **DB側のGEOS・PROJ（PostGISの空間演算・座標変換を担う）も、本番・CIともPGDGの版**
  （`libgeos-c1t64`・`libproj25`・`proj-data`）。Ubuntu本体のアーカイブにも同じパッケージ名の
  古い版があり、PGDGの`postgresql-18-postgis-3`はどちらでも入る。**本番でaptを更新すると
  GEOS・PROJも進む**——CIは実行のたびにPGDGの最新を入れるので、本番のaptを長く止めると
  CIだけが先へ進む。本番の実際のGEOS・PROJの版も`postgis_full_version()`（上）で読める。
- 開発機（Windows）は別の配布物で、版が揃わない（PostgreSQL 18.6・PostGIS 3.6.2・
  GEOS 3.14.1dev・PROJ 8.2.1。2026-09-23）。GEOS・PROJの挙動差が効く検査（土地被覆の帯の形等）は
  CIで判定する。
- **CIのbackendジョブは本番と同じaarch64で動かす。** `postgis/postgis`のイメージはamd64しか
  配っていない（Docker Hubの説明の「Supported architecture」）ため、arm64のランナーでは
  サービスコンテナにできず、ランナーへ直接入れている。GitHubの標準ランナーのarm64は、
  リポジトリがpublicである間は無料（下の「CIの実行枠」）。
- CIは`backend/Dockerfile`のイメージの中ではなく、ランナーのPython（`setup-python`）で
  テストする。Pythonの依存はwheelが自前のライブラリ（GEOS・PROJ等）を同梱するため本番と
  同じものになるが、**wheelに同梱されないOSのライブラリ**（例: rasterioが要る`libexpat`）の
  差はCIでは見えない。それは`deploy-backend.yml`がコンテナを入れ替える前の
  `import app.main`で止まる。
- `postgis/postgis`の18以降のイメージは、データの置き場（`VOLUME`）が`/var/lib/postgresql`で、
  17以前（`/var/lib/postgresql/data`）と違う。データ形式もメジャー版の間で互換が無く、
  旧版のボリュームは新しい版で開けない。

## 本番PostgreSQLの設定（既定から変えたものと、その理由）

既定から変えた設定はここへ理由つきで残す。**理由の無い設定変更を増やさない**——
なぜそうなっているか分からない値は、次に誰かが戻すか、別の値を足して悪化させる。

**`jit = off`**（`ALTER DATABASE`で両DBへ設定）。材料を引くクエリは材料ごとにCASE式を
並べるため式が非常に多く、JITのコンパイル代を回収できない。PostgreSQL自身の出力:

```
JIT: Functions: 45
Timing: ... Optimization 369.2ms, Emission 440.7ms, Total 924.7ms
Execution Time: 1605.6 ms      （jit=off なら 678.6 ms）
```

実行1,605msのうち925msがコンパイルそのもので、実処理の678msより高い。発動条件の
`jit_above_cost`は推定コストの高さを見るが、推定コストは行数だけでなく**式の数**でも
上がるため、式が多いだけで行数はそこそこのクエリでも発動する。**式の少ないクエリは
ほぼ変わらず、式の多いクエリだけが1.7倍速くなる**という非対称が、この説明を裏づける。

`ALTER DATABASE`の設定は**新規接続から効く**。稼働中のコンテナの既存接続には次の
デプロイまで反映されない。

## 本番Redisの設定

Redisは「TTL付きキャッシュ、または実データ源へのフォールバックが必ず効くcache-aside」
専用の層で、**正本データを持たない**（方針は[caching.md](../conventions/caching.md)）。
本番はOracle Cloud VMへネイティブに導入する（backendコンテナが`--network=host`のため
追加設定なしで到達できる）。ローカル開発は`docker-compose.yml`のredisサービス。

`/etc/redis/redis.conf`へ`maxmemory 2gb`・`maxmemory-policy volatile-lru`を設定する
（VM全体のメモリをPostgreSQL・backendコンテナと分け合うための配分）。**上限を外すと、
用途を広げたときに同居するVM全体のメモリを圧迫する。** 現行のキーはすべてTTL付きの
ため`volatile-lru`（TTL付きキーの中からLRUで退避）を選ぶ。

## Docker構成

`docker-compose.yml`（ルート直下）がローカル開発用に frontend / backend / postgres
（`postgis/postgis`）/ redis を定義する。名前付きの永続化ボリュームはpostgresだけが持ち、backendは
タイルの永続キャッシュを残すためにホストのディレクトリ（`backend/data`）を載せる。
クラウドのセッション（Claude Code on the web）はこのうちpostgres・redisだけを使い、
backend・frontendはネイティブで動かす（[setup.md](setup.md)「クラウドのセッション」）。
クラウドでは外への通信がホストのプロキシ経由でしか通らず、コンテナの中からは直接出られないため、
`apt-get`・`npm ci`を含むbackend・frontendのイメージはビルドの途中で止まる（イメージの取得は
dockerdが行うので通る）。

本番はこの構成をそのまま使わない——backendはOracle Cloud VM上のDockerコンテナ、
frontendはRender、PostgreSQLとRedisはVMへネイティブに置く。
