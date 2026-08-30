# 横断基盤（backend）

## 責務

DB接続・マイグレーション・Redis・HTTPクライアント・レート制限・ログ・デバッグ機構・
非同期ジョブ管理・アプリ起動（lifespan）・設定・管理API共通の認可境界という、
特定のドメイン機能に属さない横断的な基盤を提供する。

**対象ファイル**

| レイヤー | ファイル | 責務 |
|---|---|---|
| ルート | `main.py` | アプリ起動（lifespan）・ミドルウェア登録 |
| ルート | `config.py` | 設定（`Settings`、環境変数） |
| ルート | `version.py` | プロセス起動時刻（デプロイ確認用） |
| api | `admin_auth.py` | 管理API共通の認可境界 |
| api | `dependencies.py`（横断的な部分のみ、他は各モジュール参照） | DI工場・`enforce_rate_limit`集約 |
| api/routers | `health.py` | `/health`・`/api/debug/stats`・`/api/debug/db-status` |
| api/routers | `debug_admin.py` | `debug_mode`のランタイム切替・直近ログ取得 |
| infrastructure | `database.py` | PostGIS接続（SQLAlchemy） |
| infrastructure | `migrate.py` | 最小マイグレーション機構（番号付きSQL） |
| infrastructure | `redis_client.py` | Redis共有クライアント |
| infrastructure | `http_client.py` | 外部API向け共有HTTPクライアント |
| infrastructure | `rate_limiter.py` | プロセス内メモリのみの固定窓レート制限 |
| infrastructure | `request_log.py` | リクエストIDの付与、1リクエスト=1行のHTTPアクセスサマリログ |
| infrastructure | `debug_log.py` | 外部I/O（外部API・タイル/標高キャッシュ）イベントのログと集計 |
| infrastructure | `debug_control.py` | `debug_mode`のランタイム切替・直近ログの保持 |
| infrastructure | `job_registry.py` | 汎用の非同期ジョブレジストリ（プロセス内メモリのみ） |

## アプリ起動（`main.py`）

```
FastAPI(lifespan=lifespan)
        │
        ├─ (1) httpx.AsyncClientのウォームアップ（10.0秒/15.0秒タイムアウト分を事前構築。
        │       SSLコンテキスト構築が数百ms〜1秒かかるため、デプロイ直後の最初のリクエストが
        │       このコストを負わないようにする）
        ├─ (2) refresh_axis_definitions() を1回呼ぶ（軸スタジオ・評価軸定義参照）。
        │       失敗するとAxisDefinitionSyncErrorがここで捕捉されず起動自体が失敗する
        ├─ (3) APSchedulerでJMAアメダス定期更新ジョブを登録（interval分ごと＋
        │       next_run_time=nowで起動直後にも1回即時実行、コールドスタート対策）
        ▼
  CORSMiddleware → request_log_middleware（リクエストID付与・アクセスログ、CORSより外側）
        ▼
  api_router（api/routers/__init__.py、全routerを集約）
```

- ログレベルは`debug_mode`の値でINFO/DEBUGを切り替える（`main.py`のlogging.basicConfig）。
- `install_ring_buffer_handler()`（`debug_control.py`）をルートロガーへ追加し、
  `debug_admin.py`経由でSSH無しに直近ログを取得できるようにする。
- `httpx`ロガー自体はWARNING以上に抑制する（1リクエストごとのINFOでログが埋まるため。
  外部呼び出しの記録は`debug_log.py: log_external_call`が別途担う）。

## 設定（`config.py: Settings`）

環境変数（`.env`）から読む横断設定。主なもの:

| 設定 | 既定値 | 影響範囲 |
|---|---|---|
| `database_url` | localhost | PostGIS接続文字列（[ルート生成エンジン](routing-engine.md)は常にこの接続を必須とする） |
| `road_graph_use_repository` | `True` | 下記「暗黙の前提」参照 |
| `admin_basic_auth_username`/`password` | 空文字（常に拒否） | 軸スタジオ・`debug_admin.py`の認可 |
| `redis_url` | localhost | Redis接続文字列 |
| `git_commit` | None（ローカル） | `/health`が返すデプロイ確認用コミットSHA |
| 各種`*_rate_limit_per_minute`/`*_max_concurrent` | エンドポイントごとに個別 | per-IPレート制限・同時実行数上限 |

