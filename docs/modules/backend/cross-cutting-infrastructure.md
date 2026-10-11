# 横断基盤（backend）

## 責務

DB接続・Redis・HTTPクライアント・レート制限・ログ・デバッグ機構・
非同期ジョブ管理・アプリ起動（lifespan）・設定・管理API共通の認可境界という、
特定のドメイン機能に属さない横断的な基盤を提供する。

**対象ファイル**

| レイヤー | ファイル | 責務 |
|---|---|---|
| ルート | `main.py` | アプリ起動（lifespan）・ミドルウェア登録 |
| ルート | `config.py` | 設定（`Settings`、環境変数） |
| ルート | `version.py` | プロセス起動時刻（デプロイ確認用） |
| domain | `time_zone.py` | 日本標準時（`JST`）の正準定義と時刻の読み方（タイムゾーンの無い時刻はJSTとして読む`as_jst`、予報の系列の時刻＝タイムゾーンの無いJSTへ直す`as_series_time`）。時刻を扱う全モジュールがここを参照する |
| domain | `warning_levels.py` | 警戒度バッジ4段階（`WarningBadgeLevel`）の正準定義。JMA警報・WBGT・河川氾濫予報が判定根拠は別々のまま同じ語彙を返す |
| domain | `strict_model.py` | 全Pydanticモデルの基底（`StrictModel`）。未知のフィールドを黙って捨てず例外にする |
| api | `admin_auth.py` | 管理API共通の認可境界 |
| api | `admin_db_errors.py` | 管理APIのDB障害を、どの口でも503で返すアプリ単位の例外の扱い（下の「DB障害として扱う例外」） |
| api | `cache_policy.py` | 応答の`Cache-Control`（パスとポリシーの対応表・付与ミドルウェア） |
| api | `dependencies.py`（横断的な部分のみ、他は各モジュール参照） | DI工場（公開関数は注入の口だけ） |
| api | `finite_json_body.py` | 要求の本文のNaN・無限大を、アプリ全体の依存として経路の処理より前に422で断る（Starletteの本文の読み方はJSONの外の`NaN`・`Infinity`を通す） |
| api | `rate_limit.py` | per-IPレート制限（`enforce_rate_limit`集約・`client_id`） |
| api/routers | `health.py` | `/health`・`/api/debug/stats` |
| api/routers | `debug_admin.py` | `debug_mode`のランタイム切替・直近ログ取得 |
| infrastructure | `database.py` | PostGIS接続（SQLAlchemy） |
| infrastructure | `redis_client.py` | Redis共有クライアント |
| infrastructure | `redis_json_cache.py` | Redisへ持つcache-asideの共通骨格（JSON・生のバイト列・Hash） |
| infrastructure | `http_client.py` | 外部API向け共有HTTPクライアント |
| infrastructure | `process_resources.py` | プロセスで持ち回る接続と資源（HTTP・Redis・DBのエンジン・土地被覆ラスタ・ディスクのキャッシュ）を、lifespanのシャットダウン段でまとめて閉じる |
| infrastructure | `rate_limiter.py` | プロセス内メモリのみの移動窓レート制限 |
| infrastructure | `request_log.py` | 1リクエスト=1行のHTTPアクセスサマリログ、ログ1行の書式（リクエストIDの差し込みとJSTでの時刻整形）、500応答へのリクエストIDの付与 |
| infrastructure | `response_compression.py` | 応答のgzip圧縮（対象content-typeのみ） |
| infrastructure | `media_types.py` | 自前で作って配るタイルのメディアタイプ（MVT・PNG）。作る側・配る側・gzipの対象の判定が同じ値を読む |
| infrastructure | `data_paths.py` | backendがディスクへ置くものの根（本番ではホストのディレクトリを載せ、コンテナを入れ替えても残る） |
| infrastructure | `debug_log.py` | 外部I/O（外部API・タイル/標高キャッシュ）イベントのログと集計。集計の型（`ExternalCallStats`）はプロセス内のカウンタと`/api/debug/stats`の応答が共有する（ヒット率・平均の計算元の回数・合計時間は応答に載せない） |
| infrastructure | `debug_control.py` | `debug_mode`のランタイム切替・直近ログの保持 |
| infrastructure | `admin_data_backup.py` | 管理データのバックアップが最後に置けてからの時間（`/health`が返す）。下の「取り直せない管理データのバックアップ」 |
| infrastructure | `job_registry.py` | 汎用の非同期ジョブレジストリ（プロセス内メモリのみ） |
| infrastructure | `single_process.py` | 起動時にワーカー数を読み、複数なら起動を止める（プロセス内に持つ状態の前提を落ちる形にする） |
| infrastructure | `tuning_overrides.py` | 較正値の上書き（宣言の既定値から動かしたぶんだけをDBへ持つ）の読み書きと、宣言の範囲での検算。プロセス内の値へは書かない |
| services | `tuning_service.py` | 較正値の上書きの取引境界（構造仕様7）と、プロセス内の値への反映（起動時の読み込みと、書いた直後） |
| api | `tuning_admin.py` | 較正値の一覧・更新（管理画面用、`require_admin_basic_auth`の内側）。並べる項目も、効き方ごとの見出しと並び順も宣言から導く。名前に添える対象（どの路面の見込み・停止要因の種別の値か）は、値を使う側の宣言（`domain/road.py`・`domain/traffic.py`）から引く |
| scripts | `admin_data_dump_args.py` | 取り直せない管理データの表を書き出す`pg_dump`の引数（DB名と表）。表は印（`orm_base.IRREPLACEABLE`）から導く |
| ops | `admin_data_backup.sh` | 本番VMのホストで、上の引数で`pg_dump`し、Object Storageの非公開バケットへ置き、置けた時刻を書く |
| ops | `ridecompass-admin-data-backup.service`・`ridecompass-admin-data-backup.timer` | それを毎日打つsystemdのユニット（VMへの登録は手で1回） |
| scripts | `schema_gap.py` | 実DBのスキーマとORMの宣言（`orm_base.declared_metadata`）の差を出す。宣言どおりの表を同じ接続の一時スキーマへ作ってから巻き戻すまでの間に、`public`とカタログを突き合わせる——制約・既定値・索引の式をPostgreSQLが正規化した形で比べるので、CHECKの式・主キー・一意も比べられる。名前は比べない。取込が作る子パーティション（生データの区画）は、列のNULL許容だけをアダプタの宣言（`batch/ingest.py: partition_required_columns`）と比べ、カタログの値だけを読む（取込が入れ直している最中でも、そのロックを待たずに測れる）。本番DBへは、backendのデプロイがコンテナを入れ替えたあとに毎回当てる（差があればデプロイが失敗で終わる。docs/architecture/tech-stack.md「デプロイの反映確認」）ほか、手で`run_probe.py`から当てる |
| scripts | `lost_constraints.py` | 2つの版の`backend/app`をgitから取り出し、ORMが宣言する表・制約を名前抜きの同じ形へ揃えて、消えたものを出す（DBは使わない）。SQLの文の中の絞り込みは見ない——断片をつないで組み立てるSQLは文字列から構文木を取れないものが残るため |
| scripts | `mutation/` | 変異テストの台本。mutmut 3.8.0（測るときだけ入れる）には`app`の関数の中の変異の生成と、関数ごとに通るテストの記録だけをさせ（`gen.py`）、変異ごとに別のプロセスでそのテストを最後まで回して、落ちたテストを記録する（`runner.py`・`mutkill.py`）。回す変異と基準の並べ方と一覧の口（`plan.py`）・集計（`analyze.py`）・生き残りの振り分け（`classify.py`・`importtime.py`）・テストの見直しの候補と前回との比べ（`review.py`）・Pull Request の差分で変わった関数を拾って回し、生き残りを知らせる（`diff_scope.py`・`pr_plan.py`・`report_pr.py`）。回し方は[run-checks/SKILL.md](../../../.claude/skills/run-checks/SKILL.md)「変異テストでテストの効きを測る」、見直しの1回の進め方は[test-review/SKILL.md](../../../.claude/skills/test-review/SKILL.md) |
| scripts | `_stdio.py` | `scripts/`の実行口が共通で使う、標準出力・標準エラーのUTF-8化 |
| scripts | `run_probe.py` | 調査用のスクリプトを本番DBに対して走らせる（手元のPythonから本番DBを引くか、本番のbackendコンテナの中で走らせる）。手元実行では接続文字列をSQLAlchemy用と素のasyncpg用の両方の形で環境変数へ渡す。プローブの後ろに書いた引数はそのままプローブへ渡す |
| scripts | `_prod_env.py` | 本番へつなぐ道具（`run_probe.py`・`axis_apply.py`等）が共有する、手元の接続情報（`backend/.env.oracle.local`）の読み方。worktreeから打ったときは本体のチェックアウト側のファイルを読む（gitignore対象のファイルはworktreeへ写らない）。接続情報を渡す前に、このチェックアウトがorigin/masterより遅れていれば止まる（[setup.md](../../architecture/setup.md)「開発機の本体のチェックアウトの遅れ」） |
| scripts | `drop_orphan_test_databases.py` | 作業ツリーごとに作られるPostGIS統合テストのDBのうち、作業ツリーが無くなったものを出し、`--drop`で落とす。どの作業ツリーのものかはDB自身のコメントから読む（名前から推測しない） |
| scripts | `serve_e2e_live.py` | e2e-live（`frontend/e2e-live/`）のために、この作業ツリーのbackendを開発DBへ向けて空いたポートで起動し、路面タイルに道が出る起点を開発DBの区間から選んで、ビルドと実行のコマンドを出す（手順の正本は[run-checks/SKILL.md](../../../.claude/skills/run-checks/SKILL.md)「E2E・画面の撮影の走らせ方」） |
| scripts | `serve_capture.py` | 撮影の道具（`frontend/scripts/capture.mjs`の`--backend`）のために、この作業ツリーのbackendを、起動の段（DBの軸定義の読み込み・定期ジョブ）を外して起動する。ルーターとミドルウェアは`main.py: app`のまま。DBを読む経路は失敗するので、撮影の道具はDBを読まない経路（タイルの中継等）だけをここへ向ける |
| scripts | `audit_test_rewrite.py` | 実装から起こし直したテストを外から測る（実装を変えていないか・テストが読む`app.*`・対象の属性の出どころ・seams 数・実装へ1行も入らないテスト・そのテストだけが通す行が0行のテスト・カバレッジ・テストファイルごとの項目と関数と行の数・テストからしか使われない公開の名前の候補。テストは対象を読む母集団を並べて渡す。PostGISのテストはテスト用DBへ繋がるときだけ含める）。起こし直しの手順は[testing-rewrite.md](../../../.claude/rules/testing-rewrite.md) |

