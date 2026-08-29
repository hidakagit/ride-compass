from pydantic import BaseModel, Field

from app.domain.difficulty import distance_weighted_difficulty


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
    # 車ストレス(1-5、domain/traffic.py: car_stress_level)の生値。road_surface_goodと
    # 同じく、難易度（axis_difficulties["car_stress"]）とは別に、将来の色分けモード等での
    # 利用に備えて生値も保持する（静的道路属性P1残り）。
    car_stress: int | None = None
    # 改善計画T309: 以前はelevation_difficulty/wind_difficulty/road_difficulty/
    # stop_difficulty/car_stress_difficulty/accident_difficulty/night_difficultyという
    # 既存7軸1対1の固定フィールドだったが、軸スタジオで公開軸を自由に増減できる設計
    # （T221 Stage D以降の一連の改修の目的そのもの）と矛盾していた。軸スタジオで新規
    # 公開した軸はこの区間内訳に永遠に出てこず、逆に既存7軸のどれかを非公開にすると
    # 実装によっては未処理のKeyError/ValidationErrorで500になっていた
    # （T316フォローアップ、2026-08-25の実障害）。axis_id→difficulty(0-100)の汎用dictへ
    # 置き換え、公開軸の増減に自動追従する。評価できなかった軸（欠損データ等）は
    # キー自体を含めない（`compute_edge_axis_scores`・`evaluate_axis_difficulties`と
    # 同じ「データ無しはキーを持たない」規約）。
    axis_difficulties: dict[str, float] = Field(default_factory=dict)
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

    `car_stress_score`: ルート全体の車ストレス（1-5）の距離加重平均
    （domain/difficulty.py: distance_weighted_difficulty、道路情報の集計と同じ加重平均方式）。
    `bicycle_infra_score`: ルート全体の専用自転車インフラ（分離・レーン）区間の距離加重率(%)
    （domain/traffic.py: distance_weighted_bicycle_infra_score、road_scoreと同じ集約方法）。
    `intersection_density`: ルート全体の交差点密度（回/km、stop_densityと同じ集約方法）。
    いずれも静的道路属性P1残り。

    `accident_density`: ルート全体の事故密度（件/(km・年)、外部静的データソース T50残作業）。
    domain/accident.py: distance_weighted_accident_density（stop_densityと同じ「合計count÷
    合計distance_km」に収録年数での正規化を加えた集約）。

    `axis_difficulties`: `RouteSegmentDetail.axis_difficulties`（改善計画T309）と同じ
    axis_id→difficulty(0-100)の汎用dictを、ルート全区間に対して1回だけ集約したもの
    （改善計画T402、`merge_axis_difficulties`を`aggregate_segments_into_bins`のビン単位
    ではなく候補全体へ適用）。`car_stress_score`等の個別フィールド群は旧来の軸1対1固定
    設計の名残（改善計画T400節4参照）で、軸スタジオでの軸増減に追従しない。新規の消費
    （BottomSheetのルート全体プロファイル等）はこちらを使うこと。評価できなかった軸は
    キー自体を含めない（segments欠損時は空dict）。
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
    car_stress_score: float | None = None
    bicycle_infra_score: float | None = None
    intersection_density: float | None = None
    accident_density: float | None = None
    total_score: float | None = None
    score_breakdown: list[RouteScoreComponent] | None = None
    segments: list[RouteSegmentDetail] | None = None
    overall_difficulty: float | None = None
    axis_difficulties: dict[str, float] = Field(default_factory=dict)


# 改善計画T11（レビュー指摘M3）: road_graphエンジンのsegmentsはEdge単位（交差点間、
# 1候補あたり150〜230件、30km級）でAPIペイロード・フロント描画コストが嵩むため、
# 約500m単位に集約してから返す。
SEGMENT_BIN_DISTANCE_KM = 0.5