**暗黙の前提（`road_graph_use_repository`、複数サービスが個別に分岐する横断フラグ）**:
このフラグは「Road Graphの永続化（PostGIS）をランタイムのread-throughキャッシュとして
使うか」を制御する。`GraphService`（[ルート生成エンジン](routing-engine.md)が使う）は
**このフラグに関わらず常にrepository必須**（DB接続必須。ルート生成エンジンは
road_graph一本のため、DATABASE_URLへの実接続なしで動く構成は存在しない）。一方
`get_region_service`・`get_accident_service`・`get_dynamic_way_value_service`・
`get_elevation_attribute_service`（いずれも`api/dependencies.py`）は、このフラグを
**個別に見て**Falseならrepository自体を注入せず、空タイル・空dict等のグレースフル
デグレードへ倒す（`else: yield None`/`yield RegionService()`のパターンが複数箇所に
散在する。1つの設定値が複数のDI関数へ同じ判断ロジックとして繰り返し登場している）。

## DB接続プールの分離（`api/dependencies.py`・`database.py`）

**暗黙の前提（見落としやすい重要な分岐）**: DBセッションファクトリは**2系統**存在する。

| ファクトリ | command_timeout | 用途 |
|---|---|---|
| `get_session_factory()` | 20秒 | タイル配信（路面/POI/事故）・軸スタジオCRUD等、通常のリクエスト |
| `get_route_generation_session_factory()` | 180秒 | ルート生成専用（`get_graph_service`・`get_elevation_attribute_service`が使う） |

ルート生成（特にコールド時のRoad Graph再構築）は数十秒〜最大300秒超かかりうる重い処理
のため、タイル配信保護用の短いタイムアウト（20秒）を共有すると途中でキャンセルされる。
接続プールも分離しているため、ルート生成とタイル配信は接続を取り合わない（プール合計は
最大30接続、本番PostgreSQLの`max_connections=100`に余裕）。

## レート制限の集約（`api/dependencies.py: enforce_rate_limit`）

`check_rate_limit`→超過時の記録→`HTTPException(429)`という一連の処理を
`enforce_rate_limit(request, prefix, limit_per_minute)`へ集約している。`weather.py`・
`basemap.py`・`jma_tile.py`・`routes.py`の各routerがこれを共通に呼ぶ。`prefix`は
レート制限キー・rejection集計カテゴリの両方を兼ねる。

## 管理API共通の認可境界（`api/admin_auth.py`）

`require_admin_basic_auth`（HTTP Basic認証、`secrets.compare_digest`でタイミング攻撃を
回避）を[軸スタジオ・評価軸定義](axis-studio.md)の`axis_admin.py`と`debug_admin.py`が
共有する。認証情報未設定（既定の空文字）の環境では常に拒否——うっかり無保護公開しない。
frontend側（`src/proxy.ts`）も同じ資格情報を別のBasic認証チェックとして持つ（オリジンが
異なりブラウザの認証情報が自動伝播しないため、2つの独立したチェックだが同じ値を運用する
ことで実質1つの資格情報として扱う）。

## 運用エンドポイント（`api/routers/health.py`）

| エンドポイント | 認可 | 内容 |
|---|---|---|
| `GET /health` | 不要 | `status`・`commit`（デプロイされたコミットSHA）・`started_at` |
| `GET /api/debug/stats` | 不要（集計値のみ、秘匿情報なし） | `debug_log.py`の集計（呼び出し数・エラー数・ヒット率・所要時間・429拒否数） |
| `GET /api/debug/db-status` | 不要（読み取り専用診断） | pending migrations・主要テーブルの直近import run状況・行数。DB障害時も500にせずWARNINGログ＋`reachable=false`を返す |

`db-status`は「本番DBがコード上の期待に追いついているか」を1リクエストで確認する診断
エンドポイント。`road_graph_use_repository=false`のときは接続を試みずその旨だけ返す。

## `debug_admin.py`（`debug_mode`のランタイム切替）

`POST /api/admin/debug/mode`でdebug_modeをランタイム切替（`.env`は書き換えない、
再起動不要。再起動・再デプロイのたびに環境変数の既定値へ自動的に戻る設計）。
`GET /api/admin/debug/logs`でプロセス内メモリのリングバッファ（既定最大1000件）から
直近ログを取得（`contains`部分一致・`limit`件数で絞り込み）。debug_modeがOFFの間は
DEBUGレベルの行自体が記録されない。

`install_ring_buffer_handler()`（`debug_control.py`、`main.py`起動時に1回）が
`_LogRingBufferHandler`（`deque(maxlen=1000)`）をルートロガーへ追加する。既存の
標準出力ハンドラ（Dockerのjson-fileドライバへ渡る）はそのまま残るため、既存の
常時ログ出力には影響しない。

## Redisクライアント（`redis_client.py`、サーキットブレーカー）

