from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# 相対パス".env"はプロセスのカレントディレクトリ基準になるため、backend/以外から
# 起動した場合（例: uvicornに--app-dir backendだけを渡しリポジトリルートから起動する等、
# cwdを変えない起動方法）に読み込まれない。config.py自身の位置から解決することで
# 起動時のcwdに依存しないようにする。
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    cors_allowed_origins: str = "http://localhost:3000"
    openrouteservice_api_key: str = ""
    # /api/routes/generateのルーティングエンジン切り替え。"road_graph"（自前Road Graph+
    # scipy.sparse.csgraph Dijkstra、外部APIキー不要。road_graph_engine.py）と
    # "openrouteservice"（外部APIキー方式、Road Graph移行前の実装。openrouteservice_engine.py）
    # のどちらを使うかを選べる。改善計画T236（経路品質比較、致命的な差異なし）・T241
    # （道路グラフの連結性、致命的な問題ではない）・T242〜T246（本番DBのmigration未適用・
    # DELETE性能問題という本番実行不能の原因を解消、実データで検証済み）を経て、既定値を
    # road_graphへ切り替えた（2026-08-23、ユーザー判断）。road_graphを使うには
    # `DATABASE_URL`への実接続が必須（改善計画T222でDBなし構成を撤去済みのため）。
    routing_engine: Literal["road_graph", "openrouteservice"] = "road_graph"
    # Road Graph/Road Attributeの永続化先（PostGIS）。docker-compose.ymlのpostgresサービスに
    # 対応する。ElevationAttributeServiceへrepositoryを明示的に注入した場合にのみ使われる
    # （infrastructure/database.py, road_graph_repository.py）。GraphServiceは改善計画T222で
    # repository必須（このURLへの接続必須）へ一本化済み。
    database_url: str = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass"
    # Road Graphの永続化（PostGIS）をランタイムのread-throughキャッシュとして使うかどうか。
    # ElevationAttributeService・地図表示系（RegionService/AccidentService、
    # ORSエンジンの路面評価用surface_match_repository）へRoadGraphRepositoryを注入するかを
    # 切り替える。database_urlのDBへ実際に接続できない環境ではFalseにすること（これらは
    # DBなしで動作する）。GraphService（get_or_build_graph_with_attributes等、
    # routing_engine=road_graphのルート生成が使う）はこの設定に関わらず常にrepositoryを
    # 必要とする（改善計画T222でDBなし構成を撤去済みのため、Falseのままroad_graphエンジンを
    # 使うとGraphService経由のDBアクセスが失敗する）。
    # 改善計画T283: 既定はTrue（DB接続ありを前提）。以前はFalseが既定だったため、新環境
    # 構築時にこの設定を明示し忘れると「ルート生成は動くのに地図レイヤーがすべて空」という
    # 気づきにくい縮退になっていた（レビュー指摘）。DB接続失敗時は既存の空タイル
    # フォールバック（vector_tile.py: encode_empty_road_surface_tile等）が効くため、
    # DBが無い環境でTrueのままでも安全側に倒れる（単に空タイルが返るだけ）。DBなし構成を
    # 明示的に選びたい場合（.env.exampleの「開発（DBなし）」プロファイル等）は引き続き
    # 明示的にFalseを設定すること。
    road_graph_use_repository: bool = True
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
    # デプロイ先で実際にビルド・起動されたコミットのフルSHA（`GIT_COMMIT`環境変数、
    # .envには書かない。ローカル開発では未設定のためNoneのまま）。`/health`のレスポンスに
    # 含め、本番で実際に動いているコミットが手元のgit HEADと一致しているか（＝最新版が
    # 反映されているか）を外部から確認できるようにする（詳細はdocs/architecture.md参照）。
    # 改善計画T263: backendがRenderからOracle Cloud VMへ移行し、Render固有の自動注入
    # 環境変数`RENDER_GIT_COMMIT`が使えなくなったため、デプロイワークフロー
    # （.github/workflows/deploy-backend.yml）側で`git rev-parse HEAD`の結果を明示的に
    # `GIT_COMMIT`として渡す方式へ変更した（旧名`render_git_commit`から改称）。
    git_commit: str | None = None

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
    # WBGT警告バッジ（改善計画T174）。/weather・/weather/warningsと同じ地点変更デバウンス
    # 起点で呼ばれる。地点マスタCSV・予測値APIともに長寿命TTLキャッシュが効くため、
    # 実際の外部リクエストは大半がキャッシュヒットになる。
    weather_wbgt_rate_limit_per_minute: int = 30
    # 河川氾濫予報バッジ（改善計画T212）。/weather/warnings・/weather/wbgtと同じ地点変更
    # デバウンス起点で呼ばれる。洪水予報API自体は10分TTLキャッシュが効く。
    weather_flood_forecast_rate_limit_per_minute: int = 30
    # 最寄りアメダス観測値（改善計画T387）。他の/weather系バッジと同じ地点変更デバウンス
    # 起点で呼ばれる想定。観測値自体はRedis Hash（TTL 15分）でキャッシュされるため、
    # 実際のJMA呼び出しは大半がキャッシュヒットになる。
    weather_amedas_rate_limit_per_minute: int = 30
    # ルート生成は最も高コストなエンドポイント（openrouteserviceエンジン: 8方位分のORS呼び出し＋
    # 標高・天候の外部API / road_graphエンジン: Overpass・GSIへの大量問い合わせでコールド時
    # 40〜70秒）のため、per-IPレート制限に加えプロセス全体の同時実行数も制限する。
    # 上限超過は待たせず429で即座に返す（ブラウザのリトライや連打で外部サービスへの負荷が
    # 積み上がることを防ぐ）。
    generate_rate_limit_per_minute: int = 10
    generate_max_concurrent: int = 2
    # 路面タイルはPostGIS問い合わせ・ディスクキャッシュ書き込みを伴うため、無制限に叩かれると
    # 外部サービス負荷やディスク消費に繋がる。同時実行上限6の根拠: ST_AsMVT化でタイル処理は
    # ほぼDB応答待ちになり、律速はDB側の同時クエリ負荷とSQLAlchemyの接続プール
    # （既定pool_size=5+max_overflow=10=最大15接続）。6なら事故タイル分と合わせても
    # タイル配信系プールの上限に収まり、コールドタイルのバースト時の待ち行列を半減できる
    # （詳細な経緯はapi/routers/region.pyのコメント参照。改善計画T243でルート生成系は
    # 専用エンジン・別プール[さらに15接続、database.py: get_route_generation_engine]へ
    # 分離済みのため、ルート生成とタイル配信は接続プールを取り合わない。プール合計は
    # 最大30接続で、本番PostgreSQLのmax_connections=100に対し余裕がある）。
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

    # 管理画面（/admin、軸スタジオの管理API/api/admin/axis-definitions）を保護するHTTP Basic
    # 認証の資格情報（改善計画T272）。空文字（既定）のときは常に拒否する（うっかり無保護
    # 公開しない、api/routers/axis_admin.py: require_admin_basic_auth参照）。以前は
    # 共有トークン（X-Admin-Tokenヘッダ、axis_admin_token）による簡易保護だったが、T272で
    # 「実権限チェックへの差し替え」としてBasic認証へ置き換えた（ユーザー方針、2026-08-24:
    # 「将来的にはアカウント制としたいが、現状は動作確認・研究用のためBasic認証として
    # 後から拡張する」）。frontend側（src/proxy.ts、/adminページ全体のルーティング境界）も
    # 同じ資格情報をNEXT側の環境変数（ADMIN_BASIC_AUTH_USERNAME/PASSWORD）として持つ
    # ——2つの独立したBasic認証チェック（ページ本体とAPI呼び出しはオリジンが異なるため
    # ブラウザの認証情報が自動伝播しない、docs/architecture.md「T272」節参照）だが、
    # 同じ値を設定運用することで実質1つの資格情報として扱う。
    admin_basic_auth_username: str = ""
    admin_basic_auth_password: str = ""

    # Redis（改善計画T387）。JMA気象データ（アメダス・降水ナウキャスト・MSM）の短命キャッシュと、
    # road_graph_tilesタイル取得済みマーカーのcache-aside層（infrastructure/road_graph_tile_cache.py）
    # が使う。いずれもTTL付きキャッシュ、またはPostGIS（正本）へフォールバック可能なcache-asideの
    # ため、Redis側に永続化（RDB/AOF）設定は要らない設計にしてある（再起動・キャッシュ消失時は
    # 次回アクセスで自己修復する。infrastructure/redis_client.pyのdocstring参照）。
    # 本番はOracle Cloud VM上にネイティブ（apt、PostgreSQLと同じ構成）で導入する想定。
    # backendコンテナは--network=hostで起動するため、この既定値（localhost）のまま
    # VM上のRedisへ到達できる（導入手順はdocs/architecture.md参照）。
    redis_url: str = "redis://localhost:6379/0"

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return self.cors_allowed_origins.split(",")


settings = Settings()
