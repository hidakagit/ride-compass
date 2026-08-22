from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_allowed_origins: str = "http://localhost:3000"
    openrouteservice_api_key: str = ""
    # /api/routes/generateのルーティングエンジン切り替え。"road_graph"（自前Road Graph+
    # NetworkX Dijkstra、外部APIキー不要だがルーティング自体は開発中。road_graph_engine.py）と
    # "openrouteservice"（外部APIキー方式、Road Graph移行前の実装。openrouteservice_engine.py）
    # のどちらを使うかを選べる。ルーティング部分は将来拡張として並行開発を続ける一方、
    # 現状はマップの見える化・評価に必要な情報の精査を優先するため、既定値はopenrouteservice。
    routing_engine: Literal["road_graph", "openrouteservice"] = "openrouteservice"
    # Road Graph/Road Attributeの永続化先（PostGIS）。docker-compose.ymlのpostgresサービスに
    # 対応する。現時点ではどのAPIエンドポイントもこれに依存していない（DBが無くても
    # 既存機能は動作する）。GraphService/ElevationAttributeServiceへrepositoryを明示的に
    # 注入した場合にのみ使われる（infrastructure/database.py, road_graph_repository.py）。
    database_url: str = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass"
    # Road Graphの永続化（PostGIS）をランタイムのread-throughキャッシュとして使うかどうか。
    # Trueにすると、GraphService/ElevationAttributeServiceへRoadGraphRepositoryが注入され、
    # PBF取込バッチ（app/batch/import_pbf.py）等で取得済みマークされた範囲では
    # routing_engine=road_graphのルート生成がOverpassへ問い合わせずDBだけで完結する。
    # database_urlのDBへ実際に接続できる環境でのみ有効化すること（既定Falseのままなら
    # 従来どおりDBなしで動作する）。
    road_graph_use_repository: bool = False
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
    # Renderへデプロイされたgitサービスには`RENDER_GIT_COMMIT`（デプロイされたコミットの
    # フルSHA）が自動的に環境変数として注入される（.envには書かない。ローカル開発では
    # 未設定のためNoneのまま）。`/health`のレスポンスに含め、Render上で実際に動いている
    # コミットが手元のgit HEADと一致しているか（＝最新版が反映されているか）を外部から
    # 確認できるようにする（詳細はdocs/architecture.md参照）。
    render_git_commit: str | None = None

    # --- 認証なしエンドポイントのper-IPレート制限・同時実行上限（api/routers/*が参照） ---
    # 元はapi/routes.pyのモジュール定数だったが、環境（Render無料枠/ローカル/負荷試験）で
    # 調整したい運用値のため.envで上書き可能にした（改善計画T5）。各値の根拠は以下の通り。
    #
    # /preview・/weatherは/generateほど高コストではないが、いずれも外部APIの無料枠を
    # 消費する（openrouteservice: 日次2000リクエストをgenerateと共有 / Open-Meteo）。
    preview_rate_limit_per_minute: int = 20
    weather_rate_limit_per_minute: int = 60
    # 風の格子点マップ（改善計画T178フォローアップ）は1回で関東本土全域（約624地点、
    # domain/wind_grid.py: WIND_GRID_SPACING_DEG=0.1度間隔。0.35度間隔だった初期値
    # 約56地点からユーザー要望「通常ズームでもある程度使えるように」を受け密度を
    # 上げた経緯はwind_grid.py参照）をまとめて取得する重いエンドポイントのため、
    # /weather（1地点）より低めに絞る。TTLキャッシュ（weather_client.py、T195でL1+L2の
    # 2段構成・TTL 3時間へ拡大）が効くため、同一クライアントの短時間の再取得
    # （時刻スライダー操作等）はキャッシュヒットしOpen-Meteoへは行かない。
    wind_grid_rate_limit_per_minute: int = 20
    # 詳細格子（改善計画T180、ズームイン時の面表現用）。パン・ズームのたびに（デバウンス済み
    # とはいえ）呼ばれうるためwind_gridより高めにするが、固定ラティス由来のキャッシュ共有
    # （domain/wind_grid.py: generate_wind_grid_detail_points参照）により大半はOpen-Meteoへの
    # 新規リクエストを伴わない軽い呼び出しになる想定。
    wind_grid_detail_rate_limit_per_minute: int = 30
    # 警報・注意報バッジ（改善計画T205）。/weatherと同じ地点変更時デバウンス起点で呼ばれる
    # （1回の呼び出しでGSI逆ジオコーダ・JMA地域マスタ・JMA警報APIの最大3件を叩きうるが、
    # 後2者は長寿命TTLキャッシュが効くため実際の外部リクエストは大半がGSI呼び出しのみ）。
    weather_warnings_rate_limit_per_minute: int = 30
    # ルート生成は最も高コストなエンドポイント（openrouteserviceエンジン: 8方位分のORS呼び出し＋
    # 標高・天候の外部API / road_graphエンジン: Overpass・GSIへの大量問い合わせでコールド時
    # 40〜70秒）のため、per-IPレート制限に加えプロセス全体の同時実行数も制限する。
    # 上限超過は待たせず429で即座に返す（ブラウザのリトライや連打で外部サービスへの負荷が
    # 積み上がることを防ぐ）。
    generate_rate_limit_per_minute: int = 10
    generate_max_concurrent: int = 2
    # 路面タイルはPostGIS問い合わせ・ディスクキャッシュ書き込みを伴うため、無制限に叩かれると
    # 外部サービス負荷やディスク消費に繋がる。同時実行上限6の根拠: ST_AsMVT化でタイル処理は
    # ほぼDB応答待ちになり、律速はSupabase側の同時クエリ負荷とSQLAlchemyの接続プール
    # （既定pool_size=5+max_overflow=10=最大15接続）。6ならルート生成用の接続と合わせても
    # プール上限に収まり、コールドタイルのバースト時の待ち行列を半減できる
    # （詳細な経緯はapi/routers/region.pyのコメント参照）。
    road_tile_rate_limit_per_minute: int = 120
    road_tile_max_concurrent: int = 6
    # 事故タイル（外部静的データソース T50）。road_tileと同じ理由（PostGIS問い合わせ・
    # ディスクキャッシュ書き込みを伴う）で同種の歯止めを持つが、accident_pointsは
    # road_edgesよりテーブルが小さく1タイルあたりのクエリコストも低いため、road_tileより
    # やや緩い上限にしている。
    accident_tile_rate_limit_per_minute: int = 120
    accident_tile_max_concurrent: int = 6
    # 地図タイル閲覧起点の道路グラフ構築（改善計画T59、RegionService._maybe_trigger_graph_build）。
    # closure再計算・Edge全量再UPSERTを伴う重い処理（数十秒〜数分規模）で、DBセッションを
    # 長時間保持する。road_tile_max_concurrent(6)+accident_tile_max_concurrent(6)で
    # 接続プール上限15のうち既に12を使いうるため、残り枠を大きく占有しないよう低く抑える
    # （密集した未構築エリアへの一斉アクセスでプールが枯渇し、無関係な他タイル・API呼び出しまで
    # 502化した実障害を受けての対応）。ユーザー体験には影響しない完全なバックグラウンド処理
    # のため、待たされても実害が無く1で十分（複数エリアへの構築要求は順番に処理される）。
    graph_build_max_concurrent: int = 1
    basemap_rate_limit_per_minute: int = 300
    # refreshはbasemap/road-tile両方のディスクキャッシュを一括削除する破壊的操作のため、
    # 通常のbasemapプロキシより厳しい上限にする（連打されるとキャッシュが常に温まらず、
    # Overpass/OpenFreeMapへの実問い合わせが毎回発生し続けてしまう）。
    basemap_refresh_rate_limit_per_minute: int = 6
    # Open-Meteo Forecast APIの呼び出し先。既定は本家直叩き（ローカル開発用）。
    # 本番（Render）はOpen-Meteo側が送信元IP単位でレート制限しており、Renderの共有
    # アウトバウンドIPだと他テナントの分も巻き添えで429が常態化する不具合が確認された
    # （weather_client.pyのdocstring参照）。対策として自前ホストのOracle Cloud VM
    # （`ridecompass-postgis`、固定IP・専用、docs/osm-pbf-import.md参照）上にnginxで
    # /v1/forecastのみを中継するリレープロキシを立て、Render側はこの環境変数で
    # プロキシ経由に切り替える（アクセスはOCIセキュリティリスト+iptablesの両方で
    # Renderのアウトバウンド範囲のみに制限済み）。
    open_meteo_base_url: str = "https://api.open-meteo.com/v1/forecast"

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return self.cors_allowed_origins.split(",")


settings = Settings()
