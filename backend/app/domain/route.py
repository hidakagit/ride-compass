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
    """周回ルートの1区間（サンプル点i→i+1）の詳細。地図上の難易度レイヤー描画に使う。"""

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
    segments: list[RouteSegmentDetail] | None = None
