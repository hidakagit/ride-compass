# 技術選定・実行環境の制約

**コードからは導けない制約だけを書く。** 「このバージョンへ上げられない理由」「本番の設定を
既定から変えた理由」「デプロイの前後関係」は、実装には「そうなっている」事実しか残らず、
この文書だけが持つ。依存ライブラリのバージョン・デプロイ・実行環境に触る変更は、
着手前にここを読む。

## 採用しているもの

| 領域 | 採用 | 備考 |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript + MapLibre GL JS + React | バージョンの正本は`frontend/package.json` |
| Frontendスタイリング | Tailwind CSS（新規UI）+ CSS Modules（既存、機能改修時に段階移行）+ Radix UI + `frontend/src/components/ui/` | 使い分け基準・Design Token・意図的に作らないものは[frontend-design-system.md](../modules/frontend/frontend-design-system.md) |
| Backend | Python + FastAPI | バージョンの正本は`backend/requirements.txt` |
| DB | PostgreSQL + PostGIS | 生データ層・派生層・MVT生成（`ST_AsMVT`）の唯一の系統。**取込範囲外は「データ未整備」として扱い、外部APIへのフォールバックを持たない**。ルート生成には`DATABASE_URL`への実接続が必須 |
| ルーティング | 自前のRoad Graph単一構成 | 外部ルーティングAPIへの依存は無い。[route-generation.md](route-generation.md) |
| 地図タイル | OpenFreeMap（APIキー不要）をbackendがプロキシ＋ファイルキャッシュ | 下記「地図タイルプロバイダ」 |
| 天候（予報） | 気象庁MSM（Open-MeteoがAWS Open Dataで公開する前処理済み`.om`をローカル同期） | 外部の気象予報APIを実行時に叩かないため、レート制限・クォータの制約を受けない |
| 天候（実測）・防災 | 気象庁の公開API（アメダス・警報・ナウキャスト・キキクル・洪水予報）・環境省WBGT | 予報と統合しない。数値予報モデルの出力は公式発表の代わりにならない |
| 標高 | 国土地理院DEMタイル（APIキー不要、日本国内限定） | 取込バッチだけが叩き、**実行時に取りに行く経路は無い** |
| 土地被覆 | Esri × Impact Observatory の10m LULC（GeoTIFF） | リポジトリに持たず、デプロイがVMへ取得して読み取り専用でマウントする |

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

## Windows: `uvicorn --reload`の多重プロセス

Windowsでは`uvicorn --reload`がリローダー親プロセスとワーカー子プロセス
（`multiprocessing.spawn`）に分かれる。親だけを`taskkill`すると子が孤児化して同じポートに
残り、**古い設定のまま応答し続ける**。`.env`を編集してもAPIの挙動が変わらない場合は、
`netstat -ano | findstr :8000`でそのポートを握っている全PIDを確認し、すべて終了してから
起動し直す。

- `.env`の変更は`--reload`のファイル監視対象外のため、変更後は完全な再起動が要る。
- 複数ファイルを短時間に連続編集すると`watchfiles`の再読み込みが1回分しか発火せず、
  古いコードのまま動き続けることがある。挙動が古いままに見えたら再起動する。

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
出す。** `ci.yml`の最後のジョブ（`deploy-backend`）が、masterへのpushで他の全ジョブが通った
ときだけ`deploy-backend.yml`を呼ぶ——どれかが赤ならデプロイは起動しない。呼ばれた側は、本番で
動いているコミット（コンテナの`GIT_COMMIT`）からCIを通ったコミットまでの差分を
`scripts/deploy_backend_gate.py`で見て、出すかを決める。

- **差分の起点は直前のpushではなく、本番で動いているコミット。** CIが赤で出せなかった変更は、
  次にCIを通ったコミットの差分にそのまま含まれて出る（直前のpushとの差分では、テストだけを
  直したコミットがコードの変更を運ばず、その変更が次の変更まで出なくなる）。
- **出すのはCIを通ったそのコミットで、masterの先端ではない**（先端はCIを通っていないことがある）。
  後から終わった古いCIの実行は、本番のコミットより古ければ出さない。判定とデプロイは1つの
  ジョブで1本ずつ走る。
- **CIを待つぶん、反映はpushからCIの所要だけ遅れる。** 急ぎの修正でも待つ。待たずに出す手段は
  `deploy-backend.yml`の手動起動（`workflow_dispatch`）で、選んだrefの先端を判定なしで出す。

振り分けの一覧（`deploy_backend_gate.py`の`DEPLOY_PATHS`。GitHubの`paths`と同じ規則で読む）は
`backend/**`から、イメージに入らないもの（テスト・lint設定等）と、イメージには入るが本番
プロセスが読まないもの（`export_openapi.py`とそれだけが読む表示値の宣言）を外している。
表示値の変更は生成物（`frontend/src/types/generated/`）を経由してfrontendのデプロイで
画面へ届くため、backendのコンテナを入れ替える理由にならない。**外したモジュールを本番側が
importすると、その変更だけが本番へ届かなくなる**（エラーにならず古い値で動き続ける）。
`backend/tests/structure/test_deploy_exclusions.py`がその一覧とDockerfileから母集団を
導いてこれを検査する。