## Pydanticモデルの基底（`domain/strict_model.py`）

`extra`の既定は`ignore`で、モデルが知らないフィールドは例外にならず捨てられる。
フィールドを消した・改名したときの取り残しが「値は入らないがテストは通る」という
無言の形で残り、APIリクエストではtypoしたフィールドが黙って無視されて
「指定したのに効かない」として利用者に出る。

このリポジトリのモデルは**すべて自前のコードが明示キーワードで組み立てる**——外部API
（JMA・OSM）のJSONは一度dictで受けて必要な値だけを取り出しており、提供側のペイロードが
そのままモデルへ流れ込む経路は無い。そのため`extra="forbid"`で一律に締められる。

- `backend/app/`配下のモデルは`StrictModel`を継承する（素の`BaseModel`は未知フィールドを
  黙って捨てる）。素の`BaseModel`を継承して`extra`を宣言していないモデルは
  `backend/tests/structure/test_model_strictness.py`が落とす。
- 派生側が`frozen=True`等を指定しても`extra`は引き継がれる（Pydantic v2が親子の
  `model_config`をマージする）。
- **応答の契約（OpenAPIの応答側）では、既定値を持つ項目も必須になる**（`json_schema_serialization_defaults_required`）。
  書き出すときは既定値の項目も必ず載るため、契約をそれに合わせ、画面が型を補正せずに生成型のまま使えるようにする。
  要求と応答の両方に現れるモデル（軸の形等）は、FastAPIが`<名前>-Input`と`<名前>-Output`に分けて書き出す。
