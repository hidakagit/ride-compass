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
| 立ち寄り先の地点 | Overture Maps の places（GeoParquet）を DuckDB（MIT）で取込の範囲だけ切り出す | 取得と取込のバッチだけが使う（`backend/requirements-batch.txt`）。利用条件と版の入れ替えは[data-sources.md](data-sources.md) |
| 管理データの退避先 | Oracle Cloud Object Storage（非公開のバケット） | 本番VMのtimerが取り直せない管理データを置き、バケットのライフサイクルの規則が古いものを消す。仕組みと登録の手順は[production-data/SKILL.md](../../.claude/skills/production-data/SKILL.md)付録「管理データのバックアップ」 |
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
`frontend/scripts/copy-maplibre-worker.mjs`が`predev`/`prebuild`/`prebuild:e2e`で`node_modules`から行い、
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

## DependabotのPull Requestは、同じ版を取り込んだタスクが閉じる

Dependabotは、masterが同じ版になってもPull Requestを閉じないことがあり、閉じる条件は公式の文書に無い。依存の版上げを
取り込むタスクは、同じ版を出しているDependabotのPull Requestをissueの本文に番号で名指し、完了の条件に
「dependabot の #<番号> が閉じている」を書く（判定役は、issueが名指したDependabotのPull Requestだけを担当が閉じてよいものと
読む。`.github/claude-task/settings.json`の`autoMode`）。閉じるのは作る担当で、マージのあとの残りとして済ませる:
`gh pr view <番号> -R ridecompass/ride-compass --json state`が`OPEN`なら
`gh pr close <番号> -R ridecompass/ride-compass --comment "<取り込んだ Pull Request> で同じ版を取り込んだ"`で閉じる。

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

**画面がbackendを呼ぶ宛先は、コードのリポジトリの変数`BACKEND_ORIGIN`にある。** ブラウザからのAPIは`NEXT_PUBLIC_API_URL`、タイルは
`NEXT_PUBLIC_TILE_BASE_URL`（[static-map-layers.md](../modules/frontend/static-map-layers.md)）、rewritesと管理画面の転送の先は
`BACKEND_INTERNAL_URL`で、`deploy-frontend.yml`が3つとも`BACKEND_ORIGIN`の値を像のビルドへ渡し、ビルドのときに埋め込まれる。

**frontendのオリジンからbackendへ届くのは、`frontend/next.config.ts`のrewritesにあるタイル類と、管理画面の
転送（`/admin/api/…`→backendの`/api/admin/…`、Basic認証をサーバー側で付ける）だけ。** それ以外のAPI
（例: `/api/axis-catalog`・`/api/region/dynamic-way-values/…`・`/health`）をfrontendのオリジンへ投げると、
Next.jsのHTMLの404が返る（backendの404はJSON）。本番のAPIを手で叩くとき・道具から引くときは、backendの
宛先へ直接投げる。frontend自身の口（`/api/version`）はfrontendのオリジンにだけある。

**手元の道具は、backendの宛先を`backend/.env.oracle.local`の`BACKEND_ORIGIN`から読む**（読み方は
`backend/scripts/_prod_env.py`。例: `axis_apply.py`）。道具のコードに宛先を書き込まない——IPが変わったとき、
道具の側で直すのが各自の`BACKEND_ORIGIN`だけで済むようにするため。

## デプロイの反映確認（backend/frontendで注入元が異なる）

デプロイが実際にサービスへ反映されたかを、デプロイ操作をしたブラウザ以外からでも確認
できるよう、両方にデプロイ識別情報を返すエンドポイントを置いている。

| | 稼働先 | `commit`の注入元 |
|---|---|---|
| frontend | Render | `deploy-frontend.yml`が像のビルドへコミットを渡し、像の`GIT_COMMIT`に入れる（`frontend/Dockerfile`） |
| backend | Oracle Cloud VM | デプロイワークフローがVM上で`git rev-parse HEAD`を実行し、`GIT_COMMIT`として`docker run`へ渡す |

ローカル開発ではどちらの環境変数も無いため`null`になる。`started_at`（プロセス起動時刻、
モジュール読み込み時に一度だけ評価）は、デプロイのたびに再起動される運用のため直近
デプロイの目安にもなる——`commit`が変わっていなくても、再起動自体が起きたかを確認できる。

確認は`GET /health`（backend）と`GET /api/version`（frontend）の`commit`を、手元の
`git rev-parse HEAD`と突き合わせる。frontendの版は、画面のメニューの「バージョン表示」でも見られる（`commit`の頭8文字）。

