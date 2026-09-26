from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 相対パス".env"はプロセスのカレントディレクトリ基準になるため、backend/をcwdにしない
# 起動方法では読み込まれない。このファイルの位置から解決してcwdへの依存を無くす。
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    cors_allowed_origins: str = "http://localhost:3000"
    database_url: str = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass"
    # 基礎地図プロキシのスタイルJSON内URLを書き換える先。MapLibreは相対URLをスタイルの
    # 取得元ではなくページのオリジンに対して解決するため絶対URLが必須で、かつ**backend自身
    # ではなくフロントエンドのオリジン**にする（タイルの大量リクエストとAPI呼び出しを
    # ブラウザの同一オリジン接続数上限で競合させない。frontend/next.config.ts参照）。
    basemap_public_base_url: str = "http://localhost:3000/api/basemap"
    debug_mode: bool = False
    # デプロイ先でビルド・起動されたコミットのフルSHA。`GIT_COMMIT`環境変数から渡し、
    # .envには書かない（ローカル開発では未設定のままでよい）。
    git_commit: str | None = None

    # --- 認証なしエンドポイントのper-IPレート制限・同時実行上限 ---
    # 環境（本番/ローカル/負荷試験）ごとに調整したい運用値のため.envで上書きできる。
    #
    # /preview・/weatherはいずれも外部APIを叩かず、/generateほど高コストではない。
    preview_rate_limit_per_minute: int = 20
    weather_rate_limit_per_minute: int = 60
    # 風の格子点マップは1回で関東本土全域ぶんの応答を組み立てる。値はローカルのMSM
    # ファイルから読むため外部APIは消費しないが、応答サイズ（数百KB）と直列化コストが
    # 地点数に比例するため/weather（1地点）より絞る。
    wind_grid_rate_limit_per_minute: int = 20
    # 詳細格子はパン・ズームのたびに（デバウンス済みとはいえ）呼ばれうるため高めにする。
    wind_grid_detail_rate_limit_per_minute: int = 30
    # /weather系のバッジ群。いずれも/weatherと同じ地点変更デバウンスを起点に呼ばれ、
    # 外部への実リクエストは長寿命TTLキャッシュで大半が吸収される。
    weather_warnings_rate_limit_per_minute: int = 30
    weather_wbgt_rate_limit_per_minute: int = 30
    weather_flood_forecast_rate_limit_per_minute: int = 30
    weather_amedas_rate_limit_per_minute: int = 30
    # ルート生成は最も高コストなエンドポイント（1件で数秒〜数十秒CPUを使い、探索範囲に比例して
    # メモリを使う）のため、per-IPレート制限に加えプロセス全体の同時実行数も絞る。
    # 1回の生成が扱える探索範囲の上限（`graph_service`）は、メモリ上限をこの件数で割って決まる。
    generate_rate_limit_per_minute: int = 10
    generate_max_concurrent: int = 2
    # タイル処理の律速はDB側の同時クエリ負荷とSQLAlchemyの接続プール
    # （既定pool_size=5+max_overflow=10=最大15接続）。路面・事故の同時実行上限の和が
    # このプール上限に収まるようにする（ルート生成は別エンジン・別プールで取り合わない）。
    road_tile_rate_limit_per_minute: int = 120
    road_tile_max_concurrent: int = 6
    # 区間インスペクタは座標を持たない単発リクエストで、パン/ズームのたびに多数のz/x/y
    # タイルを連続要求するroad_tileとは負荷特性が異なるため別の上限を持つ。
    axis_inspector_rate_limit_per_minute: int = 120
    accident_tile_rate_limit_per_minute: int = 120
    accident_tile_max_concurrent: int = 6
    # 土地被覆ラスタタイルはDBを読まず、GeoTIFFの読み取り・再投影（GDAL）をスレッドプールで
    # 行う。律速がCPUとディスクI/Oになるため、DB向けのタイル上限とは別に持つ。
    # `asyncio.to_thread`の既定スレッドプールを1画面ぶんのタイルで埋めないための値。
    landcover_tile_max_concurrent: int = 4
    basemap_rate_limit_per_minute: int = 300
    jma_tile_rate_limit_per_minute: int = 300
    gsi_tile_rate_limit_per_minute: int = 300
    # JMA動的タイルの定期プリウォーム間隔。JMA側の実更新間隔は5〜10分おき。
    jma_tile_prewarm_interval_minutes: int = 10
    # JMA非公式APIへ実際に投げる秒間リクエスト数の上限。プリウォーム本体の同時実行数制御
    # だけでは、各リクエストの応答が速いと総スループットが青天井になるため、実フェッチ
    # 直前でこの秒間上限を守るよう待機する（jma_tile_client.py、キャッシュヒットは対象外）。
    # 1回のプリウォームがこの秒間上限のままでも次の間隔までに終わる値にしてある。
    jma_tile_upstream_max_requests_per_second: float = 5.0

    # 気象庁MSM（前処理済み.omファイル、CC-BY-4.0）の配信元。REST APIではなく静的
    # ファイルのため、レート制限・クォータの制約を受けない。
    msm_base_url: str = "https://openmeteo.s3.amazonaws.com/data/jma_msm"
    # 配信元のrun更新は3時間ごとだが公開はrun初期時刻から数時間遅れるため、更新の有無を
    # これより短い間隔で確認する（内容が変わっていなければETagの条件付きGETで転送は起きない）。
    msm_sync_interval_minutes: int = 30
    # 要求する予報の長さ。runごとの予報時間（39時間、00/12UTCのrunは78時間）を超える分は
    # 配信元のデータ終端で打ち切られる。
    msm_forecast_hours: int = 48

    # 管理画面・管理APIのHTTP Basic認証（空文字のときの扱いはapi/admin_auth.py）。
    # frontend側も同じ資格情報を別の環境変数として持ち、同じ値を設定して運用する。
    admin_basic_auth_username: str = ""
    admin_basic_auth_password: str = ""

    # 短命キャッシュ専用で、失っても外部から取り直せるものしか置かない——Redis側に
    # 永続化（RDB/AOF）設定は要らない。本番はVM上にネイティブ導入し、backendコンテナは
    # --network=hostで起動するためこの既定値のまま到達できる。
    redis_url: str = "redis://localhost:6379/0"

    # ディスク永続キャッシュ（way_id別の動的値）の容量上限（MB）。上限に達するとdiskcacheが
    # 古いものから退避する。置く値は鍵ごとの失効（expire）で入れ替わるため、上限は伸び続けた
    # ときの頭打ちとして置いている（本番VMのディスクは48GB）。
    tile_persistent_cache_size_limit_mb: int = 1024

    # 焼き済みタイル・外部タイルの置き場の容量上限（MB）。この置き場は鍵に世代を持たない
    # ため、形の署名が変わった旧世代は書かれなくなるだけで残り続ける。起動時に古い順で
    # 上限まで落とす。本番の実測は数十MB規模で、上限は伸び続けたときの頭打ちとして置いている。
    tile_cache_size_limit_mb: int = 512

    # ディスクキャッシュをDBの派生データ世代へ追随させる確認の間隔（秒）。派生バッチは
    # backendを再起動させないため、材料を使う経路からこの間隔で読み直す。バッチ自体が
    # 数十分かかるためこの程度の遅れは運用上の差にならず、読むのは1行テーブルの1列だけ。
    derived_data_revision_check_interval_seconds: float = 300.0

    # Esri×Impact Observatory LULCのGeoTIFFファイルパス（カンマ区切り、複数ゾーン対応）。
    # ラスタ自体はリポジトリにコミットせず手動取得するため.envでのみ設定する。
    lulc_raster_paths: str = ""

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return self.cors_allowed_origins.split(",")

    @property
    def lulc_raster_paths_list(self) -> list[str]:
        return [p for p in self.lulc_raster_paths.split(",") if p]


settings = Settings()
