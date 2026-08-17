from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RouteSegment(BaseModel):
    distance_km: float
    duration_minutes: float
    geometry: dict


class RouteSegmentDetail(BaseModel):
    """周回ルートの1区間（サンプル点i→i+1）の詳細。地図上の難易度レイヤー描画に使う。

    gradient_percentの正準定義: **符号付き・進行方向基準**（登り=正、下り=負）。
    両エンジン共通（openrouteservice: 区間標高差から算出 / road_graph:
    ElevationAttribute.average_grade）。フロントの勾配色分け（routeStyleModes.ts）は
    この符号を前提に「下り」カテゴリを持つため、絶対値で返してはならない。

    geometryはこの区間が実際に通る道なり形状（GeoJSON LineString、ルート全体geometryの
    部分列）。地図の区間色分けを道路形状に沿って描くために使う（以前は始点・終点の2点を
    直線で結んでおり、カーブ区間で色分け線が道路から大きく外れていた）。フロントは
    geometryがnullの場合のみ従来どおり始点・終点の直線で代替描画する（MapView.tsx:
    segmentsToFeatureCollection）。
    """

    geometry: dict | None = None
    start_latitude: float
    start_longitude: float
    end_latitude: float
    end_longitude: float
    cumulative_distance_km: float
    distance_km: float
    estimated_arrival_time: str | None = None
    gradient_percent: float | None = None
    wind_penalty: float | None = None
    road_surface_good: bool | None = None
    # 交通ストレス(1-5、domain/traffic.py: traffic_stress_level)・自転車インフラ分類
    # （domain/traffic.py: BicycleInfraClass）の生値。road_surface_goodと同じく、難易度
    # （traffic_difficulty/infra_difficulty）とは別に、将来の色分けモード等での利用に備えて
    # 生値も保持する（静的道路属性P1残り）。
    traffic_stress: int | None = None
    bicycle_infra: str | None = None
    elevation_difficulty: float | None = None
    wind_difficulty: float | None = None
    road_difficulty: float | None = None
    stop_difficulty: float | None = None
    traffic_difficulty: float | None = None
    infra_difficulty: float | None = None
    intersection_difficulty: float | None = None
    # 外部静的データソース T50残作業（事故密度、8軸目）。
    accident_difficulty: float | None = None
    difficulty: float | None = None


class RouteScoreComponent(BaseModel):
    """total_scoreの1指標分の内訳（RouteScorerが算出。研究インターフェース改善 §10-2）。

    - `score`: 候補集合内min-max正規化の0-100（相対評価。total_scoreと同じ性質で、
      同じgenerate呼び出し内の候補同士でのみ比較できる）。指標を取得できなかった候補はNone
    - `weight`: 合成に使った設定重み（scoring.yamlまたはリクエスト上書きの値そのまま）
    - `contribution`: total_scoreへの寄与点（score×weight÷有効指標の重み和）。
      有効な指標のcontributionを合計するとtotal_scoreに一致する（丸め誤差を除く）。
      scoreがNone、または合成不能（total_score=None）のときはNone
    """

    axis: str
    score: float | None = None
    weight: float
    contribution: float | None = None


class RouteCandidate(BaseModel):
    """`overall_difficulty`: segmentsの`difficulty`（絶対基準0-100）の距離加重平均
    （domain/difficulty.py: distance_weighted_difficulty）。total_scoreが同一generate
    呼び出し内の候補間でしか比較できない相対値なのに対し、これは絶対基準なので
    **異なる実験（重み・条件）間の比較**に使える（研究インターフェース改善 §10-7）。
    segments欠損時・全区間difficulty欠損時はNone。

    `stop_density`: ルート全体の信号・横断歩道・一時停止・踏切の合計密度（回/km、
    静的道路属性P1）。domain/traffic.py: distance_weighted_stop_density（合計count÷
    合計distance_kmの単純比、road_score等の「率の加重平均」とは集約方法が異なる）。

    `traffic_stress_score`: ルート全体の交通ストレス（1-5）の距離加重平均
    （domain/difficulty.py: distance_weighted_difficulty、道路情報の集計と同じ加重平均方式）。
    `bicycle_infra_score`: ルート全体の専用自転車インフラ（分離・レーン）区間の距離加重率(%)
    （domain/traffic.py: distance_weighted_bicycle_infra_score、road_scoreと同じ集約方法）。
    `intersection_density`: ルート全体の交差点密度（回/km、stop_densityと同じ集約方法）。
    いずれも静的道路属性P1残り。

    `accident_density`: ルート全体の事故密度（件/(km・年)、外部静的データソース T50残作業）。
    domain/accident.py: distance_weighted_accident_density（stop_densityと同じ「合計count÷
    合計distance_km」に収録年数での正規化を加えた集約）。
    """

    id: str
    direction_label: str
    distance_km: float
    geometry: dict
    elevation_gain_m: float | None = None
    min_elevation_m: float | None = None
    max_elevation_m: float | None = None
    max_gradient_percent: float | None = None
    wind_score: float | None = None
    road_score: float | None = None
    stop_density: float | None = None
    traffic_stress_score: float | None = None
    bicycle_infra_score: float | None = None
    intersection_density: float | None = None
    accident_density: float | None = None
    total_score: float | None = None
    score_breakdown: list[RouteScoreComponent] | None = None
    segments: list[RouteSegmentDetail] | None = None
    overall_difficulty: float | None = None