**backendのデプロイは、masterのCIが通ったコミットを、本番プロセスに届く変更があるときだけ
出す。** `ci.yml`の`deploy-backend`が、masterへのpushでbackend・api-contract・frontend・e2e・e2e-scanの
ジョブが通ったときだけ`deploy-backend.yml`を呼ぶ——どれかが赤ならデプロイは起動しない（flow-gate・文書の検査は待たない）。呼ばれた側は、本番で
動いているコミット（コンテナの`GIT_COMMIT`）からCIを通ったコミットまでの差分を
`backend/scripts/deploy_backend_gate.py`で見て、出すかを決める。

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
  差が1件でもあればジョブを失敗させ、差の行をログに出す。積み上げ式のmigrationは持たず、差は本番で埋める（打つのは開発機の対話のセッションで、`.claude/skills/dev-session/SKILL.md`の「本番へ書く」）。
  埋めるのは、新しいコードが書く・読む表や列なら出す前（.claude/rules/deployment-sync.md「コミットと同時に揃えるもの」）、
  古いコードが読む列を消す・新しいコードが宣言しただけで読まない表を作るなら出した後で、
  **測るのは入れ替えの後、出すのは止めない**——前で止めると、出した後に埋める差がデプロイを止めて埋められなくなる。
  赤のまま次のデプロイも出る（判定は本番のコミットからの差分で、前の実行の成否を見ない）ので、差を埋めるまで毎回赤になる。
  下の「本番でルートを作る確かめ」とは別の段にし、互いの失敗で飛ばさない（差が続く間も確かめは回る）。
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
プロセスが読まないもの（`export_openapi.py`とそれだけが読む表示値の宣言）を外している。`backend/ops/`（VMのホストで動く
systemdのユニットとシェル）はイメージに入らないが外さない——デプロイがVMの作業コピーをそのコミットへ揃えて
`systemctl daemon-reload`を打つことでだけ届く。
表示値の変更は生成物（`frontend/src/types/generated/`）を経由してfrontendのデプロイで
画面へ届くため、backendのコンテナを入れ替える理由にならない。**外したモジュールを本番側が
importすると、その変更だけが本番へ届かなくなる**（エラーにならず古い値で動き続ける）。
`backend/tests/structure/test_deploy_exclusions.py`がその一覧とDockerfileから母集団を
導いてこれを検査する。

