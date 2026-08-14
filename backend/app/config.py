from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_allowed_origins: str = "http://localhost:3000"
    openrouteservice_api_key: str = ""
    # Road Graph/Road Attributeの永続化先（PostGIS）。docker-compose.ymlのpostgresサービスに
    # 対応する。現時点ではどのAPIエンドポイントもこれに依存していない（DBが無くても
    # 既存機能は動作する）。GraphService/ElevationAttributeServiceへrepositoryを明示的に
    # 注入した場合にのみ使われる（infrastructure/database.py, road_graph_repository.py）。
    database_url: str = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass"
    # 基礎地図プロキシ（/api/basemap）のスタイルJSON内URL書き換えに使う絶対URL。
    # MapLibreは相対URLをスタイル自身の取得元ではなくページのオリジンに対して解決してしまう
    # ため絶対URLへの書き換えが必須で、かつフロントエンド（Next.jsのrewrites経由でこの
    # /api/basemapにプロキシする）と同一オリジンにする必要がある。バックエンド自身のURLでは
    # ない点に注意（タイル大量リクエストとAPI呼び出しをブラウザの同一オリジン接続数上限で
    # 競合させないための設計、詳細はfrontend/next.config.tsのコメント参照）。
    basemap_public_base_url: str = "http://localhost:3000/api/basemap"
    # 調査用デバッグモード。有効にすると外部API呼び出し（Open-Meteo/Overpass/OpenFreeMap）
    # やタイルキャッシュのhit/missをイベント単位でDEBUGログに出力する（main.pyのlogging設定を参照）。
    debug_mode: bool = False

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return self.cors_allowed_origins.split(",")


settings = Settings()