- **応答の項目がnullになるかを同じ応答の別の項目が決めるなら、形で表す**——状態ごとのモデルの共用体
  （例: `api/routers/routes.py: RouteGenerateJobDone`）か、一緒に在る項目を1つのモデルへまとめた任意の項目
  （例: `infrastructure/derived_data_freshness.py: ColumnsChange`）。項目ごとの`X | None`で並べると、
  画面は起きない組み合わせまで分岐と既定値で受けることになる。
- 環境変数を読む`config.py: Settings`だけは対象外。プロセスの環境変数には無関係なものが
  常に含まれるため`extra="ignore"`でなければ起動しない。
- 新たに外部ペイロードを直接`model_validate`する経路を作る場合は、そのモデルで
  `extra="ignore"`を明示的に上書きし理由をその場に書く。

## アプリ起動（`main.py`）

```
FastAPI(lifespan=lifespan)
        │
        ├─ (0) require_single_worker()。ワーカーが複数なら起動を止める（下記「1プロセスの境界」）
        ├─ (1) httpx.AsyncClientのウォームアップ（10.0秒/15.0秒タイムアウト分を事前構築。
        │       SSLコンテキスト構築が数百ms〜1秒かかるため、デプロイ直後の最初のリクエストが
        │       このコストを負わないようにする）
        ├─ (2) refresh_axis_definitions() を1回呼ぶ（軸スタジオ・評価軸定義参照）。
        │       失敗するとAxisDefinitionSyncErrorがここで捕捉されず起動自体が失敗する
        ├─ (2') 同じセッションで refresh_tuning_values() を呼び、較正値の上書きを重ねる
        │       （[ルーティングエンジン](routing-engine.md)参照）。行が無い・テーブルが
        │       無い場合は宣言の既定値のまま進み、値が壊れている行だけが起動を止める
        ├─ (2'') スケジューラをここで作り（アプリの寿命の間だけ動くので、モジュールの大域に持たない）、
        │       失敗の受け口（EVENT_JOB_ERROR）を付ける（下記「定期ジョブの失敗」）
        ├─ (3) APSchedulerでJMAアメダス定期更新ジョブを登録（interval分ごと＋
        │       next_run_time=nowで起動直後にも1回即時実行、コールドスタート対策）
        ├─ (4) 同じくAPSchedulerでJMA動的タイルの定期プリウォームジョブを登録
        │       （interval=jma_tile_prewarm_interval_minutes分＋next_run_time=nowで
        │       同様に起動直後にも即時実行、[動的気象レイヤー](weather-dynamic-layers.md)
        │       「定期プリウォーム」節参照）
        ├─ (5) 同じくAPSchedulerで気象庁MSM（風・降水の予報）の.omファイル定期同期ジョブを
        │       登録（interval=msm_sync_interval_minutes分＋next_run_time=now。初回は
        │       ローカルにファイルが無く、完了するまで風グリッド・ルート評価の風が使えない）
        ├─ (6) 同じくAPSchedulerでディスク永続キャッシュの旧世代掃除ジョブを登録
        │       （trigger="date"で起動直後に1回だけ。世代を上げたデプロイの直後がこの
        │       タイミングに当たる、routing-engine.md「道路網全体の配列」参照）
        └─ (7) 同じくAPSchedulerで地域タイルの旧世代掃除ジョブを登録（interval=24時間＋
                next_run_time=now。世代は派生の作り直し・取込でも再起動なしに変わるため定期に回す。
                [静的道路属性](static-road-attributes.md)「共通骨格」の旧世代の掃除）
        ▼
  CORSMiddleware → ContentTypeGZipMiddleware（応答のgzip圧縮）
            → CachePolicyMiddleware（Cache-Control付与、下記「Cache-Controlの一元化」節）
            → request_log_middleware（アクセスログ）
            → CorrelationIdMiddleware（リクエストID付与、最も外側）
        ▼
  api_router（api/routers/__init__.py、全routerを集約）
        │  全経路に掛かる依存（FastAPI(dependencies=...)）: reject_non_finite_json_body（finite_json_body.py）が
        │  本文のNaN・無限大を経路の処理（管理APIの認可を含む）より前に422で断る
        ▼
      yield（アプリ稼働中）
        ▼
  シャットダウン: (1) APSchedulerを停止（`wait=False`）→
                 (2) プロセスで持ち回る接続と資源を閉じる（`process_resources.py: close_process_resources`。
                     httpxクライアント・Redisクライアント・DBの2系統のエンジン・土地被覆ラスタ・ディスクのキャッシュ）
```

- ログレベルは`debug_mode`の値でINFO/DEBUGを切り替える（`main.py`のlogging.basicConfig）。
- `install_ring_buffer_handler()`（`debug_control.py`）をルートロガーへ追加し、
  `debug_admin.py`経由でSSH無しに直近ログを取得できるようにする。
- `httpx`ロガー自体はWARNING以上に抑制する（1リクエストごとのINFOでログが埋まるため。
  外部呼び出しの記録は`debug_log.py: log_external_call`が別途担う）。
- 未処理例外（500）発生時も`unhandled_exception_handler`（`request_log.py`）経由で
  `X-Request-ID`ヘッダを付けて返す（通常レスポンスと同じ追跡性を保つ）。

### 定期ジョブの失敗