**frontend（Render）のデプロイも、masterのCIが通ったコミットを出す。** `ci.yml`の`deploy-frontend`が、
`deploy-backend`と同じ条件で`deploy-frontend.yml`を呼ぶ。呼ばれた側は、そのコミットから`frontend/Dockerfile`で像を
ビルドしてGitHubのコンテナの置き場（`ghcr.io/<リポジトリの持ち主>/ride-compass-frontend:<コミット>`、公開）へ置き、
Renderのデプロイフックへその像を`imgURL`で渡す（Render公式の[Deploy Hooks](https://render.com/docs/deploy-hooks)。
フックのURLはリポジトリの秘密`RENDER_FRONTEND_DEPLOY_HOOK_URL`）。

- **Renderではビルドしない。** Renderのサービスは、GitHubのリポジトリではなく上の像から出す形にしてある（ダッシュボードの
  サービスの Settings → Source）。Renderのワークスペースのビルドの時間は無料のプランで月500分で、使い切るとその月の残りは
  ビルドを止める（Render公式の[Build pipeline](https://render.com/docs/build-pipeline)）。公開のリポジトリのGitHub Actionsは
  無料なので、ビルドはActionsでする。フックの`imgURL`は、タグ以外がサービスに設定した像のURLと同じでないと断られる
  （同じDeploy Hooksの文書）ので、リポジトリの持ち主が変わったらサービスの像のURLも直す。
- **出すかは本番の`/api/version`の`commit`で決める。** CIを通ったコミットが本番のコミットか、その祖先なら出さない
  （後から終わった古いCIの実行）。本番のコミットが読めない・履歴に無いときは出す。このワークフローは変更のパスでは
  振り分けず、`ci.yml`が`frontend/`の変更があるときだけ呼ぶ（下の「CIの実行枠」）。
- **出したあと、本番の`/api/version`がそのコミットになるまで待つ。** Renderは最後に頼まれたデプロイを出す
  （同じ文書の「Handling overlapping deploys」）ので、待たずに次へ進むと古いコミットが新しいコミットを上書きしうる。
  判定・ビルド・フック・待ちは1つのジョブで1本ずつ走る。上限（30分）までに変わらなければジョブを落とす——Renderの
  像の取得か起動が失敗している（ダッシュボードの Events に出る）。変わるまでの秒数は毎回ジョブのログに出る。
- 待たずに出す手段は`deploy-frontend.yml`の手動起動（`workflow_dispatch`）で、選んだrefの先端を判定なしで出す。

**タイルプロパティを削除する変更はデプロイ順序に制約がある。** backendとfrontendは別
サービスとして独立にデプロイされ、反映タイミングは同期しない。プロパティの**追加**は
常に後方互換（旧フロントは知らないプロパティを無視する）だが、**削除**を含む世代を
backendが先に配信すると、そのプロパティの有無を見ている旧フロントの凡例フィルタが
全地物に一致し、対象レイヤーが一時的に「不明」表示になる。frontendを先に（または
同時に）デプロイする。

## 本番でルートを作る確かめ

**本番のbackendで、利用者と同じ操作（ルートを作ってレンズを替える）が壊れていないかを外から見る。** CIの層は
どれもこの組を本物の応答で通さない（e2eは応答がモックで、`frontend/e2e-live/`はCIに載らず、担当が変更のときに手で回すだけ）。
`backend/scripts/prod_route_check.py`が、軸カタログを1回読み、画面の既定の条件・backendの既定の重みで生成を1回頼み、
終わるまで結果を聞く。候補が0件か、カタログのどれかの軸について、候補1のどの区間もその軸のレンズが塗る値
（軸カタログの`map_paint.value`が指す欄）を持たなければ失敗にする。区間ごとの値の有無は実データで変わるので、
全区間が欠けたときだけ落とす。本番には書き込まない。

- **回すのは2か所。** `deploy-backend.yml`が出したあと（出さなかった実行・入れ替えの段で落ちた実行では回さない。
  スキーマの差の段の成否には左右されない）と、
  `prod-route-check.yml`が毎日1回。本番の値はデプロイを伴わずにも変わる（派生データの作り直し・取込・軸スタジオでの
  軸の変更・外部の観測の取込の止まり）ので、デプロイのあとだけでは次のデプロイまで気づけない。どちらも落ちたら
  GitHub Actionsの失敗の知らせが届き、出したものは戻さない。決まった時刻の起動（`schedule`）は、GitHubが混むと遅れ、
  ひどく混むと取りこぼされ、publicのリポジトリに60日動きが無いと止められる（公式の「Events that trigger workflows」の
  `schedule`）。
- **上限**: 生成を待つのは`backend/scripts/prod_route_check.py: GENERATION_LIMIT_SECONDS`（120）秒までで、超えたら失敗にする。段には`timeout-minutes`の3分を置く。
  2026-10-10に本番で同じ条件を測った値は、デプロイで再起動した直後の1回目が生成36.6秒（結果を聞いた回数21）、2回目以降が
  約4秒で、上限は再起動の直後の約3倍。デプロイのあとの確かめはいつも再起動の直後の形になる。
- **利用者への影響**: 本番は生成を同時に決まった本数までしか受けないので、確かめの生成が走っている間（約4秒、再起動の直後は
  約40秒）に利用者の生成が重なると、上限を超えた分が混み合いとして断られる。

## CIの実行枠（リポジトリがpublicである間の前提）

**GitHub Actionsの実行時間は、リポジトリがpublicである間は課金も分数の上限も無い。** GitHubの
公式（[Actionsの課金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)）は、
publicリポジトリで標準のGitHubホストランナーを使う実行を無料としている。残る制約は
[Actionsの制限](https://docs.github.com/en/actions/reference/limits)で、Freeプランでは同時に
動くジョブの数と1ジョブの実行時間（6時間）に上限がある。同時実行の上限を超えた分は失敗せず、
空くまで待つ。

この前提の上で、CIは次のように組んである。

- どの出来事でCIが走るかは.claude/skills/run-checks/SKILL.md「検査の置き場（手元・作業ブランチのCI・masterのCI）」が持つ。
  作業ブランチへのpushで走らせないのは、検査はPull Requestの実行で済み、誰も待たないpushの実行で枠を使わないため。
  backendの本番へのデプロイは、masterへの
  pushでCIが通ったときだけ`ci.yml`から呼ばれる（上の「デプロイの反映確認」）。
- `ci.yml`は、同じref（master・Pull Requestごと）の実行を1本ずつ動かし、待ちは一番新しい1件だけにする（`concurrency`）。
  後のコミットは前の変更を全部含み、古いコミットの実行はデプロイにもマージの判断にも使わないため。Pull Requestは
  新しいpushで走っている実行も打ち切り、masterは走っている実行を最後まで走らせる（デプロイが同じ実行の中で走るので、
  途中で切らない）。打ち切った・待ちから外した実行のコミットにはCIの結論が残らないので、結論は最新のコミットで読む
  （.claude/skills/run-checks/SKILL.md「CIの結論を読む」）。数十秒で終わる`docs-consistency.yml`・`claude-gate.yml`には置かない
  （待ちが積もらない）。
- ジョブの分け方・キャッシュは、所要時間と同時実行の枠で決める（理由は各ワークフローのコメント）。
- **どのジョブを走らせるかは、変わった置き場で決める。** 置き場（`backend/`・`frontend/`・`scripts/`）はどれも自分のテストを自分の中に
  持ち、`ci.yml: changes`は変わったファイルの頭からどの置き場が変わったかだけを見て、その置き場の検査（backendならテスト・api-contract・
  像の確かめ、frontendならテスト・e2e・全状態の走査・api-contract・像の確かめ、`scripts/`なら道具のテスト）とデプロイを走らせる。
  それ以外の変更（文書・タスク管理・ほかのワークフロー）では何も走らせない。`ci.yml`と`.github/actions/`を変えたら、その定義で
  全部を走らせて確かめる。置き場をまたいで読むものは数えず、テストを読む側の置き場へ置く（backendのための道具は`backend/scripts/`）。
  走らせるジョブの組は`changes`の段だけが持ち、ジョブの`if`と`ci-ok`が読む。
- **masterのpushの`changes`は、pushの実行が成功した一番近い祖先と比べる。** 直前のコミット
  （`github.event.before`）と比べると、直前の実行が失敗で終わったか待ちのまま取り消された（上の`concurrency`）とき、その変更が
  検査もデプロイもされないまま、次の文書だけの変更の実行がそれを飛ばして成功で終わる。デプロイだけが落ちた実行のあとは、
  確かめ済みのテストも走り直すが、余分に走るだけで抜けはしない。
- **タスク管理は製品のCIと分ける。** タスク管理の置き場（`.github/taskflow-paths`。ゲートの`tools/flow-gate/`と
  担当のワークフロー）の検査とゲートの公開は`claude-gate.yml`が持ち、`ci.yml`はその置き場を読まない。そのため
  `ci.yml: changes`はその置き場だけの変更でどのジョブも走らせず、backend・frontendのデプロイも起動しない。
  置き場の定義は、総量の計測（`scripts/review_checks.py: TASKFLOW_PREFIXES`）が読む。
- **ワークフローは`paths`で飛ばさず、いつも起こす。** コードのリポジトリは、master へ入れる前に必須チェック
  （`ci.yml`の`ci-ok`・`docs-consistency.yml`のジョブ・`claude-gate.yml`の`flow-gate`）が通ることを求める。ワークフローごと飛ばすと必須チェックが Pending のまま残り、
  Pull Request がマージできない（公式の「Troubleshooting required status checks」）。ジョブを飛ばすのは
  `changes`ジョブが決め、ジョブの`if`で飛ばしたものはスキップとして必須チェックを通る。
- **文書の整合は`ci.yml`と分けたワークフローに置く。** 文書の整合の検査（`scripts/review_checks.py docs`）は
  文書だけの変更こそが対象なので、`changes`が文書だけの変更でジョブを飛ばす`ci.yml`に置かず、常に走る`docs-consistency.yml`に置く。
  backendの外のPythonとshの静的検査も、置き場を問わず同じワークフローが常に走らせる。

**privateにしたら、この節の前提が崩れる。** 公式の同じページによれば、Freeプランのprivate
リポジトリは標準ランナーで月2,000分までで、支払い方法が未登録なら使い切った時点で実行が止まる
（登録済みなら超過分が課金される）。privateへ切り替えるときは、切り替えの前に次を見直す:
Pull RequestごとにCIを走らせるか、古い実行を打ち切るか（`concurrency`）、文書・運用の道具
だけの変更でジョブを飛ばす範囲（`ci.yml: changes`）、ジョブの分け方とキャッシュ。検査の門を
CIだけに置いているため、CIの分数が尽きると検査そのものが止まる。

## 秘密の値とトークン

**どのトークンが誰の名義で、どこへ届き、どこで使われているかは、GitHub・Cloudflareの画面にもコードにも
まとまって無く、この表だけが持つ。** 値はここに書かない。トークンを作る前に、この表で今あるものを使えないかを
見る。トークンを作る・消す・権限や届く範囲を変えるときは、同じ変更でこの表を直す。どの名義でどこへ書くかの
決まりは[flow.md](../conventions/flow.md)「担当」の「名義」が持つ。

| 入れた場所 | 名前 | 中身（作った人・Resource owner・届く範囲・権限・期限） | 使う所 |
|---|---|---|---|
| ridecompass/ride-compassのActionsの秘密の値 | `CODE_TOKEN` | hidakagitが作ったfine-grained。Resource ownerはridecompassで、届くのはridecompass/ride-compassだけ。Actions・Contents・Issues・Pull requests・Variables・Workflowsは読み書き（Workflowsは2026-10-09に足した。担当が`.github/workflows/`を自分でpushする）、Commit statusesは読むだけ。期限は未記録 | `claude-task.yml`（checkout・Claudeの連携・ghの既定） |
| 同 | `FLOW_BOT_TOKEN` | hidakagit-botが作ったfine-grained。届くのはridecompass/ride-compass-tasksだけ。Contentsは読み書き（担当の手番の記録をリリースへ置く）。期限2027-09-29 | 担当と流れの道具が置き場へ書く。開発機ではユーザー環境変数の同じ名前 |
| 同 | `CLAUDE_CODE_OAUTH_TOKEN` | Claudeの契約のトークン（GitHubのトークンではない） | `claude-task.yml` |
| 同 | `CLOUDFLARE_API_TOKEN`・`CLOUDFLARE_ACCOUNT_ID` | Cloudflare | ゲートと回答フォームの公開（`claude-gate.yml`） |
| 同 | `MAPILLARY_TOKEN` | hidakagitがMapillaryの開発者の画面で登録したアプリのClient Token（読むだけ。GitHubのトークンではない）。期限は未記録 | `claude-task.yml`（担当の環境変数。Mapillaryの街灯の点の付き方の測定） |
| 同 | `ORACLE_VM_HOST`・`ORACLE_VM_SSH_KEY` | 本番のVM | backendのデプロイ |
| 同 | `RENDER_FRONTEND_DEPLOY_HOOK_URL` | Render | frontendのデプロイ |
| ゲートのWorker（`ridecompass-gate`） | `APP_ID`・`APP_KEY`・`WEBHOOK_SECRET` | GitHub Appの鍵とWebhookの秘密 | ゲート |
| 回答フォームのWorker（`ride-compass-answer`） | `APP_ID`・`APP_KEY`・`FORM_TOKEN` | `FORM_TOKEN`はhidakagitが作ったfine-grained `ridecompass-answer-form-2`。Resource ownerはridecompassで、届くのはridecompass/ride-compass-tasksだけ。期限2027-09-29 | 回答フォームの答えをhidakagitの名義で書く |
| Renderのワークスペースの資格（Container Registry Credentials） | `ghcr-read` | hidakagitが作ったclassic `render-ghcr-read`。`read:packages`だけ（GitHubのコンテナの置き場はclassicのトークンだけを受ける）。期限なし | Renderの`ride-compass-frontend`が、非公開のfrontendのコンテナイメージを取る（サービスの Settings → Image の Credential） |

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
専用の層で、**正本データを持たない**（方針は[caching.md](../../.claude/rules/caching.md)）。
本番はOracle Cloud VMへネイティブに導入する（backendコンテナが`--network=host`のため
追加設定なしで到達できる）。ローカル開発は`docker-compose.yml`のredisサービス。

`/etc/redis/redis.conf`へ`maxmemory 2gb`・`maxmemory-policy volatile-lru`を設定する
（VM全体のメモリをPostgreSQL・backendコンテナと分け合うための配分）。**上限を外すと、
用途を広げたときに同居するVM全体のメモリを圧迫する。** 現行のキーはすべてTTL付きの
ため`volatile-lru`（TTL付きキーの中からLRUで退避）を選ぶ。

本番で14MBのpickleを読んだ中央値は、
ディスク（ページキャッシュに当たる）2.0ms・Redis GET（localhost）18.9ms・ディスク（ページキャッシュに当たらない）26.3msで、
どちらの経路でも復元（unpickle）の263.1msが支配した（本番の実測。`docs/records/tasks/T649.md`「対応方針」）。

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