def aggregate_segments_into_bins(
    segments: list[RouteSegmentDetail], bin_distance_km: float = SEGMENT_BIN_DISTANCE_KM
) -> list[RouteSegmentDetail]:
    """連続するEdge単位の`RouteSegmentDetail`を、累積距離`bin_distance_km`単位で
    グルーピングし、1ビン1件の`RouteSegmentDetail`へ集約する（改善計画T11）。

    集約方法（フィールドの性質ごと）:
    - 距離加重平均: gradient_percent/wind_penalty/car_stress/各difficulty系
      （domain/difficulty.py: distance_weighted_difficulty、Noneの区間は除外し
      残りの距離で再正規化。ルート全体の集約と同じ考え方）
    - 距離加重多数決: road_surface_good（カテゴリ値のため平均ではなく、
      ビン内で最も距離の長い値を代表値とする。Noneの区間は除外）
    - 先頭からの引き継ぎ: cumulative_distance_km/estimated_arrival_time/
      start_latitude/start_longitude（ビン開始時点の値）
    - 末尾からの引き継ぎ: end_latitude/end_longitude（ビン終了時点の値）
    - 合計: distance_km
    - 連結: geometry（ビン内の全形状点を、隣接区間の境界点を重複させずに連結）

    最後のビンは`bin_distance_km`未満でも単独のビンとして残す（経路全体の距離を
    正しく合計するため、切り捨てや次ビンへの繰り越しはしない）。`segments`が空なら
    空リストを返す。既存の`RouteSegmentDetail`型のまま返すため、OpenAPI契約・
    フロント型への影響が無い設計（フロントは単にEdge単位からビン単位へ粒度が変わる
    だけで、型自体は変わらない）。
    """
    if not segments:
        return []

    bins: list[list[RouteSegmentDetail]] = []
    current_bin: list[RouteSegmentDetail] = []
    current_bin_distance = 0.0
    for segment in segments:
        current_bin.append(segment)
        current_bin_distance += segment.distance_km
        if current_bin_distance >= bin_distance_km:
            bins.append(current_bin)
            current_bin = []
            current_bin_distance = 0.0
    if current_bin:
        bins.append(current_bin)

    return [_merge_segment_bin(bin_segments) for bin_segments in bins]


def _weighted_mode(pairs: list[tuple[object | None, float]]) -> object | None:
    """(値, 距離)のペア列から、値ごとの合計距離が最大のものを返す（距離加重多数決）。
    Noneの値は候補から除外する。有効な値が1つも無ければNone。"""
    totals: dict[object, float] = {}
    for value, distance in pairs:
        if value is None:
            continue
        totals[value] = totals.get(value, 0.0) + distance
    if not totals:
        return None
    return max(totals.items(), key=lambda item: item[1])[0]


def _concat_segment_geometries(segments: list[RouteSegmentDetail]) -> dict | None:
    coordinates: list[list[float]] = []
    for segment in segments:
        if segment.geometry is None:
            continue
        points = segment.geometry["coordinates"]
        if coordinates and points and coordinates[-1] == points[0]:
            points = points[1:]
        coordinates.extend(points)
    if len(coordinates) < 2:
        return None
    return {"type": "LineString", "coordinates": coordinates}


def merge_axis_difficulties(segments: list[RouteSegmentDetail]) -> dict[str, float]:
    """複数の`RouteSegmentDetail.axis_difficulties`を、axis_idごとに距離加重平均へ
    集約する（改善計画T309）。`_merge_segment_bin`がビン単位（500m）の集約に使うほか、
    `RouteCandidate.axis_difficulties`（改善計画T402）はこの関数を候補の全区間へ1回
    適用するだけで得られる（新しい計算式は不要、`route_generator.py`参照）。
    渡されたsegments群のどの区間にも無いaxis_idは結果にも含めない
    （`RouteSegmentDetail.axis_difficulties`と同じ「データ無しはキーを持たない」規約）。
    """
    axis_ids = {axis_id for s in segments for axis_id in s.axis_difficulties}
    merged: dict[str, float] = {}
    for axis_id in axis_ids:
        value = distance_weighted_difficulty(
            [(s.axis_difficulties.get(axis_id), s.distance_km) for s in segments]
        )
        if value is not None:
            merged[axis_id] = value
    return merged


def _merge_segment_bin(segments: list[RouteSegmentDetail]) -> RouteSegmentDetail:
    first, last = segments[0], segments[-1]
    car_stress_avg = distance_weighted_difficulty(
        [(s.car_stress, s.distance_km) for s in segments]
    )
    return RouteSegmentDetail(
        geometry=_concat_segment_geometries(segments),
        start_latitude=first.start_latitude,
        start_longitude=first.start_longitude,
        end_latitude=last.end_latitude,
        end_longitude=last.end_longitude,
        cumulative_distance_km=first.cumulative_distance_km,
        distance_km=round(sum(s.distance_km for s in segments), 2),
        estimated_arrival_time=first.estimated_arrival_time,
        gradient_percent=distance_weighted_difficulty(
            [(s.gradient_percent, s.distance_km) for s in segments]
        ),
        wind_penalty=distance_weighted_difficulty(
            [(s.wind_penalty, s.distance_km) for s in segments]
        ),
        road_surface_good=_weighted_mode([(s.road_surface_good, s.distance_km) for s in segments]),
        # car_stressは1-5の順序尺度だが、ルート全体の集約（RouteCandidate.car_stress_score）
        # も同じくdistance_weighted_difficultyで連続値として扱っている（既存の前例）ため、
        # ビン単位でも同じ方式で加重平均し最近傍の整数へ丸める。
        car_stress=round(car_stress_avg) if car_stress_avg is not None else None,
        axis_difficulties=merge_axis_difficulties(segments),
        difficulty=distance_weighted_difficulty([(s.difficulty, s.distance_km) for s in segments]),
    )