ジョブ本体は例外を捕まえない。APSchedulerが捕まえて次の実行を続け、失敗を
`apscheduler.executors.default`へスタックトレース付きのERRORで出す。そのうえで`main.py`の
`_log_job_failure`（`EVENT_JOB_ERROR`の受け口）が`ridecompass.scheduler`へジョブidと例外を
1行のWARNINGで出す——APScheduler側の名前は接頭辞`ridecompass.`から外れ、接頭辞単位で
レベルを絞ると漏れるため（接頭辞は`test_canonical_definitions.py: test_loggers_use_the_documented_prefix`が見る）。
スケジューラも受け口もlifespanの中で作って付けるので、lifespanを通るたびに同じ受け口の付いた新しいスケジューラになる。

## 1プロセスの境界（`single_process.py`）

backendは**1プロセスでしか正しく動かない**。プロセス内に持つ状態が多数あり（ジョブ台帳・
JMAへの実フェッチの秒間上限・軸定義と較正値の反映・レート制限・APSchedulerの定期ジョブ等）、
ワーカーを増やしても何も落ちずに意味だけが変わる——上限はワーカー数倍になり、ジョブは
別ワーカーへ届いたポーリングから見つからず、定期ジョブはワーカー数だけ重なって走る。

そこでlifespanの最初に`require_single_worker(sys.argv, os.environ)`を呼び、複数なら
`RuntimeError`で起動を止める。ワーカーは`multiprocessing`のspawnで起動され親の`sys.argv`を
受け継ぐため、ワーカーの中からuvicornに渡された引数が読める。引数の解釈はuvicorn自身の
CLI定義（`uvicorn.main.main.make_context`）に任せ、`--reload`ではワーカー指定を無視する・
未指定なら`WEB_CONCURRENCY`を読む、という既定の決め方だけをuvicornの`Config`に合わせる。
uvicorn以外からの起動（テスト・スクリプト）は1とみなす。

プロセスをまたいで状態を持つ（Redisへ置く）形にしないのは、状態が1つではないため——
秒間上限だけをRedisへ移しても、他の状態がワーカーごとに分かれたまま残る。

## 設定（`config.py: Settings`）

環境変数（`.env`）から読む横断設定。主なもの:

| 設定 | 既定値 | 影響範囲 |
|---|---|---|
| `database_url` | localhost | PostGIS接続文字列。[ルート生成エンジン](routing-engine.md)・地図のタイル配信・管理APIのどれもこの接続を必須とし、DBなしで動く構成は無い |
| `admin_basic_auth_username`/`password` | 空文字（常に拒否） | 軸スタジオ・`debug_admin.py`の認可 |
| `redis_url` | localhost | Redis接続文字列 |
| `git_commit` | None（ローカル） | `/health`が返すデプロイ確認用コミットSHA |
| 各種`*_rate_limit_per_minute`/`*_max_concurrent` | エンドポイントごとに個別 | per-IPレート制限・同時実行数上限 |
| `jma_tile_prewarm_interval_minutes` | `10` | JMA動的タイル定期プリウォームの実行間隔（[動的気象レイヤー](weather-dynamic-layers.md)「定期プリウォーム」節） |

**既定値はこのクラスだけが持つ。** `.env`の雛形（`backend/.env.example`・リポジトリ直下の`.env.example`）は項目と
上書きの仕方だけを書き、値を写さない——写した値は`.env`へコピーされた時点で固定され、既定値を直しても手元では
古い値が効き続ける。`docker-compose.yml: environment`がCORSの許可元・基礎地図の書き換え先を書くのは写しではない:
composeのfrontendの公開先に従う値で、既定値（手元で`next dev`を起動したときのオリジン）を変えても変わらない。

**暗黙の前提**: DBの口（repository）を受け取るサービスは、口が無い状態を持たない。
`api/dependencies.py`のDI工場は常にセッションを開いて口を渡し、DBに届かないときの
空タイル・空dict等への倒し方は、読み取りで上がる例外（下記「DB障害として扱う例外」）だけが
決める。設定で口を外して「データなし」に見せる経路を足すと、その設定の環境でだけ地図が
黙って空になり、エラーも出ないため取込範囲外やDB障害と見分けがつかない。

## DB接続プールの分離（`api/dependencies.py`・`database.py`）

**暗黙の前提（見落としやすい重要な分岐）**: DBセッションファクトリは**2系統**存在する。

| ファクトリ | command_timeout | 用途 |
|---|---|---|
| `get_session_factory()` | 20秒 | タイル配信（路面/POI/事故）・軸スタジオCRUD等、通常のリクエスト |
| `get_route_generation_session_factory()` | 180秒 | ルート生成（`api/dependencies.py: _open_route_generation_setup`）と、全表走査を伴う管理APIの集計（DBの状態・材料の欠損率等） |

ルート生成は取込範囲の判定（`is_covered`）で接続を取り、確定した経路の形の取り直し
（`get_edges_with_geometry`）を終えるまで、1件の生成の間（本番で数秒〜数十秒）その接続を持ち続ける。
プールを分けているのはこのためで、ルート生成とタイル配信は接続を取り合わない（プール合計は
最大30接続、本番PostgreSQLの`max_connections=100`に余裕）。上限を長くしているのは全表走査の集計の
ためで（タイル配信用の20秒では最後まで走らない）、生成のクエリはこの上限に近づかない——本番の
都心40〜80kmで、形の取り直しを含む評価の段が全体で1.3秒以下（2026-09の計測）。

### DB障害として扱う例外（`database.py: DB_UNAVAILABLE_ERRORS`）

タイル配信・区間インスペクタ・動的way値等、DBの読み取りに失敗したら空（空タイル・空dict・
None）へ倒す箇所は、`except Exception`ではなくこのタプルだけを捕まえる。実装の誤り
（`TypeError`・`AttributeError`等）は捕まえず、500として表へ出す——空へ倒すと応答は正常の
形のまま「データなし」に見え、誰も気づかない。
管理API（`/api/admin/...`）は空へ倒さず、口では捕まえずに、`api/admin_db_errors.py`がアプリ単位の例外の扱いで
同じタプルだけを503にする（口ごとに書くと、書き忘れた口だけが500になる）。管理API以外の経路で捕まえなかった
ものは、送り直して500のまま表へ出す。