**frontend（Render）のデプロイがCIを待つかは、Renderのダッシュボードの設定で決まり、
リポジトリには無い。** Renderの自動デプロイの設定のうち「On Commit」はpushで即デプロイし、
「After CI Checks Pass」はそのコミットのGitHubのチェックが全て成功（skipped・neutralを含む）
したときだけデプロイする（チェックが1件も無いコミットは出さない。Render公式の
[Deploys](https://render.com/docs/deploys)）。

**タイルプロパティを削除する変更はデプロイ順序に制約がある。** backendとfrontendは別
サービスとして独立にデプロイされ、反映タイミングは同期しない。プロパティの**追加**は
常に後方互換（旧フロントは知らないプロパティを無視する）だが、**削除**を含む世代を
backendが先に配信すると、そのプロパティの有無を見ている旧フロントの凡例フィルタが
全地物に一致し、対象レイヤーが一時的に「不明・他」表示になる。frontendを先に（または
同時に）デプロイする。

## CIの実行枠（リポジトリがpublicである間の前提）

**GitHub Actionsの実行時間は、リポジトリがpublicである間は課金も分数の上限も無い。** GitHubの
公式（[Actionsの課金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)）は、
publicリポジトリで標準のGitHubホストランナーを使う実行を無料としている。残る制約は
[Actionsの制限](https://docs.github.com/en/actions/reference/limits)で、Freeプランでは同時に
動くジョブの数と1ジョブの実行時間（6時間）に上限がある。同時実行の上限を超えた分は失敗せず、
空くまで待つ。

この前提の上で、CIは次のように組んである。

- `ci.yml`・`docs-consistency.yml`はmasterに加えて並行実行の作業ブランチ（`orch/**`）への
  pushでも走り、重い検査を開発機から外す（手順はdocs/conventions/orchestration.md「完了とpush」）。
  `.githooks/pre-push`は検査をしない（docs/conventions/testing.md「検査の置き場」）。backendの本番へのデプロイは、masterへの
  pushでCIが通ったときだけ`ci.yml`から呼ばれる（上の「デプロイの反映確認」）。
- 同じブランチへの新しいpushで古い実行を打ち切らない。監査は報告のコミットごとのCIの結論を
  読むため、打ち切るとそのコミットの結論が残らない。
- ジョブの分け方・キャッシュ・`paths-ignore`は、所要時間と同時実行の枠で決める（理由は各
  ワークフローのコメント）。

**privateにしたら、この節の前提が崩れる。** 公式の同じページによれば、Freeプランのprivate
リポジトリは標準ランナーで月2,000分までで、支払い方法が未登録なら使い切った時点で実行が止まる
（登録済みなら超過分が課金される）。privateへ切り替えるときは、切り替えの前に次を見直す:
作業ブランチ（`orch/**`）でCIを走らせるか、古い実行を打ち切るか（`concurrency`）、docs・`*.md`
だけの変更で`ci.yml`を飛ばす範囲（`paths-ignore`）、ジョブの分け方とキャッシュ。検査の門を
CIだけに置いている（pre-pushは検査をしない）ため、CIの分数が尽きると検査そのものが止まる。

## DBの版（本番が正本）

**本番DBの版が正本で、CIと`docker-compose.yml`はそれに従う。本番の版を上げたら、同じ変更で
CIと`docker-compose.yml`も上げる。** CIが本番と違う版で合否を決めると、関数・プランナーの
挙動の差がCIで通って本番で違う形になる。

| | PostgreSQL | PostGIS | 入れ方 |
|---|---|---|---|
| 本番 | 18 | 3.6 | Oracle Cloud VM（Ubuntu 24.04・aarch64）へ、PostgreSQL公式のaptリポジトリ（PGDG）のパッケージ |
| CI（`ci.yml`のbackendジョブ） | 18 | 3.6 | `ubuntu-24.04-arm`ランナーへ、本番と同じ配布元・同じパッケージ名で入れる |
| ローカル（`docker-compose.yml`） | 18 | 3.6 | `postgis/postgis:18-3.6`イメージ（Debian） |

- **揃えるのはメジャー版まで。** パッチ・マイナーは同じ配布元の最新に追従する（CIは実行の
  たびにその時点の最新、本番はVMでaptを更新した時点の版）。本番の実際の版は
  `backend/scripts/run_probe.py --in-container`で`SELECT version()`・`postgis_full_version()`を
  引いて確かめる。CIの版は実行ごとの注釈（`DB`）に出る。
- **DB側のGEOS・PROJ（PostGISの空間演算・座標変換を担う）も、本番・CIともPGDGの版**
  （`libgeos-c1t64`・`libproj25`・`proj-data`）。Ubuntu本体のアーカイブにも同じパッケージ名の
  古い版があり、PGDGの`postgresql-18-postgis-3`はどちらでも入る。**本番でaptを更新すると
  GEOS・PROJも進む**——CIは実行のたびにPGDGの最新を入れるので、本番のaptを長く止めると
  CIだけが先へ進む。本番の実際の版はCIの注釈`DB`と同じ関数（`postgis_full_version()`）で読める。
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
（`postgis/postgis`）/ redis を定義する。postgresのみ永続化ボリュームを持つ。

本番はこの構成をそのまま使わない——backendはOracle Cloud VM上のDockerコンテナ、
frontendはRender、PostgreSQLとRedisはVMへネイティブに置く。