JMA気象データの短命キャッシュ・`road_graph_tile_cache.py`のcache-aside層が使う共有
接続。**接続/ソケットタイムアウトを明示的に0.2秒へ短縮**している（既定タイムアウトの
ままだと疎通不能環境で1回の接続試行に数秒かかることが判明したため——ルート生成の
ホットパスに乗ると「PostGIS往復を減らす」という本来の目的に反する遅延になる）。

**サーキットブレーカー**: `redis_available()`が直近の失敗（`record_redis_failure()`）から
`_CIRCUIT_COOLDOWN_SECONDS=10.0`秒以内なら`False`を返し、呼び出し元はRedis自体への
接続試行そのものをスキップしてPostGISへ即座にフォールバックできる（0.2秒×リクエスト数の
累積コストを避ける）。Redis接続自体の障害はfail-fastさせない設計（`main.py`のlifespanでも
疎通確認しない）。すべての用途がTTL付きキャッシュまたはPostGIS[正本]への即座フォールバック
可能なcache-asideであるため。

## HTTPクライアントの共有（`http_client.py`）

`get_http_client(timeout)`が、timeoutの値ごとに`httpx.AsyncClient`を1つだけ生成して
キャッシュする（`_clients: dict[float, httpx.AsyncClient]`）。`httpx.AsyncClient`の生成が
SSLコンテキスト構築（CA証明書バンドルの読み込み・パース）を伴い、環境によっては
1回あたり約1秒かかる実測があったため、リクエストごとの新規生成をやめプロセス全体で
使い回す（`main.py`のlifespanが起動時に主要なtimeout値[10.0/15.0]を事前ウォームアップする
のもこのため）。

## リクエストIDとアクセスログ（`request_log.py`）

`request_log_middleware`が全リクエストへリクエストID（`X-Request-ID`ヘッダを引き継ぐか、
無ければ`uuid4().hex[:12]`で生成）を割り当て、`contextvars`経由で保持する。
`RequestIdLogFilter`が全ログレコードへ`request_id`属性を注入するため、1リクエスト中に
出た外部API呼び出しログ・ルート生成ステージログ等がすべて同じIDで紐づく。

アクセスログのレベルは`_access_level`が動的に決める:

| 条件 | レベル |
|---|---|
| ステータス5xx | ERROR |
| ステータス429 | DEBUG（`record_rate_limit_rejection`が抑制付きWARNINGで別途記録するため、ここでは重ねない） |
| ステータス4xx（429以外） | WARNING |
| GET かつ`/api/basemap`・`/api/region/road-surface-tiles`配下（高頻度タイル取得） | DEBUG |
| それ以外 | INFO |

未処理例外はスタックトレース付きERRORで記録してから再送出する（`HTTPException`は
FastAPI側で処理済みのためここには来ない）。

## 非同期ジョブレジストリ詳細（`job_registry.py`）

プロセス内メモリのみ（`dict[str, JobRecord]`）。単一プロセスデプロイ前提（軸定義の
push型更新と同じ前提）。`JobStatus = "queued"|"running"|"done"|"failed"`。完了
（done/failed）から`_JOB_TTL_SECONDS=600.0`秒経過したジョブは、次の`create_job()`
呼び出し時に掃除する（専用の定期タスクは新設せず、`rate_limiter.py`と同じ「呼ばれた
ついでに掃除」方式）。ルート生成に特化させず`result: Any`型で汎用化してあるため、
本モジュール自体はルート生成の型を知らない（`routes.py`との循環import回避）。

## ログ集計の詳細（`debug_log.py: log_external_call`）

`log_external_call(category, **fields)`はコンテキストマネージャで、`yield`されたdictへ
呼び出し元が`cache="hit"/"miss"`・`result="ok"/"error"`・`retries=N`等を追記してから抜けると、
完了ログと`/api/debug/stats`の集計へ反映される。

- 例外発生、または`fields["result"]=="error"`は抑制付きWARNINGで**常時**出力する。
  呼び出し元が既に詳細な独自WARNINGを出している場合は`fields["warned"]=True`で二重出力
  だけ抑制できる（エラー集計自体は正しく計上され続ける）。
- 成功はDEBUG（`debug_mode`時のみ実質出力）。
- 集計（`/api/debug/stats`）にはカテゴリ単位で呼び出し数・エラー数・キャッシュhit/miss・
  平均/最大所要時間に加え、`retried_calls`/`retry_attempts_total`（再試行回数）・
  `stale_fallback_used`（`fields["fallback"]`が`"stale_cache"`で始まる場合、古い
  キャッシュで代用した回数）・直近のエラー種別/時刻も
  含む。