中身はSQLAlchemy 2.1＋asyncpgで例外がどう届くかから決まっている（ソースで確認）:

- 接続を張る段階（接続数の上限・認証等）と実行中の失敗は、asyncpgの例外（`asyncpg.PostgresError`・
  `asyncpg.InterfaceError`）が`DBAPIError`へ訳される（方言の`_asyncpg_error_translate`）。プールの待ち切れは
  `sqlalchemy.exc.TimeoutError`。どれも`SQLAlchemyError`。
- `command_timeout`の`TimeoutError`は訳されずに届く（Python 3.11以降は`OSError`の派生）。
  接続の拒否・切断も`OSError`。

## レート制限の集約（`api/rate_limit.py: enforce_rate_limit`）

`check_rate_limit`→超過時の記録→`HTTPException(429)`という一連の処理を
`enforce_rate_limit(request, prefix, limit_per_minute)`へ集約している。routerはこれを直接呼び
（`weather.py`・`routes.py`等）、`region.py`は路面・点のタイル・専用way値配信で同じ上限を共有するため
`_check_tile_rate_limit`という薄いラッパー経由で呼ぶ。DI工場ではなく、ルーターが要求ごとに`prefix`と上限を
変えて普通に呼ぶ関数なので、`dependencies.py`（公開関数は注入の口だけ）と分けて置く。`prefix`はレート制限キー・
rejection集計カテゴリの両方を兼ねる。

### 回数の記録（`infrastructure/rate_limiter.py`）

キー（`prefix:接続元`）ごとに通した時刻の並びを持ち、直近1窓（60秒）に入る時刻だけを数える
移動窓。拒否した回は数えない——数えると、連打をやめない利用者は窓が明けても回復しない。

記録は`cachetools.TTLCache`に置き、期限は最後に通した1回から窓の長さにしてある。中身が窓を
出たときにキーごと期限が切れ、TTLCacheが書き込みのついでに古い順に消すので、来なくなった
接続元（接続元を入れ替えながらの連打・携帯回線）のキーは残らず、見回りの処理も持たない。
件数の上限を超えると最も古い接続元の回数が忘れられる（その接続元が少し多く通るだけ）。
上限は記憶量の歯止めで、根拠はコード側のコメント。

- **ロックを持たない**: TTLCacheはスレッド安全でない。呼び出し元がすべてイベントループ上の
  asyncハンドラであることが前提で、同期の`def`ハンドラから呼ぶとスレッドプールから並行に書かれる。
- **`limits`（`MovingWindowRateLimiter`＋`MemoryStorage`）を使わない理由**: `MemoryStorage`は
  古い時刻を切り詰めるが空になったキーを消さず、問い合わせのたびに全キーを見回る（5.8.0のソース）。
  接続元が入れ替わり続けるとキーが再起動まで溜まり、見回りの所要がキーの数に比例して伸びる。

## 管理API共通の認可境界（`api/admin_auth.py`）

`require_admin_basic_auth`（HTTP Basic認証、`secrets.compare_digest`でタイミング攻撃を
回避）を管理API（`/api/admin/...`）の全ての口が共有する。口がすべて管理用のルーター
（[軸スタジオ・評価軸定義](axis-studio.md)の`axis_admin.py`・較正値・DBの状態等）はルーターの`dependencies`で
1か所に宣言し、口を足しても付け忘れが起きない形にする。公開の口と同居するルーター（材料カタログ等）だけが
管理の口ごとに付ける。
認証情報未設定（既定の空文字）の環境では常に拒否——うっかり無保護公開しない。
frontend側（`src/proxy.ts`）も同じ資格情報を別のBasic認証チェックとして持つ（オリジンが
異なりブラウザの認証情報が自動伝播しないため、2つの独立したチェックだが同じ値を運用する
ことで実質1つの資格情報として扱う）。

## 運用エンドポイント（`api/routers/health.py`）

| エンドポイント | 認可 | 内容 |
|---|---|---|
| `GET /health` | 不要 | `status`・`commit`（デプロイされたコミットSHA）・`started_at`・`admin_data_backup_age_hours`（管理データのバックアップが最後に置けてからの時間。記録が無いか印のファイルが読めなければnull（読めない理由はWARNINGのログ）。下の「取り直せない管理データのバックアップ」） |
| `GET /api/debug/stats` | 不要（集計値のみ、秘匿情報なし） | `debug_log.py`の集計（呼び出し数・エラー数・ヒット率・所要時間・429拒否数）と、予報（MSM）の同期の鮮度。集計はプロセス内のカウンタで、デプロイ・再起動で0へ戻る（起点は`started_at`） |

どちらも集計値だけで機微情報を含まないため無認証。本番DBがコードの期待に追いついているか
（取込runの成否・テーブルの実数・統計とVACUUM）は、管理APIの`GET /api/admin/db-status`
（[静的道路属性・タイル配信](static-road-attributes.md)「本番DBの状態」節）が返す。

## `debug_admin.py`（`debug_mode`のランタイム切替）

`POST /api/admin/debug/mode`でdebug_modeをランタイム切替（`.env`は書き換えない、
再起動不要。再起動・再デプロイのたびに環境変数の既定値へ自動的に戻る設計）。
`GET /api/admin/debug/logs`でプロセス内メモリのリングバッファ（既定最大1000件）から
直近ログを取得（`min_level`で「このレベル以上」に絞り込み・`contains`部分一致・`limit`
件数、いずれも併用可でAND条件）。debug_modeがOFFの間はDEBUGレベルの行自体が記録
されない（WARNING以上は常時記録される）。フロントの「開発者」タブ
（`BackendLogsPanel.tsx`、[軸スタジオ・評価軸定義](axis-studio.md)の
管理APIの転送の口と同じBasic認証セッション再利用）がこのエンドポイントを叩く。

