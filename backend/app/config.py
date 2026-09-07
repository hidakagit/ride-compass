import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 相対パス".env"はプロセスのカレントディレクトリ基準になるため、backend/以外から
# 起動した場合（例: uvicornに--app-dir backendだけを渡しリポジトリルートから起動する等、
# cwdを変えない起動方法）に読み込まれない。config.py自身の位置から解決することで
# 起動時のcwdに依存しないようにする。
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    cors_allowed_origins: str = "http://localhost:3000"
    # Road Graph/Road Attributeの永続化先（PostGIS）。docker-compose.ymlのpostgresサービスに
    # 対応する。ElevationAttributeServiceへrepositoryを明示的に注入した場合にのみ使われる
    # （infrastructure/database.py, road_graph_repository.py）。GraphServiceは常に
    # repository必須（このURLへの接続必須）。
    database_url: str = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass"
    # Road Graphの永続化（PostGIS）をランタイムのread-throughキャッシュとして使うかどうか。
    # 既定はTrue（DB接続ありを前提）。詳細（GraphServiceは常にrepository必須で本設定の
    # 影響を受けないこと、DBなし環境での安全側フォールバック）はdocs/modules/backend/
    # cross-cutting-infrastructure.md「設定」節参照。
    road_graph_use_repository: bool = True
    # 基礎地図プロキシ（/api/basemap）のスタイルJSON内URL書き換えに使う絶対URL。
    # MapLibreは相対URLをスタイル自身の取得元ではなくページのオリジンに対して解決してしまう
    # ため絶対URLへの書き換えが必須で、かつフロントエンド（Next.jsのrewrites経由でこの
    # /api/basemapにプロキシする）と同一オリジンにする必要がある。バックエンド自身のURLでは
    # ない点に注意（タイル大量リクエストとAPI呼び出しをブラウザの同一オリジン接続数上限で
    # 競合させないための設計、詳細はfrontend/next.config.tsのコメント参照）。
    basemap_public_base_url: str = "http://localhost:3000/api/basemap"
    # 調査用デバッグモード。有効にすると外部API呼び出し（MSM配信元/Overpass/OpenFreeMap）
    # やタイルキャッシュのhit/missをイベント単位でDEBUGログに出力する（main.pyのlogging設定を参照）。
    debug_mode: bool = False
    # デプロイ先で実際にビルド・起動されたコミットのフルSHA（`GIT_COMMIT`環境変数、
    # .envには書かない。ローカル開発では未設定のためNoneのまま）。`/health`のレスポンスに
    # 含め、本番で実際に動いているコミットが手元のgit HEADと一致しているか（＝最新版が
    # 反映されているか）を外部から確認できるようにする（詳細はdocs/architecture.md参照）。
    git_commit: str | None = None

    # --- 認証なしエンドポイントのper-IPレート制限・同時実行上限（api/routers/*が参照） ---
    # 環境（Render無料枠/ローカル/負荷試験）で調整したい運用値のため.envで上書き可能に
    # している。各値の根拠は以下の通り。
    #
    # /preview・/weatherは/generateほど高コストではない（いずれも外部APIを叩かない）。
    preview_rate_limit_per_minute: int = 20
    weather_rate_limit_per_minute: int = 60
    # 風の格子点マップは1回で関東本土全域（約624地点、domain/wind_grid.py:
    # WIND_GRID_SPACING_DEG=0.1度間隔）ぶんの応答を組み立てるエンドポイントのため、
    # /weather（1地点）より低めに絞る。値はローカルのMSMファイルから読むため外部APIは
    # 消費しないが、応答サイズ（数百KB）と直列化コストは地点数に比例する。
    wind_grid_rate_limit_per_minute: int = 20
    # 詳細格子（ズームイン時の面表現用）。パン・ズームのたびに（デバウンス済みとはいえ）
    # 呼ばれうるためwind_gridより高めにする。1回あたりの地点数は
    # WIND_GRID_DETAIL_MAX_POINTSで上限が掛かる。
    wind_grid_detail_rate_limit_per_minute: int = 30
    # 警報・注意報バッジ。/weatherと同じ地点変更時デバウンス起点で呼ばれる
    # （1回の呼び出しでGSI逆ジオコーダ・JMA地域マスタ・JMA警報APIの最大3件を叩きうるが、
    # 後2者は長寿命TTLキャッシュが効くため実際の外部リクエストは大半がGSI呼び出しのみ）。
    weather_warnings_rate_limit_per_minute: int = 30
    # WBGT警告バッジ。/weather・/weather/warningsと同じ地点変更デバウンス
    # 起点で呼ばれる。地点マスタCSV・予測値APIともに長寿命TTLキャッシュが効くため、
    # 実際の外部リクエストは大半がキャッシュヒットになる。
    weather_wbgt_rate_limit_per_minute: int = 30
    # 河川氾濫予報バッジ。/weather/warnings・/weather/wbgtと同じ地点変更
    # デバウンス起点で呼ばれる。洪水予報API自体は10分TTLキャッシュが効く。
    weather_flood_forecast_rate_limit_per_minute: int = 30
    # 最寄りアメダス観測値。他の/weather系バッジと同じ地点変更デバウンス
    # 起点で呼ばれる想定。観測値自体はRedis Hash（TTL 15分）でキャッシュされるため、
    # 実際のJMA呼び出しは大半がキャッシュヒットになる。
    weather_amedas_rate_limit_per_minute: int = 30
    # ルート生成は最も高コストなエンドポイント（PostGISへの大量問い合わせ・コールド時の
    # Road Graph再構築で数十秒〜最大300秒超）のため、per-IPレート制限に加えプロセス全体の
    # 同時実行数も制限する。
    # 上限超過は待たせず429で即座に返す（ブラウザのリトライや連打で外部サービスへの負荷が
    # 積み上がることを防ぐ）。
    generate_rate_limit_per_minute: int = 10
    generate_max_concurrent: int = 2
    # 路面タイルはPostGIS問い合わせ・ディスクキャッシュ書き込みを伴うため、無制限に叩かれると
    # 外部サービス負荷やディスク消費に繋がる。同時実行上限6の根拠: ST_AsMVT化でタイル処理は
    # ほぼDB応答待ちになり、律速はDB側の同時クエリ負荷とSQLAlchemyの接続プール
    # （既定pool_size=5+max_overflow=10=最大15接続）。6なら事故タイル分と合わせても
    # タイル配信系プールの上限に収まり、コールドタイルのバースト時の待ち行列を半減できる
    # （ルート生成は専用エンジン・別プール[さらに15接続、database.py:
    # get_route_generation_engine]のため、ルート生成とタイル配信は接続プールを取り合わない。
    # プール合計は最大30接続で、本番PostgreSQLのmax_connections=100に対し余裕がある）。
    road_tile_rate_limit_per_minute: int = 120
    road_tile_max_concurrent: int = 6
    # 区間インスペクタ（region.py: region_axis_inspector、地図クリックで1件のosm_way_idを
    # 引くAPI）は座標を持たない単発リクエストで、パン/ズームのたびに多数のz/x/yタイルを
    # 連続要求するroad_tileとは負荷特性が異なるため別設定として持つ。
    axis_inspector_rate_limit_per_minute: int = 120
    # 事故タイル。road_tileと同じ理由（PostGIS問い合わせ・ディスクキャッシュ書き込みを
    # 伴う）で同種の歯止めを持つが、accident_pointsはroad_edgesよりテーブルが小さく
    # 1タイルあたりのクエリコストも低いため、road_tileよりやや緩い上限にしている。
    accident_tile_rate_limit_per_minute: int = 120
    accident_tile_max_concurrent: int = 6
    # 地図タイル閲覧起点の道路グラフ構築（RegionService._maybe_trigger_graph_build）。
    # closure再計算・Edge全量再UPSERTを伴う重い処理（数十秒〜数分規模）で、DBセッションを
    # 長時間保持する。road_tile_max_concurrent(6)+accident_tile_max_concurrent(6)で
    # 接続プール上限15のうち既に12を使いうるため、残り枠を大きく占有しないよう低く抑える
    # （密集した未構築エリアへの一斉アクセスでプールが枯渇すると、無関係な他タイル・API呼び出し
    # まで502化しうる）。ユーザー体験には影響しない完全なバックグラウンド処理のため、
    # 待たされても実害が無く1で十分（複数エリアへの構築要求は順番に処理される）。
    graph_build_max_concurrent: int = 1
    basemap_rate_limit_per_minute: int = 300
    # refreshはbasemap/road-tile両方のディスクキャッシュを一括削除する破壊的操作のため、
    # 通常のbasemapプロキシより厳しい上限にする（連打されるとキャッシュが常に温まらず、
    # Overpass/OpenFreeMapへの実問い合わせが毎回発生し続けてしまう）。
    basemap_refresh_rate_limit_per_minute: int = 6
    # JMA動的タイル系レイヤーのプロキシ。降水ナウキャスト・rasrf・
    # 雷/竜巻ナウキャスト・キキクル・線状降水帯予測マップの各タイル・時刻一覧をまとめて
    # 経由するため、basemapと同水準の上限にする。
    jma_tile_rate_limit_per_minute: int = 300
    # 国土地理院 色別標高図タイルのプロキシ。basemap/jma-tileと同水準の上限。
    gsi_relief_tile_rate_limit_per_minute: int = 300
    # JMA動的タイルの定期プリウォーム間隔。JMA側の実更新間隔（5〜10分おき、
    # jma_tile_client.pyのコメント参照）に合わせ、アメダス（AMEDAS_REFRESH_INTERVAL_MINUTES）
    # と同じ10分にした。
    jma_tile_prewarm_interval_minutes: int = 10
    # JMA非公式APIへの実際の秒間リクエスト数の上限。プリウォーム本体の同時実行数制御
    # （jma_tile_prewarm_service.py: _MAX_CONCURRENCY=8）だけでは、各リクエストの応答が
    # 速いと総スループット（秒間リクエスト数）自体は青天井になるため、jma_tile_client.py:
    # fetchの実フェッチ直前でこの秒間上限を守るよう待機する（キャッシュヒットは対象外、
    # プリウォーム・オンデマンド双方の実フェッチ経路を共有する）。1983タイル/回・10分間隔の
    # 定期プリウォームに対し、この値でも十分に間隔内へ収まる（1983/5≒397秒 < 600秒）よう
    # 控えめに設定した。
    jma_tile_upstream_max_requests_per_second: float = 5.0

    # 気象庁MSM（前処理済み.omファイル、CC-BY-4.0）の配信元。REST APIではなく静的
    # ファイルのため、レート制限・クォータの制約を受けない（infrastructure/msm_client.py）。
    msm_base_url: str = "https://openmeteo.s3.amazonaws.com/data/jma_msm"
    # MSMの定期同期間隔。配信元のrun更新は3時間ごと（メタ情報のupdate_interval_seconds）
    # だが公開はrun初期時刻から数時間遅れるため、更新の有無をこの間隔で確認する
    # （内容が変わっていなければETagの条件付きGETで転送自体が起きない）。
    msm_sync_interval_minutes: int = 30
    # 風グリッド・ルート評価が要求する予報の長さ。runごとの予報時間（39時間、00/12UTCの
    # runは78時間）を超える分は配信元のデータ終端で打ち切られる。
    msm_forecast_hours: int = 48

    # 管理画面（/admin、軸スタジオの管理API/api/admin/axis-definitions）を保護するHTTP Basic
    # 認証の資格情報。空文字（既定）のときは常に拒否する（うっかり無保護
    # 公開しない、api/routers/axis_admin.py: require_admin_basic_auth参照）。frontend側
    # （src/proxy.ts、/adminページ全体のルーティング境界）も同じ資格情報をNEXT側の環境変数
    # （ADMIN_BASIC_AUTH_USERNAME/PASSWORD）として持つ——2つの独立したBasic認証チェック
    # （ページ本体とAPI呼び出しはオリジンが異なるためブラウザの認証情報が自動伝播しない）
    # だが、同じ値を設定運用することで実質1つの資格情報として扱う。
    admin_basic_auth_username: str = ""
    admin_basic_auth_password: str = ""

    # JMA気象データ（アメダス・降水ナウキャスト・MSM）の短命キャッシュと、
    # road_graph_tilesタイル取得済みマーカーのcache-aside層（infrastructure/road_graph_tile_cache.py）
    # が使う。いずれもTTL付きキャッシュ、またはPostGIS（正本）へフォールバック可能なcache-asideの
    # ため、Redis側に永続化（RDB/AOF）設定は要らない設計にしてある（再起動・キャッシュ消失時は
    # 次回アクセスで自己修復する。infrastructure/redis_client.pyのdocstring参照）。
    # 本番はOracle Cloud VM上にネイティブ（apt、PostgreSQLと同じ構成）で導入する想定。
    # backendコンテナは--network=hostで起動するため、この既定値（localhost）のまま
    # VM上のRedisへ到達できる（導入手順はdocs/architecture.md参照）。
    redis_url: str = "redis://localhost:6379/0"

    # タイル材料キャッシュ（graph_material_cache.py・tile_score_matrix_cache.py）の
    # ディスク永続化キャッシュ（infrastructure/tile_persistent_cache.py）読み込みの
    # 同時実行数上限。案C1（列指向EdgeMaterialTable化）で残るCPUコストは`LeanEdge`等の
    # 再構築を伴うPythonループのためGILで直列化される——コア数を増やして効くのは
    # ファイルI/O・numpy部分のみで、コア数に比例して線形に速くなるのは案C2（グラフ側も
    # 完全列指向化する将来の別タスク）まで進めた場合に限る。既定は
    # `min(4, os.cpu_count())`（コア数が少ない環境でも過剰にスレッドを起動しない）。
    tile_cache_load_max_concurrent: int = Field(default_factory=lambda: min(4, os.cpu_count() or 4))

    # 土地被覆バッチ（app/batch/precompute_way_landcover.py）が読むEsri×Impact
    # Observatory LULCのGeoTIFFファイルパス（カンマ区切り、複数ゾーン対応）。
    # ラスタ自体はリポジトリにコミットせず手動取得する（docs/disaster-recovery.md参照）ため
    # .envでのみ設定する。空文字列（未設定）はrefresh_derived.py経由の実行時のみ
    # フェイルファストの対象になる（バッチを直接`--raster`引数付きで呼ぶ場合は無関係）。
    lulc_raster_paths: str = ""

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return self.cors_allowed_origins.split(",")

    @property
    def lulc_raster_paths_list(self) -> list[str]:
        return [p for p in self.lulc_raster_paths.split(",") if p]


settings = Settings()
