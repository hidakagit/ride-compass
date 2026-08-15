from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RouteSegment(BaseModel):
    distance_km: float
    duration_minutes: float
    geometry: dict
    surface_summary: list[dict] | None = None
    surface_values: list[list] | None = None


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
    elevation_difficulty: float | None = None
    wind_difficulty: float | None = None
    road_difficulty: float | None = None
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
    total_score: float | None = None
    score_breakdown: list[RouteScoreComponent] | None = None
    segments: list[RouteSegmentDetail] | None = None