`install_ring_buffer_handler()`（`debug_control.py`、`main.py`起動時に1回）が
`_LogRingBufferHandler`（`deque(maxlen=1000)`）をルートロガーへ追加する。既存の
標準出力ハンドラ（Dockerのjson-fileドライバへ渡る）はそのまま残るため、既存の
常時ログ出力には影響しない。`_LogRingBufferHandler`は各行を`(levelno, 整形済み文字列)`
のタプルで保持し、`min_level`フィルタは整形済み文字列を`[LEVELNAME]`のような
部分文字列でパースせずこの数値で判定する。

## Redisのcache-aside（`redis_json_cache.py`）

どの層に持つか・TTLをどう決めるか・無効化の手段といった方針は[.claude/rules/caching.md](../../../.claude/rules/caching.md)と[.claude/rules/caching-retention.md](../../../.claude/rules/caching-retention.md)が
正本で、ここは実装の説明に絞る。

「Redisが使えるか確認→クライアント取得→`log_external_call`で計測→失敗は握り潰して
未キャッシュ扱い→成否をサーキットブレーカーへ記録」という定型文を1本にまとめたもの。値の形で入口が分かれる——
JSONは`get_json`/`set_json`、バイナリは`get_bytes`/`set_bytes`、観測所ごとのような複数の項目はHashの`get_hash`と、
複数のキーのHashをTTLとともに1往復（pipeline）で書く`set_hashes`。接続は値を生のバイト列で返し、JSONはここでデコードする。
`get_bytes`・`get_hash`は呼び出し元の解釈関数へ生のバイト列を渡し、解釈できない値は未キャッシュ（miss）として扱う。呼び出し元はキー設計・TTL・値の意味づけだけを持つ。

読みの口は「値・保存なし（None）・取れない（`UNAVAILABLE`。冷却中・接続を作れない・コマンドの失敗）」の3通りを返す。
保存なしなら上流から取り直して書けばよいが、取れない間に取り直すと上流へ同じ問い合わせを繰り返すので、
取り直しの重い呼び出し元（アメダスの1時間雨量の履歴）はこれで分ける。分けない呼び出し元は両方を未キャッシュとして扱う。
`simple_api_client.py: cached_fetch`がプロセス内`TTLCache`側で担っている役割の、Redis版。

**fail-openが前提**: 扱うのはいずれも正本を持たないキャッシュのため、Redis障害・接続不能・
壊れたエントリはすべて「未キャッシュ」（`get_json`はNone）へ倒し、呼び出し元が通常の取得
経路へ進めるようにする。キャッシュの不調でアプリの機能を止めない。

新しくRedisへ持つキャッシュはこれを使う（例: 気象庁タイル本体の`jma_tile_redis_cache`・在否インデックスの
`jma_tile_index`・アメダスの`jma_amedas_store`）。タイル本体は値がバイナリ（PNG/PBF）なので`get_bytes`/`set_bytes`に乗せている。
骨格に無い操作が要るときは骨格へ口を足す（骨格を呼び出し元へ写すと`test_redis_skeleton.py`が落とす）。

## Redisクライアント（`redis_client.py`、サーキットブレーカー）

JMA気象データの短命キャッシュが使う共有接続。値を生のバイト列で読み書きする接続を1本だけ持つ。
接続を作れない（`redis_url`の誤り等）ときはサーキットブレーカーを開け、抑制付きWARNING（`cache:redis-client`）を出す。**接続/ソケットタイムアウトを明示的に0.2秒へ短縮**している（既定タイムアウトの
ままだと疎通不能環境で1回の接続試行に数秒かかりうるため。ルート生成の
ホットパスに乗ると「PostGIS往復を減らす」という本来の目的に反する遅延になる）。

**サーキットブレーカー**: `redis_available()`が直近の失敗（`record_redis_failure()`）から
`CIRCUIT_COOLDOWN_SECONDS=10.0`秒以内なら`False`を返し、呼び出し元はRedis自体への
接続試行そのものをスキップしてPostGISへ即座にフォールバックできる（0.2秒×リクエスト数の
累積コストを避ける）。Redis接続自体の障害はfail-fastさせない設計（`main.py`のlifespanでも
疎通確認しない）。すべての用途がTTL付きキャッシュまたはPostGIS[正本]への即座フォールバック
可能なcache-asideであるため。

## HTTPクライアントの共有（`http_client.py`）

`get_http_client(timeout)`が、timeoutの値ごとに`httpx.AsyncClient`を1つだけ生成して
キャッシュする。`httpx.AsyncClient`の生成は
SSLコンテキスト構築（CA証明書バンドルの読み込み・パース）を伴い環境によっては高コストに
なりうるため、リクエストごとの新規生成をやめプロセス全体で使い回す（`main.py`の
lifespanが起動時に主要なtimeout値[10.0/15.0]を事前ウォームアップするのもこのため）。

## 応答のgzip圧縮（`response_compression.py`）

`ContentTypeGZipMiddleware`はStarletteの`GZipMiddleware`を、応答の`content-type`が
`COMPRESSIBLE_CONTENT_TYPES`（JSON・MVT・protobuf・JavaScript）または`text/*`のときだけ
圧縮するよう絞ったもの。basemap/JMA/国土地理院のラスタタイル（PNG等）は圧縮済み形式のため
素通しする。`Accept-Encoding: gzip`を持つリクエストで、本文が`DEFAULT_MINIMUM_SIZE`
（1000バイト）以上の応答が対象。`compresslevel`は3（圧縮はイベントループ上で同期的に
走るため、縮小率がほぼ変わらない高レベルは使わない）。`Vary: Accept-Encoding`は
Starlette側が付与する。

## 応答のCache-Control（`api/cache_policy.py`）

`CachePolicyMiddleware`が全応答へ`Cache-Control`を付ける。パスとポリシーの対応表
（`ROUTE_POLICIES`）がこのファイルにあり、ルーター側はヘッダを書かない——方針が
ルーター全体へ散らばると「どのAPIがどれだけキャッシュされるか」を一覧できなくなるため。

| 規則 | 内容 |
|---|---|
| 引き方 | パスの前方一致。複数該当時は最長のパターンを採るため、表への追記順に依存しない |
| 適用範囲 | 2xxのみ。エラー応答には付けない（一時的な失敗をキャッシュさせると障害が実際の復旧より長く尾を引く） |
| ハンドラ優先 | ハンドラが自分で`Cache-Control`を設定した応答には触らない |
| `immutable` | 「URLが同じなら内容も同じ」と保証できる場合のみ。ブラウザはリロード時の条件付きリクエストすら省くため、内容が更新されうるURLに付けると更新が届かなくなる |

ポリシーは秒数の直書きではなく意味を持つ名前（`PERMANENT`・`IMMUTABLE_TILE`・`BATCH_TILE`・
`BASEMAP`・`SHORT`・`VOLATILE`・`LIVE`・`NO_STORE`）で定義し、時間の調整は
その定義1箇所で行う。同じ秒数でも意味が違うものは別の定数として持つ（片方だけを後から
動かせるようにするため）。

`/api/jma-tile/`だけは1つのパスで性質の異なるもの（内容が確定して以後変化しないタイル
本体・同じURLのまま更新される時刻一覧・恒久404・配信前の地物の404）を返すため、表では`HANDLER_MANAGED`とし、
どのポリシーを使うかを`jma_tile.py`が選ぶ。選択肢自体（`JMA_TARGET_TIMES`・
`JMA_TILE_NOT_FOUND`・`JMA_NOT_YET_DELIVERED`）は`cache_policy.py`が持ち、キャッシュ時間の定義がこのファイルの外へ
漏れないようにしてある。

`tests/test_cache_policy.py`が全`APIRoute`と表を突き合わせ、表に無いルート（ポリシーの
決め忘れ）とどの実ルートにも一致しないエントリ（リファクタで残った死んだエントリ）の
両方を検出する。

**暗黙の前提**: `POST /api/admin/basemap/refresh`（管理画面のタイルキャッシュ消去、
Basic認証必須）はサーバー側のファイルキャッシュしか消せず、利用者のブラウザが保持する分へは
手が届かない。基礎地図の`max-age`（`BASEMAP`）は、消した効果が各利用者の画面へ現れるまでの
最大の遅れでもある。

## リクエストIDとアクセスログ（`request_log.py`）

リクエストIDは`asgi_correlation_id`の`CorrelationIdMiddleware`（`main.py`で最も外側に登録、
既定の設定のまま）が割り当てる。クライアントが送った`X-Request-ID`はUUIDの形（32桁の16進、
ハイフンの有無は問わない）のときだけ引き継ぎ、無い・形が違うときは`uuid4().hex`で作り直す
（作り直したときはライブラリの`asgi_correlation_id`ロガーがWARNINGを出す）。長さも文字種も
確かめずにログと応答ヘッダへ流すと、任意の文字列を行へ差し込める。IDは`contextvars`で持たれ、
応答の`X-Request-ID`にも付く。

`format_log_lines`がハンドラへ付ける`CorrelationIdFilter`が全ログレコードへ`correlation_id`
属性を注入するため、1リクエスト中に出た外部API呼び出しログ・ルート生成ステージログ等が
すべて同じIDで紐づく（リクエストの外で出た行は`-`）。

500応答は`ServerErrorMiddleware`（ミドルウェアの最も外）が作るため、ミドルウェアはそこへ
ヘッダを付けられない。`unhandled_exception_handler`がIDを読んでヘッダ付きの応答を組み立てる。
ミドルウェアはcontextvarを巻き戻さないので、そこでもIDが読める。

`request_log_middleware`は1リクエスト=1行のアクセスログを出す。

アクセスログのレベルは`access_level`が動的に決める:

| 条件 | レベル |
|---|---|
| ステータス5xx | ERROR |
| ステータス429 | DEBUG（`record_rate_limit_rejection`が抑制付きWARNINGで別途記録するため、ここでは重ねない） |
| タイルの経路（`HIGH_FREQUENCY_PATH_PREFIXES`。どれもGETだけ）の成功と404（疎な格子・整備区域の外・配信前のタイルでは正常系） | DEBUG |
| ステータス4xx（429以外。タイルの経路の404を除く） | WARNING |
| それ以外 | INFO |

未処理例外はスタックトレース付きERRORで記録してから再送出する（`HTTPException`は
FastAPI側で処理済みのためここには来ない）。

### ログ1行の書式と時刻（`LOG_FORMAT`・`JstLogFormatter`）

書式はこのモジュールが1つだけ持ち、標準出力（`main.py`のルートハンドラ）と管理画面の
リングバッファ（`debug_control.py`）の双方が同じものを使う。同じ行をそれぞれで組み立てると、
片方だけ直したとき`docker logs`と管理画面で表記が食い違う。

時刻は**JSTで、オフセット（`+0900`）を付けて**書く。コンテナはTZを設定していないため
既定の整形はUTCの壁時計をオフセット無しで書き、ブラウザ側のデバッグログ（利用者の
ローカル時刻）と9時間ずれる——**ずれていること自体より、行が自分の時間帯を名乗らないため
読み手が気づけないことが問題**（実際に9時間離れた窓を見て「該当ログなし」と読みかけた）。
時間帯は`domain/time_zone.py: JST`をそのまま使い、ログ用に別の定義を持たない。

コンテナの`TZ`ではなく整形する側を変える。`TZ`を動かすと素の`datetime.now()`の意味まで
変わり、スケジューラ・DBへ書く時刻へ波及する。

## 取り直せない管理データのバックアップ（`ops/admin_data_backup.sh`）

管理画面で人が積み上げた行（軸の定義・較正値の上書き等）は、外部から取り直せず派生からも作り直せない。
DBを失ったときに戻せるよう、本番VMのsystemdのtimerが毎日、その表だけを`pg_dump`（custom形式）で書き出し、
Oracle Cloud Object Storageの非公開バケットへ置く。戻しは`pg_restore`（登録・戻しの手順は
[production-data/SKILL.md](../../../.claude/skills/production-data/SKILL.md)「管理データのバックアップ」「本番DBを失ったとき」）。

- **対象は表の印から導く**。ORMの表に`__table_args__ = {"info": IRREPLACEABLE}`を付けると、次の書き出しから
  入る。表の名前とDB名は、デプロイ済みのイメージで`scripts/admin_data_dump_args.py`を打って取る（シェルに
  表の名前を書かない）。`pg_dump`は`--strict-names`で打つので、印の付いた表が本番DBに無ければ書き出しごと失敗する。
- **`pg_dump`はホストのもの**を使う。サーバーと同じPGDGのパッケージで入るので版が揃う——`pg_dump`は自分より
  新しいメジャー版のサーバーからは書き出さず、イメージ（python:slim）のDebianの配布物はサーバーより古い。
- **置くのはVMの鍵を使わない形**（インスタンス・プリンシパル。OCI CLIは公式のコンテナイメージで打つ）。VMに
  許すのはそのバケットへの新しいオブジェクトの作成（`OBJECT_CREATE`）だけで、読み出し・上書き・削除はできない
  ——VMが乗っ取られても、置いたバックアップは消せない。オブジェクト名は書き出した時刻（UTC）なので、毎日増える
  だけで上書きしない。消すのはバケットのライフサイクルの規則で、30日より古いものだけ（VMの権限の外）。止まった日が
  30日続くと残りが無くなるので、止まりは次のとおり外から気づく。
- **止まりは`/health`で外へ出す**。置けたらその時刻を、ホストの`/home/ubuntu/ridecompass-cache-data`（コンテナの`data/`）の
  `admin_data_backup_at`へ書き、`infrastructure/admin_data_backup.py`が経過時間を出す。DBに表を足さないのは、本番のスキーマを
  人が埋める手間（docs/architecture/tech-stack.md「デプロイの反映確認」）を、1行の時刻のために増やさないため。
- **書き出しの時点では中身を検算しない**。アプリが起動できない中身（値の不変条件に通らない軸等）も書き出すが、
  前の日のものは残る。戻した行は、backendの起動時の読み込み（`services/axis_registry_service.py:
  refresh_axis_definitions`・`infrastructure/tuning_overrides.py: load_tuning_values`）が管理APIの本文と同じ
  検査に通し、通らなければ起動しない。
- **戻しはスキーマごと入れ替える**（`pg_restore --clean --if-exists --single-transaction`）。表の定義は
  書き出した日の本番のもので、ほかの表からの外部キーは無いので落とせる。1つのトランザクションなので、
  途中で落ちれば何も変わらない。
- 稼働中のbackendは戻した行を読み直さない（読み込みは起動時と管理APIの書き込み直後だけ）。戻したら再起動する。

## 非同期ジョブレジストリ詳細（`job_registry.py`）

プロセス内メモリのみ（`dict[str, JobRecord]`）。単一プロセスデプロイ前提（軸定義の
push型更新と同じ前提）。`JobRecord`は状態ごとの型の共用体で、待ち（`JobPending`。"queued"|"running"）・
完了（`JobDone`。結果）・失敗（`JobFailed`。理由）のうち終わった2つだけが終わった時刻を持つ。完了
（done/failed）から`JOB_TTL_SECONDS`秒経過したジョブは、次の`create_job()`
呼び出し時に掃除する（専用の定期タスクは新設せず、`rate_limiter.py`と同じ「呼ばれた
ついでに掃除」方式）。**この保持時間はフロントのポーリングの打ち切りと同じ値でなければ
ならない**（短いと、まだ待っているフロントが掃除済みのjob_idを引く）。そのためフロントは
独立に値を持たず、生成物`route-generate-config.json`の`job_result_ttl_seconds`から受け取る。ルート生成に特化させず`result: Any`型で汎用化してあるため、
本モジュール自体はルート生成の型を知らない（`routes.py`との循環import回避）。

**ジョブキュー（arq等）は使わない。** arqはジョブの列と結果をRedisに置き、ジョブは`arq`コマンドで起動する
別のワーカープロセスで走る（[arqの文書](https://arq-docs.helpmanual.io/)）。これは次の2点と合わない:

- ジョブ本体（ルート生成）が読む状態は、webプロセスの中にある（道路網全体の配列・軸定義と較正値。
  管理APIの書き込みで読み直す）。別プロセスのワーカーはそれを共有できず、同じものを別に持って別に
  読み直すことになる——上の「1プロセスの境界」が止めている形そのもの。
- Redisは失っても困らないキャッシュだけを置くfail-openの層で、ルート生成はRedisが落ちていても
  雨の材料を欠損にして続く（[ルート生成エンジン](routing-engine.md)「キャッシュ」）。ジョブの列をRedisへ置くと、
  Redisの障害が生成の失敗になる。

代わりに失うもの: ジョブはプロセスの再起動（デプロイ）で消える。

## ログ集計の詳細（`debug_log.py: log_external_call`）

`log_external_call(category, **fields)`はコンテキストマネージャで、`yield`されたdictへ
呼び出し元が`cache="hit"/"miss"`・`result="ok"/"error"`等を追記してから抜けると、
完了ログと`/api/debug/stats`の集計へ反映される。

- 例外発生、または`fields["result"]=="error"`は抑制付きWARNINGで**常時**出力する。
  例外を捕まえて既定値へ倒す呼び出し元は`mark_failed(fields, exc)`で失敗を記録する
  （結果・例外の詳細・種別のラベルをまとめて書く。警告は抜けるときにここが出す）。
- 成功はDEBUG（`debug_mode`時のみ実質出力）。
- 集計（`/api/debug/stats`）はカテゴリ単位で呼び出し数・エラー数・キャッシュのヒット率・
  平均/最大所要時間・エラー種別ごとの件数・直近のエラー種別/時刻を持つ。
