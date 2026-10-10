"""Road Graph + 辺基準グラフ探索（A*/一対全Dijkstra、lazy評価）の自前ルーティングエンジン。

`RouteGenerator`が探索を委譲する先。構造と各段の役割は
docs/modules/backend/routing-engine.mdが持つ。ここには、このファイルを変更するときに
破ってはいけないことだけを書く。

- **Road Graphの取得は1リクエストにつき1回だけ。** 候補ごとにbboxで問い合わせず、
  `prepare`が取った1つのグラフを全候補で共有する。
- **Edgeコストはbbox全体ぶんを1回だけnumpyで合成し、探索へは配列のまま渡す。**
  探索中にPythonのコールバックもEdgeごとのオブジェクトも作らない。
- **候補ごとの探索は直列に実行する。** `trace_loop_from_turnaround`が共有のコスト配列を
  一時的に書き換えるため、並列化と両立しない。
- **区間表示は探索と同じコスト配列・スコア行列から引く。** 二重に計算しない。
- **標高・風は探索フェーズで読んだ材料の中にある。** 経路確定後に外部へ取りに行かない。

割り切り: 同一Node間の並行Edgeは`build_lazy_road_graph`が元の行の小さい1本へ解消する
（トポロジはリクエストごとに変わるコストに依らず決める）。そのため並行Edgeの一方だけが0次
フィルタで除外されると、許可される側ではなく行の小さい側が残り、そのNode対が到達不能になりうる。

区間は探索用グラフの番号（`LazyRoadGraph`の区間）、ノードは探索範囲の切り出しの番号で持ち、
区間の文字列の鍵（`edge_key`）は経路の区間の分だけ作る。
"""

import asyncio
import logging
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import NoReturn

import numpy as np

from app.domain.time_zone import JST, as_series_time
from app.domain.traffic import highway_rank
from app.domain.tuning import tuning_value
from app.domain.attributes import ElevationAttribute
from app.domain.errors import RoutingError
from app.domain.evaluation import (
    StaticEdgeScoreMatrix,
    build_static_edge_score_matrix,
    displayed_material_ids,
)
from app.domain.hard_filters import compute_hard_filter_excluded, compute_routable_nodes
from app.domain.leg_costs import LegCostArrays, LegCostComposer, RowValues, material_value_at
from app.domain.gradient import GRADIENT_VALUE_DECIMALS
from app.domain.material_catalog import GRADIENT_PERCENT
from app.domain.route_preference import RoutePreference
from app.domain.geo import (
    bearing_between,
    bearing_between_array,
    compass_degrees,
    compass_label,
)
from app.domain.graph import LeanEdge, edge_key, node_key, parse_edge_key
from app.domain.region import BoundingBox, bbox_covering_points
from app.domain.rain import StationRainMaterials, rain_material_columns
from app.domain.road_network import RoadSlice, edge_row_of, elevation_attribute, material_arrays_of
from app.domain.route import (
    Coordinates,
    DensityScoreInput,
    RouteCandidate,
    RouteSegmentDetail,
    DISTANCE_KM_DECIMALS,
    aggregate_segments_into_bins,
    concat_edge_geometries,
    merge_material_category_shares,
    reverse_elevation_by_edge,
    route_axis_raw_values,
    route_elevation_gain,
)
from app.domain.route_search import (
    DETOUR_RATIO_MIN_ROAD_M,
    LOOP_MAX_OVERLAP_RATIO,
    MAX_SNAP_CORRECTION_KM,
    TURNAROUND_MAX_OVERLAP_RATIO,
    TURNAROUND_RELAXED_OVERLAP_RATIO,
    VIA_NODE_MAX_OVERLAP_RATIO,
    VIA_NODE_RELAXED_OVERLAP_RATIO,
    EdgePassage,
    alternative_via_nodes,
    best_first,
    heuristic_seconds,
    leg_duration_hours,
    leg_of_edge_by_half,
    median_detour_ratio,
    order_by_bearing_spread,
    pick_better_candidate,
    rank_by_pareto_layers,
    retrace_penalized,
    reverse_leg_assignment,
    relay_band,
    ring_closeness_m,
    route_passages,
    straight_distances_m,
    turnaround_ring_m,
    turnaround_separation,
)
from app.domain.routing import (
    LazyRoadGraph,
    NodeSpatialIndex,
    SearchGraphStatics,
    build_lazy_road_graph,
    build_node_spatial_index,
    build_search_graph_statics,
    current_turn_cost,
    TurnExpandedStructure,
    add_terminal_candidate,
    build_turn_expanded_structure,
    build_turn_expanded_tree,
    combine_forward_backward_at_nodes,
    edge_bearings,
    edge_index_between,
    largest_strongly_connected_nodes,
    lengths_by_physical_segment,
    overlap_ratio,
    physical_overlap_ratio,
    select_diverse_by_overlap,
    snap_to_accessible_node,
    turn_expanded_path_edge_indices,
    turn_expanded_path_from_state,
    turn_expanded_path_from_state_to_source,
    turn_expanded_shortest_path,
)
from app.domain.wind import (
    cruise_hours,
    detour_ratio_or_default,
    estimate_passage_hours,
    is_usable_detour_ratio,
    kmh_to_ms,
    reached_or_estimated_hours,
    straight_line_hours,
)
from app.infrastructure import detour_ratio_cache
from app.infrastructure.debug_log import log_throttled_warning
from app.services.graph_service import GraphService
from app.domain.loop_routing import LoopTurnaround, TracedLoop
from app.services.weather_service import WeatherService

# Road Graphを取得するbboxは、起点と置いた点の外接矩形に、自由に選ぶ部分の半径とこのマージンを足したもの。
# 実際の道なりは直線距離の外接矩形からはみ出ることが多い（川・線路等を迂回する等）ため、
# 探索が失敗しない程度の余裕を持たせる。半径に比例させつつ、最低値を設ける。
_BBOX_MARGIN_RATIO = 0.3
_BBOX_MARGIN_MIN_KM = 2.0

# 一対全探索のコスト上限に掛ける余裕。Edge単位の丸めの積み上がりで上限ぎりぎりのNodeを
# 取りこぼさないため。
_COST_LIMIT_SLACK = 1.01
# ランキング上位から間引き判定にかけるリングNode数の上限（往路の経路復元コストの上限）。
_MAX_RING_CANDIDATES_EXAMINED = 4000
# ランキング上位から間引き判定にかけるvia-node候補数の上限（_MAX_RING_CANDIDATES_EXAMINEDと
# 同じ役割）。目的地ルートのbboxは周回より小さいため周回より小さい上限にする。
_MAX_VIA_NODE_CANDIDATES_EXAMINED = 2000

logger = logging.getLogger("ridecompass.graph")


@dataclass
class _RoadGraphContext:
    """prepareで構築し、1回の生成の前段・仕上げ・評価（`evaluate_loops`）で共有するリクエスト単位の状態。"""

    # 探索範囲の切り出し。ノードの番号・区間の元の行はこれが決める。
    road: RoadSlice
    # 起点のノード番号（`road`の切り出しの番号）。
    origin_node: int
    # 1リクエスト内で繰り返す最寄りNodeの探索（prepareの起点・前段の
    # 各経由地・仕上げの目的地）を都度線形探索せず使い回すための索引
    # （domain/routing.py参照）。
    node_index: NodeSpatialIndex
    # 置いた点を寄せてよいNode（ノード番号順の真偽。`domain/routing.py: largest_strongly_connected_nodes`）。
    # 起点・経由地・目的地をどれもこの中へ寄せるので、置いた点どうしは互いに行き来できる。
    accessible: np.ndarray
    # 探索用グラフ（区間は番号、domain/routing.py: LazyRoadGraph参照）。
    lazy_graph: LazyRoadGraph
    # レグごとのコスト配列を合成する部品と、合成済みのレグ配列（前段の区間ごとのレグのあとに、仕上げの往路[最後の
    # 固定点から離れるレグ]と帰り[終点へ向かうレグ]。経由地が無ければ0=往路・1=帰り）。
    # `TracedLoop.leg_of_edge`がこの添字を指す。
    composer: LegCostComposer
    legs: list[LegCostArrays]
    # 周回の復路レグ・目的地ルートの後ろ向き木の基準点に使う起点座標。
    origin: Coordinates
    # A*のヒューリスティック（`straight_distances_m`）を、レグごとの目的地に対して
    # numpyで1回だけベクトル計算するための、ノード番号順の緯度・経度配列。
    node_lat: np.ndarray
    node_lon: np.ndarray
    # 一対全最短経路木用のCSR構造＋Edge実距離配列（domain/routing.py: SearchGraphStatics参照）。
    statics: SearchGraphStatics
    # 状態＝有向Edge・辺＝ターンの遷移構造（`statics.csr`から導く。起点にもコストにも
    # 依存しないためリクエスト内で共有する）。
    turn_structure: TurnExpandedStructure
    # 探索範囲を覆うタイル集合。学習した迂回率の鍵に使う。
    tile_set: frozenset[tuple[int, int, int]]
    # 帰りの探索（中継点→終点）のA*ヒューリスティック配列（終点のノード番号→配列）。終点は1回の生成で
    # 固定のため、終点ごとに1回だけ計算し全候補で共有する（初回の帰りの探索時に遅延構築）。
    end_estimates: dict[int, list[float]] = field(default_factory=dict)
    # 仕上げが目的地を一番近いNodeでなく出て戻れる最寄りNodeへ寄せた場合の
    # 実際の座標（寄せ直しが無ければNone）。RouteGenerator.last_no_candidates_reasonと同じ
    # side channel——Protocolの戻り値型（list[TracedLoop]）を変えずにRouteGenerator側へ
    # 伝える。
    destination_correction: Coordinates | None = None


def _static_score_matrix(road: RoadSlice, rain: StationRainMaterials | None) -> tuple[StaticEdgeScoreMatrix, int]:
    """切り出した区間の材料に、区間の中点に最も近い雨量計の観測（雨の材料）を足して静的スコア行列を組む。
    戻り値の2つ目は雨の材料を引くのにかかった時間（ms）。"""
    materials = material_arrays_of(road)
    started = time.monotonic()
    observed = {} if rain is None else rain_material_columns(rain, materials.mid_lat, materials.mid_lon)
    rain_ms = round((time.monotonic() - started) * 1000)
    return build_static_edge_score_matrix(materials, observed), rain_ms


@dataclass
class _SearchGraph:
    """`prepare`が組む「bboxに対する探索用グラフ＋材料一式」。
    0次ハードフィルタ等の探索コスト算出の組み立ては`_build_search_graph`1箇所にある。
    """

    road: RoadSlice
    lazy_graph: LazyRoadGraph
    # bboxを覆うタイル集合（学習した迂回率の鍵）。
    tile_set: frozenset[tuple[int, int, int]]
    # _RoadGraphContextと同じ意味（フィールドdocstring参照）。`outbound`は基準点（起点側の
    # 座標）から離れていくレグとして合成済みの配列。
    composer: LegCostComposer
    outbound: LegCostArrays
    node_lat: np.ndarray
    node_lon: np.ndarray
    # 0次フィルタ除外配列（`compute_hard_filter_excluded`、切り出した区間の順。cost_arrayをinfに
    # するのに使ったのと同じ配列）。routable Node判定にこの配列をそのまま使い回す。
    hard_filter_excluded: np.ndarray


@dataclass(frozen=True)
class _TurnaroundData:
    """`LoopTurnaround.data`（本エンジン固有）: 中継点（折返し点）のノード番号と、最後の固定点からの一対全木上の
    往路（区間の番号列）、向かう終点のノード番号。`trace_loop_from_turnaround`が帰りの探索に使う。"""

    node: int
    outbound_edge_indices: list[int]
    outbound_length_m: float
    end_node: int
    # 終点が出発地か（周回）。周回だけが方位の名前を持つ。
    closes: bool
    reversible: bool


@dataclass(frozen=True)
class FixedLegs:
    """前段（`RoadGraphEngine.trace_fixed_points`）の結果: 出発地から置いた経由地を置いた順に、区間ごとの最短でつないだ道。

    仕上げの戦略はここから続ける。戦略層は中身を読まず、受け取ったまま仕上げへ渡す。
    """

    # 区間（出発地→1つ目の経由地、…）ごとの、探索用グラフの区間の番号列。添字が`_RoadGraphContext.legs`の添字になる。
    segments: list[list[int]]
    # 出発地と置いた経由地のノード番号（置いた順）。最後が最後の固定点。
    nodes: list[int]
    # 前段の道の実距離（m）。
    length_m: float

    @property
    def last_node(self) -> int:
        return self.nodes[-1]

    @property
    def edges(self) -> list[int]:
        """前段の道の区間の番号列（区間をつないだもの）。"""
        return [index for segment in self.segments for index in segment]

    @property
    def leg_of_edge(self) -> list[int]:
        return [leg_index for leg_index, segment in enumerate(self.segments) for _ in segment]

    @property
    def reversible(self) -> bool:
        """出発地へ戻る経路を逆に回っても、置いた経由地を置いた順に通るか（経由地が1つ以下）。"""
        return len(self.segments) <= 1


class RoadGraphEngine:
    """評価条件は解決済みの値だけを受け取る（既定を持たない）。組み立ては
    `services/route_generation_setup.py: assemble_route_generation_setup`だけが行う。"""

    def __init__(
        self,
        graph_service: GraphService,
        weather_service: WeatherService,
        *,
        route_preference: RoutePreference,
        penalty_strength: float,
        max_average_grade_percent: float | None,
        hard_filters: frozenset[str],
        assumed_speed_kmh: float,
    ):
        self._graph_service = graph_service
        # 仮定巡航速度（km/h、リクエスト単位で上書き可）。各Edgeの通過予定時刻・区間の
        # 到達予想時刻・所要時間の算出に使う。
        self._assumed_speed_kmh = assumed_speed_kmh
        self._weather_service = weather_service
        self._route_preference = route_preference
        # コスト式`所要時間 × (1 + P × difficulty/100)`のP＝「主観 vs 時間」の換算レート。
        self._penalty_strength = penalty_strength
        # 0次ハードフィルタの勾配しきい値（%、None＝除外しない）。
        # `domain/hard_filters.py: compute_hard_filter_excluded`参照。
        self._max_average_grade_percent = max_average_grade_percent
        # 有効にする0次ハードフィルタ名の集合。
        self._hard_filters = hard_filters
        # 交差点でのターンの費用（秒）。較正値のため、組み立てた時点の値で1回の生成を通す。
        self._turn_cost = current_turn_cost()

    async def _build_search_graph(
        self, bbox: BoundingBox, origin: Coordinates, now: datetime
    ) -> _SearchGraph | None:
        """bboxに対する探索用グラフ（lazy_graph）＋bbox全体ぶんのコスト配列を構築する。
        風の時別予報が無いときの風（出発時点の値）と、区間を通る時刻の昼夜は`origin`（起点）の地点で決める。
        時別予報は`bbox`を覆う格子点ごとに引く。

        雨の材料は、出発時刻ではなく今の観測（地図の雨と同じ値）。観測の履歴が無い・古いときは欠損のまま組み、
        雨の材料を読む軸はその生成で「データなし」になる。

        `GraphService.get_search_slice`が切り出した区間の材料と雨の観測から`StaticEdgeScoreMatrix`
        （静的Edge×公開軸スコア行列）を組み、動的軸（風、`evaluate_dynamic_axis_arrays`）と重み
        ベクトルを適用してコスト配列を**bbox全体ぶん1回だけ**numpyで合成する。探索本体へは
        合成済みのnumpy配列をそのまま渡すだけにする。
        """
        stage_started = time.monotonic()
        built = await self._graph_service.get_search_slice(bbox)
        slice_ms = round((time.monotonic() - stage_started) * 1000)
        if built is None:
            return None
        road, tile_set = built
        if road.edge_count == 0:
            return None

        weather_started = time.monotonic()
        departure_wind = await self._weather_service.get_departure_wind(origin)
        # 探索範囲を覆う格子点ごとの時別風予報（MSMのローカルファイルから読む。外部API呼び出しは無い）。
        wind_series = await self._weather_service.get_wind_forecast_lattice(bbox)
        rain = await self._weather_service.get_station_rain_materials(datetime.now(JST))
        weather_ms = round((time.monotonic() - weather_started) * 1000)
        if rain is None:
            log_throttled_warning("engine:rain-materials", "雨の観測の履歴が無いか古いため、雨の材料を欠損として探索範囲を組む")

        materials_started = time.monotonic()
        score_matrix, rain_ms = await asyncio.to_thread(_static_score_matrix, road, rain)
        materials_ms = round((time.monotonic() - materials_started) * 1000)
        # 通過予定時刻の基準（出発時刻）。
        start = as_series_time(now)

        # --- bbox全体ぶんのコスト配列の合成（レグごと。まず起点から離れる往路レグ） ---
        cost_started = time.monotonic()
        hard_filter_excluded = compute_hard_filter_excluded(
            score_matrix.hard_filter_flags,
            score_matrix.gradient_percent, self._hard_filters, self._max_average_grade_percent,
        )

        graph_started = time.monotonic()
        lazy_graph = await asyncio.to_thread(build_lazy_road_graph, road.edge_from, road.edge_to, road.node_count)
        graph_ms = round((time.monotonic() - graph_started) * 1000)

        # 迂回率は同じ探索範囲で前回の往路木から学習した値があればそれを使う（無ければ既定値）。
        learned_detour_ratio = detour_ratio_cache.get_detour_ratio(tile_set)
        composer = LegCostComposer(
            score_matrix, self._route_preference.weights, self._penalty_strength, hard_filter_excluded, departure_wind,
            wind_series, start, self._assumed_speed_kmh, lazy_graph.edge_rows,
            detour_ratio=detour_ratio_or_default(learned_detour_ratio),
            twilight_origin=origin,
        )
        outbound = composer.compose("outbound", origin, 0.0, +1)
        cost_ms = round((time.monotonic() - cost_started) * 1000) - graph_ms
        # 重み付き軸がすべてNaNのEdge比率（探索コストはbbox内平均difficultyで補完される。
        # 実際の発生頻度を把握するためのサマリ）。
        missing_axis_mask = np.isnan(outbound.difficulty_array)
        missing_axis_distance_ratio = float(
            score_matrix.distance_m[missing_axis_mask].sum() / float(score_matrix.distance_m.sum())
        )

        total_ms = round((time.monotonic() - stage_started) * 1000)
        logger.info(
            "_build_search_graph edges=%d nodes=%d slice_ms=%d weather_ms=%d materials_ms=%d rain_ms=%d cost_ms=%d "
            "graph_ms=%d total_ms=%d rain_hour=%s time_varying=%s speed_kmh=%.1f detour_ratio=%.2f(%s) "
            "missing_axis_edges=%d missing_axis_distance_ratio=%.3f",
            road.edge_count, road.node_count, slice_ms, weather_ms, materials_ms, rain_ms, cost_ms, graph_ms, total_ms,
            "none" if rain is None else rain.latest_hour.strftime("%Y-%m-%dT%H"),
            composer.time_varying, self._assumed_speed_kmh, composer.detour_ratio,
            "learned" if learned_detour_ratio is not None else "default",
            int(missing_axis_mask.sum()), missing_axis_distance_ratio,
        )

        return _SearchGraph(
            road=road,
            lazy_graph=lazy_graph,
            tile_set=tile_set,
            composer=composer,
            outbound=outbound,
            node_lat=road.node_lat,
            node_lon=road.node_lon,
            hard_filter_excluded=hard_filter_excluded,
        )

    async def _build_search_structures(
        self, search: _SearchGraph
    ) -> tuple[NodeSpatialIndex, np.ndarray, SearchGraphStatics, TurnExpandedStructure]:
        """最寄りNodeの索引・置いた点を寄せてよいNode・CSR・ターン構造を組む。

        索引の候補は実際に経路探索可能な（Hard Constraint通過後も区間が1本以上残る）Nodeに
        絞る。絞らないと、幹線道路（highway=trunk等）にしか接続していない地理的最近傍Node
        （駅前が国道の交差点に直接面する場所が実例）が選ばれ、そこがHard Constraint除外後の
        グラフ上では孤立点になるため、すべての折返し点・経由地への探索が"no path found"で失敗する。
        区間が残っていても出て戻れないNode（孤立した小さな塊・一方通行の袋）は、置いた点を寄せるときに
        外す（`domain/routing.py: snap_to_accessible_node`）。
        """
        started = time.monotonic()
        road = search.road
        routable = compute_routable_nodes(road.edge_from, road.edge_to, search.hard_filter_excluded, road.node_count)
        node_index = await asyncio.to_thread(build_node_spatial_index, search.node_lat, search.node_lon, routable)
        statics = build_search_graph_statics(search.lazy_graph, search.composer.distance_m)
        accessible = await asyncio.to_thread(
            largest_strongly_connected_nodes, statics.csr, ~search.hard_filter_excluded[search.lazy_graph.edge_rows],
        )
        index_ms = round((time.monotonic() - started) * 1000)
        turn_started = time.monotonic()
        turn_structure = await asyncio.to_thread(self._build_turn_structure, search, statics)
        logger.info(
            "prepare structures edges=%d states=%d transitions=%d index_ms=%d turn_ms=%d",
            road.edge_count, turn_structure.state_count, len(turn_structure.target_state),
            index_ms, round((time.monotonic() - turn_started) * 1000),
        )
        return node_index, accessible, statics, turn_structure

    def _build_turn_structure(self, search: _SearchGraph, statics: SearchGraphStatics) -> TurnExpandedStructure:
        """状態＝有向区間の遷移構造。信号の有無・集まる道の最大階級はノードの事前集計列、
        区間の道路階級は`highway`の語彙から引く（`domain/traffic.py: highway_rank`）。"""
        road, lazy_graph = search.road, search.lazy_graph
        network = road.network
        rank_of_code = np.array([highway_rank(highway) for highway in network.highway_vocab], dtype=np.int64)
        edge_rank = rank_of_code[network.edge_highway[road.rows[lazy_graph.edge_rows]]]
        return build_turn_expanded_structure(
            statics.csr, lazy_graph,
            edge_bearings(lazy_graph, search.composer.bearing_deg, search.node_lat, search.node_lon),
            edge_rank, self._turn_cost,
            np.asarray(network.node_has_signals[road.nodes], dtype=bool),
            np.asarray(network.node_max_rank[road.nodes], dtype=np.int64),
        )

    async def prepare(
        self,
        origin: Coordinates,
        points: list[Coordinates],
        radius_km: float,
        now: datetime,
    ) -> _RoadGraphContext | None:
        """`points`は置いた点（経由地・目的地）、`radius_km`は自由に選ぶ部分が届く見込みの半径（置いた点だけを
        つなぐなら0）。出発地と置いた点を覆う矩形をこの半径とマージンだけ広げるので、中継点がどの方位に選ばれても
        この1回の取得で足りる。

        起点は出て戻れるNodeへ寄せ（`domain/routing.py: snap_to_accessible_node`）、寄せられなければ`RoutingError`。"""
        # nowは出発時刻。区間ごとの通過時刻（風・昼夜）はここからの経過で決まる。
        margin_km = max(_BBOX_MARGIN_MIN_KM, radius_km * _BBOX_MARGIN_RATIO)
        bbox = bbox_covering_points([origin, *points], radius_km + margin_km)

        search = await self._build_search_graph(bbox, origin, now)
        if search is None:
            return None
        node_index, accessible, statics, turn_structure = await self._build_search_structures(search)
        snapped = snap_to_accessible_node(node_index, accessible, origin, MAX_SNAP_CORRECTION_KM)
        if snapped is None:
            raise RoutingError("no accessible node near origin")
        origin_node, moved = snapped
        if moved:
            logger.warning(
                "prepare moved origin to nearest accessible node lat=%.2f lon=%.2f",
                float(search.node_lat[origin_node]), float(search.node_lon[origin_node]),
            )

        return _RoadGraphContext(
            road=search.road,
            origin_node=origin_node,
            node_index=node_index,
            accessible=accessible,
            lazy_graph=search.lazy_graph,
            composer=search.composer,
            legs=[search.outbound],
            origin=origin,
            node_lat=search.node_lat,
            node_lon=search.node_lon,
            statics=statics,
            turn_structure=turn_structure,
            tile_set=search.tile_set,
        )

    def _trace_leg(
        self, context: _RoadGraphContext, leg_index: int, from_node: int, to_node: int, cumulative_m: float,
    ) -> list[int] | None:
        """置いた点どうしを結ぶ区間を1本、A*で探す。区間0は`prepare`が合成済みの往路レグそのもので、
        ほかは区間の起点を基準点に、それまでの実距離ぶんの経過時間に置いて合成し`context.legs`へ足す。

        A*のヒューリスティックは区間ごとに目的地が変わるため、区間ごとにnumpyで1回だけ計算し直す。
        """
        if leg_index == 0:
            leg = context.legs[0]
        else:
            leg = context.composer.compose(
                f"leg{leg_index}", _node_coordinates(context, from_node),
                cruise_hours(cumulative_m / 1000, context.composer.speed_kmh), +1,
            )
            context.legs.append(leg)
        return turn_expanded_shortest_path(
            context.turn_structure, leg.cost_bins_lazy,
            heuristic_seconds(
                straight_distances_m(context.node_lat, context.node_lon, to_node), context.composer.speed_kmh,
            ),
            _origin_states(context.statics, from_node),
            to_node,
            leg.travel_bins_lazy, leg.bin_seconds,
        )

    async def trace_fixed_points(self, context: _RoadGraphContext, waypoints: list[Coordinates]) -> FixedLegs:
        """前段: 出発地から、置いた経由地を置いた順に区間ごとのA*で結ぶ。経由地が無ければ出発地で止まる（区間は無い）。

        起点は`prepare`がスナップ済みのNodeをそのまま使い、経由地はここで起点と同じく出て戻れるNodeへスナップする。
        """
        if not waypoints:
            return FixedLegs(segments=[], nodes=[context.origin_node], length_m=0.0)
        node_sequence = [context.origin_node]
        for point in waypoints:
            snapped = _snap(context, point)
            if snapped is None:
                raise RoutingError("could not snap waypoints to road graph")
            node_sequence.append(snapped[0])

        trace_started = time.monotonic()
        context.legs = context.legs[:1]
        segments: list[list[int]] = []
        cumulative_m = 0.0
        for leg_index, (from_node, to_node) in enumerate(zip(node_sequence, node_sequence[1:])):
            segment = self._trace_leg(context, leg_index, from_node, to_node, cumulative_m)
            if segment is None:
                raise RoutingError("no path found between waypoints")
            segments.append(segment)
            cumulative_m += float(context.statics.edge_length_m[segment].sum())
        logger.info("trace_fixed_points legs=%d wall_ms=%d", len(segments), round((time.monotonic() - trace_started) * 1000))
        return FixedLegs(segments=segments, nodes=node_sequence, length_m=cumulative_m)

    async def select_loop_turnarounds(
        self,
        context: _RoadGraphContext,
        fixed: FixedLegs,
        destination: Coordinates | None,
        distance_km: float,
        distance_tolerance_km: float,
        pool_size: int,
    ) -> list[LoopTurnaround]:
        """距離ありの中継点（折返し点）候補を、最後の固定点からの往路の軸的な良さの順に最大`pool_size`件選ぶ。

        1. 最後の固定点（経由地が無ければ起点）からの一対全最短経路木（`domain/routing.py: build_turn_expanded_tree`、
           軸重み付きコスト）を1回だけ求める。前段で走った道（同じNode対の逆向きを含む）には帰りと同じ罰を置く。
           探索はコスト上限（帯の上限の距離を最低速度で秒へ直し×(1+P)。帯の中のNodeを取りこぼさない上界）で打ち切る。
        2. 帯に入るNodeを選ぶ。終点からの逆向きの木で中継点から終点までの長さを取り、全長の見込み（前段＋往路＋帰り）が
           目標±許容に入るNode（`domain/route_search.py: relay_band`）。経由地の無い周回は帰りの最短を往路の長さで
           代え、木に沿った往路の**実距離**が周回のリング（`domain/route_search.py: turnaround_ring_m`）に入るNodeにする。
           どちらも最短実距離ではなく軸コスト最適経路の実距離で定義する——重みを極端に振った設定ほど往路が遠回りする
           ため、最短実距離基準だと往路だけで目標の半分を超え距離フィルタで全滅する。
        3. 帯の中心からのずれ・往路の難易度のパレート層の順に並べる（`rank_by_pareto_layers`）。
        4. 上位から順に、既採用候補と往路の重複率が`TURNAROUND_MAX_OVERLAP_RATIO`を
           超えるもの・`MIN_TURNAROUND_SEPARATION_KM`より近いものを飛ばして`pool_size`件
           採る（同一コリドー上の隣接Nodeが上位を独占し似た周回が並ぶのを防ぐ）。
           埋まらなければ閾値を`TURNAROUND_RELAXED_OVERLAP_RATIO`へ緩めてやり直す。

        `context.legs`は前段のレグのあとに、往路（最後の固定点から離れるレグ）と帰り（終点へ向かうレグ）を置く。
        """
        statics = context.statics
        leg_index = len(fixed.segments)
        start_node = fixed.last_node
        fixed_m = fixed.length_m
        remaining_km = distance_km - fixed_m / 1000
        closes = destination is None
        if destination is None:
            end_node = context.origin_node
            end_point = context.origin
        else:
            end_node = _snap_destination(context, destination)
            if end_node is None:
                return []
            end_point = context.destination_correction or destination
        # 往路レグを、見込み所要時間（残りの距離の半分÷巡航速度）ぶんの時刻ビンで組み直す。
        # 木は出発からの経過時間を持ち回れるため、風を推定ではなく実際の経過時間で引ける。
        outbound = context.composer.compose(
            "outbound" if leg_index == 0 else f"leg{leg_index}",
            context.origin if leg_index == 0 else _node_coordinates(context, start_node),
            cruise_hours(fixed_m / 1000, context.composer.speed_kmh), +1,
            duration_hours=leg_duration_hours(remaining_km, context.composer.speed_kmh),
        )
        context.legs = [*context.legs[:leg_index], outbound]
        traveled = _traveled_columns(context, fixed.edges)

        backward_tree = None
        if closes and leg_index == 0:
            # 経由地の無い周回は、出発地からの往路と出発地への帰りの最短が同じ2点を結ぶので、帰りの最短を往路の長さで
            # 代えられる（リング）。逆向きの木を求めない。
            ring_lower_m, ring_upper_m, ring_center_m = turnaround_ring_m(distance_km, distance_tolerance_km)
            outbound_upper_m = ring_upper_m
        else:
            # 帰りレグ: 終点へ向かうレグとして、全長の目標ぶんの所要時間を終点への到着予定時刻に置く。
            inbound = self._compose_inbound(context, end_point, distance_km, remaining_km)
            context.legs = [*context.legs[:leg_index + 1], inbound]
            backward_tree = await asyncio.to_thread(
                build_turn_expanded_tree,
                context.turn_structure, _avoiding_traveled(inbound.cost_lazy, traveled), statics.edge_length_m,
                _destination_states(context.turn_structure, end_node), statics.csr.node_count,
                reverse=True, edge_seconds=inbound.travel_seconds_lazy,
            )
            outbound_upper_m = (distance_km + distance_tolerance_km) * 1000 - fixed_m
        if outbound_upper_m <= 0:
            logger.info("select_turnarounds fixed_km=%.1f exceeds the target", fixed_m / 1000)
            return []
        # コストは秒（体感の所要時間）のため、上限も帯の上限の距離を秒へ直して決める。
        # 走行モデルが出しうる最も遅い速度（押して歩く）で割ることで、帯の中のNodeを
        # 取りこぼさない上界になる（`cost <= 所要時間 × (1+P)`かつ
        # `所要時間 <= 距離 ÷ 最低速度`）。走った道の罰はコストを増やすだけなので、上界のまま。
        cost_limit = (
            outbound_upper_m / kmh_to_ms(tuning_value("speed.walking_kmh"))
            * (1.0 + max(self._penalty_strength, 0.0)) * _COST_LIMIT_SLACK
        )

        tree_started = time.monotonic()
        tree = await asyncio.to_thread(
            build_turn_expanded_tree,
            context.turn_structure, _avoiding_traveled(outbound.cost_bins_lazy, traveled), statics.edge_length_m,
            _origin_states(statics, start_node), statics.csr.node_count,
            cost_limit=cost_limit, edge_seconds=outbound.travel_bins_lazy,
            bin_seconds=outbound.bin_seconds,
        )
        tree_ms = round((time.monotonic() - tree_started) * 1000)

        length = tree.node_length_m
        if backward_tree is None:
            in_ring = (length >= ring_lower_m) & (length <= ring_upper_m)
            band_km = (ring_lower_m / 1000, ring_upper_m / 1000)
        else:
            in_ring, total_closeness_m = relay_band(
                fixed_m, length, backward_tree.node_length_m, distance_km, distance_tolerance_km,
            )
            in_ring[end_node] = False
            band_km = ((distance_km - distance_tolerance_km), (distance_km + distance_tolerance_km))
        in_ring[start_node] = False
        ring = np.flatnonzero(in_ring)
        if len(ring) == 0:
            logger.info(
                "select_turnarounds ring_nodes=0 reached=%d ring_km=[%.1f,%.1f] fixed_km=%.1f tree_ms=%d",
                int(np.isfinite(tree.node_cost).sum()), band_km[0], band_km[1], fixed_m / 1000, tree_ms,
            )
            return []

        ring_length = length[ring]
        # 迂回率（道なり距離÷直線距離）の実測中央値を学習値として保存する。周回の合成自体は
        # 使わない（レグはビンの開始時刻で評価する）が、直線距離を走行時間へ直す係数として
        # 目的地ルートの到着予定時刻が読む。
        detour_ratio_median = _median_detour_ratio(context, start_node, ring, ring_length)
        _learn_detour_ratio(context, detour_ratio_median)
        if backward_tree is None:
            # 帰りレグ: 出発地へ向かうレグとして、周回の総所要時間（目標距離÷仮定速度）を出発地への
            # 到着予定時刻に置いて合成する（距離フィルタが目標±許容を強制するため定数扱いできる）。
            inbound = self._compose_inbound(context, end_point, distance_km, remaining_km)
            context.legs = [*context.legs[:leg_index + 1], inbound]
            closeness_key = ring_closeness_m(ring_length, ring_center_m)
        else:
            closeness_key = total_closeness_m[ring]
        ranking = rank_by_pareto_layers(
            ring, closeness_key, tree.node_cost[ring], tree.node_seconds[ring], self._penalty_strength,
            max_items=pool_size, max_examined=_MAX_RING_CANDIDATES_EXAMINED, tie_by_distance=True,
        )
        order = ranking.order
        ranked = ring[order]
        # 方位／近接判定用平面座標は、以降で実際に引かれうる`ranked`
        # （上限_MAX_RING_CANDIDATES_EXAMINED件）ぶんだけ用意する。
        ranked_list = ranked.tolist()
        # 同点（層と丸めた難易度が等しい）候補はグループとして渡し、グループ内の試行順は
        # 「採用済み候補との方位角距離の最小値が最大」（最遠点貪欲法、方位は生成機構ではなく
        # 同点タイブレーク専用）で採用のたびに決め直す。グループ自体の順序（主キー）・
        # 同点でない候補間の順序は変えない。
        origin_node = _node_coordinates(context, context.origin_node)
        bearing_by_node = dict(zip(
            ranked_list,
            bearing_between_array(origin_node, context.node_lat[ranked], context.node_lon[ranked]).tolist(),
        ))
        closeness_by_node = dict(zip(ranked_list, closeness_key[order].tolist()))
        tie_groups = ranking.tie_groups(ring)

        def prefer(remaining: Sequence[int], selected: list[int]) -> list[int]:
            return order_by_bearing_spread(remaining, selected, bearing_by_node, closeness_by_node)

        outbound_cache: dict[int, list[int] | None] = {}

        def outbound_edges(node_index: int) -> list[int] | None:
            if node_index not in outbound_cache:
                outbound_cache[node_index] = turn_expanded_path_edge_indices(tree, node_index)
            return outbound_cache[node_index]

        far_enough = turnaround_separation(
            ranked_list, context.node_lat[ranked], context.node_lon[ranked],
            float(context.node_lat[context.origin_node]),
        )

        # 閾値を昇順に渡すと、埋まらなかったときの緩和までを1回の呼び出しで行う。
        selected = select_diverse_by_overlap(
            [], outbound_edges, statics.edge_length_m,
            [TURNAROUND_MAX_OVERLAP_RATIO, TURNAROUND_RELAXED_OVERLAP_RATIO], pool_size, far_enough,
            tie_groups=tie_groups, prefer=prefer,
        )

        turnarounds: list[LoopTurnaround] = []
        for node_index in selected:
            edges = outbound_edges(node_index)
            if not edges:
                continue
            bearing = compass_degrees(bearing_between(origin_node, _node_coordinates(context, node_index)))
            turnarounds.append(
                LoopTurnaround(
                    bearing=bearing,
                    data=_TurnaroundData(
                        node=node_index, outbound_edge_indices=edges,
                        outbound_length_m=float(length[node_index]), end_node=end_node,
                        closes=closes, reversible=closes and fixed.reversible,
                    ),
                )
            )
        logger.info(
            "select_turnarounds ring_nodes=%d examined=%d selected=%d pool=%d "
            "ring_km=[%.1f,%.1f] fixed_km=%.1f detour_ratio_median=%.2f tree_ms=%d total_ms=%d",
            len(ring), len(ranked_list), len(turnarounds), pool_size,
            band_km[0], band_km[1], fixed_m / 1000, detour_ratio_median, tree_ms,
            round((time.monotonic() - tree_started) * 1000),
        )
        return turnarounds

    def _compose_inbound(
        self, context: _RoadGraphContext, end_point: Coordinates, distance_km: float, remaining_km: float,
    ) -> LegCostArrays:
        """距離ありの帰りレグ: 終点を基準点に、全長の目標ぶんの所要時間（目標距離÷仮定速度）を終点への到着予定時刻に置く
        （距離フィルタが目標±許容を強制するため定数扱いできる）。"""
        return context.composer.compose(
            "inbound", end_point, cruise_hours(distance_km, context.composer.speed_kmh), -1,
            duration_hours=leg_duration_hours(remaining_km, context.composer.speed_kmh),
        )

    async def select_via_nodes(
        self, context: _RoadGraphContext, fixed: FixedLegs, destination: Coordinates | None, max_routes: int
    ) -> list[TracedLoop]:
        """距離なしの仕上げ: 最後の固定点（経由地が無ければ起点）から終点（`destination`、Noneなら出発地）までの区間を、
        via-node方式で互いに異なる道に`max_routes`件まで選び、前段の道とつないで返す。代わりの道は最後の区間でだけ探す
        ——置いた点までは全候補で同じで、最後だけが違う（区間ごとに代わりを探すと組み合わせが増える）。
        周回のretraceペナルティ付き復路探索（`trace_loop_from_turnaround`）とは異なり、最後の固定点からの前向き木・
        終点からの後ろ向き木（遷移の向きを反転した辺基準の木）を各1回求めれば、どのNode（via-node）を経由する経路も
        両木の経路復元だけで確定するため、候補ごとの追加探索が発生しない。前段で走った道（同じNode対の逆向きを含む）には、
        両方の木で帰りと同じ罰を置く。

        1. 全Nodeについて経由路長`len_f+len_b`・合成コスト`cost_f+cost_b`をベクトル計算し、
           合成コスト最小のNode（"最良路"）の長さの`ALTERNATIVE_MAX_STRETCH`倍以内の
           Nodeだけを候補にする。
        2. 平均difficulty`(合成コスト/経由路長-1)/P`昇順に並べる。ただし最良路のNodeは常に
           先頭へ回す——合成コスト最小であっても、伸び率の許す範囲でより平均difficultyの
           低い経路が他に存在すれば難易度順ではそちらが上位に来うるため、「最良路は必ず
           結果に含まれる」をランキングとは独立に保証する。
        3. `select_diverse_by_overlap`で、前向き経路・後ろ向き経路が同じEdgeを共有する
           Node（行って戻る形になり経路として成立しない）を除外しつつ、採用済み候補との
           重複率（最後の区間どうし）が閾値超のものを飛ばして`max_routes`件採る。

        目的地は起点・経由地と同じく出て戻れるNodeへスナップするので、走り出す点からの前向き木は必ず届く。
        終点が出発地なら`prepare`がスナップ済みのNodeをそのまま使う（起終点を同じNodeに揃えないと周回が閉じない）。
        """
        leg_index = len(fixed.segments)
        start_node = fixed.last_node
        start_point = context.origin if leg_index == 0 else _node_coordinates(context, start_node)
        fixed_hours = cruise_hours(fixed.length_m / 1000, context.composer.speed_kmh)
        closes = destination is None
        if destination is None:
            destination_index = context.origin_node
            destination = context.origin
        else:
            snapped = _snap_destination(context, destination)
            if snapped is None:
                return []
            destination_index = snapped
            destination = context.destination_correction or destination
        traveled = _traveled_columns(context, fixed.edges)

        tree_started = time.monotonic()
        # 往路レグを、最後の固定点→終点の見込み所要時間ぶんの時刻ビンで組み直す。
        outbound = context.composer.compose(
            "outbound" if leg_index == 0 else f"leg{leg_index}", start_point, fixed_hours, +1,
            duration_hours=straight_line_hours(
                start_point, destination, context.composer.speed_kmh, context.composer.detour_ratio,
            ),
        )
        context.legs = [*context.legs[:leg_index], outbound]
        forward_tree = await asyncio.to_thread(
            build_turn_expanded_tree,
            context.turn_structure, _avoiding_traveled(outbound.cost_bins_lazy, traveled), context.statics.edge_length_m,
            _origin_states(context.statics, start_node), context.statics.csr.node_count,
            edge_seconds=outbound.travel_bins_lazy, bin_seconds=outbound.bin_seconds,
        )

        # 迂回率は前向き木（走り出す点から`DETOUR_RATIO_MIN_ROAD_M`以上先の到達Node）の実測中央値を使い、学習値として保存する。
        reached = np.flatnonzero(
            np.isfinite(forward_tree.node_cost) & (forward_tree.node_length_m >= DETOUR_RATIO_MIN_ROAD_M)
        )
        detour_ratio_median = _median_detour_ratio(context, start_node, reached, forward_tree.node_length_m[reached])
        inbound_detour_ratio = _learn_detour_ratio(context, detour_ratio_median)
        # 後ろ向き木は終点へ向かうレグ: 終点を基準点に、到着予定時刻を
        # 「前段の見込み時間＋走り出す点〜終点の直線距離×迂回率÷仮定速度」に置いて合成する。
        arrival_hours = fixed_hours + straight_line_hours(
            start_point, destination, context.composer.speed_kmh, inbound_detour_ratio,
        )
        # 後ろ向き木は時刻ラベルを持てない（終点から遡るため各状態の到達時刻が決まらない）。
        # 代わりに、前向き木が出した「走り出す点からその区間へ実際に到達する時間」を通過時刻として
        # 渡す——直線距離からの推定より実態に近く、候補は伸び率の上限内に収まるため
        # ずれもその範囲に収まる。前向き木が届かない区間だけ直線距離の推定へ落とす。
        forward_seconds_lazy = forward_tree.node_seconds[context.turn_structure.edge_from]
        forward_hours = context.composer.to_full_row_order(forward_seconds_lazy) / 3600.0 + fixed_hours
        fallback_hours = estimate_passage_hours(
            context.composer.mid_lat, context.composer.mid_lon,
            destination, arrival_hours, -1, context.composer.speed_kmh,
            detour_ratio=inbound_detour_ratio,
        )
        inbound = context.composer.compose(
            "inbound", destination, arrival_hours, -1,
            passage_hours=reached_or_estimated_hours(forward_hours, fallback_hours),
        )
        context.legs = [*context.legs[:leg_index + 1], inbound]
        backward_tree = await asyncio.to_thread(
            build_turn_expanded_tree,
            context.turn_structure, _avoiding_traveled(inbound.cost_lazy, traveled), context.statics.edge_length_m,
            _destination_states(context.turn_structure, destination_index),
            context.statics.csr.node_count, reverse=True, edge_seconds=inbound.travel_seconds_lazy,
        )
        tree_ms = round((time.monotonic() - tree_started) * 1000)

        # Nodeで単に前向き＋後ろ向きを足すと、そのNodeで曲がる費用が抜ける。
        junction_started = time.monotonic()
        junction = combine_forward_backward_at_nodes(
            context.turn_structure, forward_tree, backward_tree, context.statics.csr.node_count
        )
        junction_ms = round((time.monotonic() - junction_started) * 1000)
        # 終点そのものを経由Nodeとする経路（＝経由せず直行する経路）も候補に含める。
        # junctionは「入る区間×出る区間」の対で作るため、そこで終わる経路は現れない。
        add_terminal_candidate(junction, forward_tree, destination_index)
        combined_cost = junction.cost
        combined_length = junction.length_m
        combined_seconds = junction.seconds
        reachable = np.isfinite(combined_cost)
        if not np.any(reachable):
            # 前向き木・後ろ向き木のどちらがどれだけ到達できているかを内訳として出す
            # （前向きのみ0なら走り出す側、後ろ向きのみ0なら終点側の孤立を疑える）。
            logger.warning(
                "select_via_nodes reachable=0 forward_reached=%d backward_reached=%d "
                "destination_reached_by_forward=%s start_reached_by_backward=%s tree_ms=%d",
                int(np.isfinite(forward_tree.node_cost).sum()), int(np.isfinite(backward_tree.node_cost).sum()),
                bool(np.isfinite(forward_tree.node_cost[destination_index])),
                bool(np.isfinite(backward_tree.node_cost[start_node])),
                tree_ms,
            )
            return []

        best_index, candidates = alternative_via_nodes(combined_cost, combined_length, reachable)
        best_length_m = float(combined_length[best_index])
        # 周回の折返し点選定と同じく、経路長・difficultyのパレート非劣解を先に並べる
        # （目的地ルートは目標距離を持たずALTERNATIVE_MAX_STRETCH倍以内という上限だけが効くぶん、
        # 難易度単独で並べると伸び率上限いっぱいの遠回りが上位を占めやすい）。
        ranking = rank_by_pareto_layers(
            candidates, combined_length[candidates], combined_cost[candidates], combined_seconds[candidates],
            self._penalty_strength,
            max_items=max_routes, max_examined=_MAX_VIA_NODE_CANDIDATES_EXAMINED, tie_by_distance=False,
        )
        ranked = candidates[ranking.order].tolist()
        if len(candidates) > _MAX_VIA_NODE_CANDIDATES_EXAMINED:
            logger.warning(
                "via-node候補を打ち切りました within_stretch=%d examined=%d "
                "（上位から順に見るため、打ち切られたのは並べた後の下位）",
                len(candidates), _MAX_VIA_NODE_CANDIDATES_EXAMINED,
            )
        ranked = best_first(ranked, best_index)

        full_edges_cache: dict[int, list[int] | None] = {}
        forward_edge_count: dict[int, int] = {}

        def full_edges(node_index: int) -> list[int] | None:
            if node_index not in full_edges_cache:
                forward_state = int(junction.forward_state[node_index])
                backward_state = int(junction.backward_state[node_index])
                forward_edges = (
                    turn_expanded_path_from_state(forward_tree, forward_state) if forward_state >= 0 else None
                )
                # backward_stateが-1なのは終点そのものを指す場合で、後ろ向きの区間は無い。
                backward_edges = (
                    turn_expanded_path_from_state_to_source(backward_tree, backward_state)
                    if backward_state >= 0 else []
                )
                if forward_edges is None:
                    full_edges_cache[node_index] = None
                else:
                    # 行って戻る形（前向き・後ろ向きが同じ物理区間を通る）の判定は、
                    # is_loop_too_similarと同じ進行方向を無視した物理区間キーで行う——
                    # 同じ道でも逆方向Edge（別のedge_id/index）を通れば単純なEdge index
                    # 集合の比較では検出できないため。
                    forward_segments = _physical_segments(context, forward_edges)
                    backward_segments = _physical_segments(context, backward_edges)
                    if forward_segments.keys() & backward_segments.keys():
                        full_edges_cache[node_index] = None
                    else:
                        full_edges_cache[node_index] = forward_edges + backward_edges
                        forward_edge_count[node_index] = len(forward_edges)
            return full_edges_cache[node_index]

        selected = select_diverse_by_overlap(
            ranked, full_edges, context.statics.edge_length_m,
            [VIA_NODE_MAX_OVERLAP_RATIO, VIA_NODE_RELAXED_OVERLAP_RATIO], max_routes,
        )

        fixed_edges = fixed.edges
        fixed_leg_of_edge = fixed.leg_of_edge
        traced: list[TracedLoop] = []
        for node_index in selected:
            edges = full_edges(node_index)
            if not edges:
                continue
            forward_count = forward_edge_count[node_index]
            path = [*fixed_edges, *edges]
            leg_of_edge = [
                *fixed_leg_of_edge, *[leg_index] * forward_count, *[leg_index + 1] * (len(edges) - forward_count),
            ]
            traced.append(TracedLoop(
                bearing=None, distance_km=_path_km(context, path), data=path, leg_of_edge=leg_of_edge,
                reversible=closes and fixed.reversible,
            ))

        logger.info(
            "select_via_nodes reachable=%d within_stretch=%d examined=%d selected=%d max_routes=%d "
            "best_km=%.1f fixed_km=%.1f detour_ratio_median=%.2f tree_ms=%d junction_ms=%d",
            int(reachable.sum()), len(candidates), len(ranked), len(traced), max_routes,
            best_length_m / 1000, fixed.length_m / 1000, detour_ratio_median, tree_ms, junction_ms,
        )
        return traced

    async def select_fastest_route(
        self, context: _RoadGraphContext, fixed: FixedLegs, destination: Coordinates
    ) -> TracedLoop | None:
        """所要時間が最短の経路を1本返す（主観的な軸の重みを一切使わない基準線）。出発地から置いた経由地を置いた順に
        通り、目的地で終わる。

        コスト配列に区間ごとの所要時間（走行モデル＋停止の待ち）を、遷移にはターンの待ちを
        そのまま秒で渡すため、得られるのは**時間最短**の経路になる。利用者の好み（軸の重み）を
        すべて0にしたときの経路であり、候補が基準線に対して何を犠牲に何を得たかを読むための
        物差しになる。置いた点どうしの区間も時間最短で結び直す（候補の前段の道は軸の重みで選んでいる）。

        **軸の重みは使わないが、0次フィルタは使う**——あれは好みではなく通行可否・走行可否の
        表明で、所要時間を優先する経路でも越えてよいものではない。除外Edgeの所要時間を
        `inf`にすることで表現する。

        `select_via_nodes`の後に呼ぶこと。最後の区間のレグを引き継ぐ。

        置いた点どうしの区間は候補と同じレグで測り、最後の区間は経路の所要時間が半分になる位置で前向き・後ろ向きの
        レグへ割る——他の候補と同じく概ね半分ずつ割れ、レグごとに時刻の異なる風の評価が候補間で揃う。
        """
        snapped = _snap(context, destination)
        if snapped is None:
            return None
        destination_index = snapped[0]

        started = time.monotonic()
        stops = [*fixed.nodes, destination_index]
        path: list[int] = []
        leg_of_edge: list[int] = []
        for leg_index, (from_node, to_node) in enumerate(zip(stops, stops[1:])):
            leg = context.legs[leg_index]
            time_bins = leg.travel_bins_lazy
            edges = await asyncio.to_thread(
                turn_expanded_shortest_path,
                context.turn_structure, time_bins,
                heuristic_seconds(
                    straight_distances_m(context.node_lat, context.node_lon, to_node), context.composer.speed_kmh,
                ),
                _origin_states(context.statics, from_node), to_node,
                time_bins, leg.bin_seconds,
            )
            if not edges:
                logger.debug("select_fastest_route to_node=%s", _node_key_of(context.road, to_node))
                logger.warning("select_fastest_route no path to=%s", _node_label(context, to_node))
                return None
            path.extend(edges)
            if to_node == destination_index:
                halves = leg_of_edge_by_half([float(leg.travel_seconds_lazy[index]) for index in edges])
                leg_of_edge.extend(leg_index + half for half in halves)
            else:
                leg_of_edge.extend([leg_index] * len(edges))
        distance_km = _path_km(context, path)

        logger.info(
            "select_fastest_route fastest_km=%.1f edges=%d forward_edges=%d elapsed_ms=%d",
            distance_km, len(path), sum(1 for leg in leg_of_edge if leg < len(fixed.segments) + 1),
            round((time.monotonic() - started) * 1000),
        )
        return TracedLoop(bearing=None, distance_km=distance_km, data=path, leg_of_edge=leg_of_edge, reversible=False)

    async def trace_loop_from_turnaround(
        self, context: _RoadGraphContext, fixed: FixedLegs, turnaround: LoopTurnaround,
    ) -> TracedLoop:
        """前段の道と往路（最後の固定点からの一対全木上の経路、`select_loop_turnarounds`で確定済み）に、それまでに
        走った道を避けた帰り（中継点→終点のA*）を継いで1本にする。

        帰りの探索の間だけ、走った区間（前段＋往路）＋同一Node対の逆方向Edgeのコストを
        `RETRACE_PENALTY_MULTIPLIER`倍へ**差し替え**、探索後に元へ戻す。配列ごとコピーすると
        候補の数だけbbox全体ぶんの複製を払うため、触るのは走った区間の列だけにする。時刻ビンを
        張った帰りでは全ビンの同じ列をまとめて差し替える——どの時刻に通っても「走った道を
        なぞる」ことに変わりはない。

        **差し替えはawaitを挟まない同期区間で完結させること。** 共有のコスト配列を書き換える
        ため、この間に他のコルーチンへ制御が渡ると別の候補が書き換え後の値を見る。

        倍率は有限のため、帰りが走った道を戻る以外に道が無い区間（袋小路・起点付近の単一の道）は
        そのまま通れる。
        """
        data: _TurnaroundData = turnaround.data
        leg_index = len(fixed.segments)
        # 帰りレグのコスト配列（select_loop_turnaroundsが合成済み）。
        inbound_leg = context.legs[leg_index + 1]
        cost_bins = inbound_leg.cost_bins_lazy

        penalized_columns = _traveled_columns(context, [*fixed.edges, *data.outbound_edge_indices])
        trace_started = time.monotonic()
        original = cost_bins[:, penalized_columns].copy()
        try:
            cost_bins[:, penalized_columns] = retrace_penalized(original)
            return_edge_index_list = turn_expanded_shortest_path(
                context.turn_structure, cost_bins,
                heuristic_seconds(_estimate_to(context, data.end_node), context.composer.speed_kmh),
                _origin_states(context.statics, data.node),
                data.end_node,
                inbound_leg.travel_bins_lazy, inbound_leg.bin_seconds,
            )
        finally:
            cost_bins[:, penalized_columns] = original
        trace_wall_ms = round((time.monotonic() - trace_started) * 1000)
        if return_edge_index_list is None:
            raise RoutingError(f"turnaround bearing={turnaround.bearing}: no return path found")

        if not return_edge_index_list:
            raise RoutingError(f"turnaround bearing={turnaround.bearing}: return path has no edges")
        return_edge_indices = np.array(return_edge_index_list, dtype=np.int64)
        retrace = overlap_ratio(return_edge_indices, penalized_columns, context.statics.edge_length_m)
        path = [*fixed.edges, *data.outbound_edge_indices, *return_edge_index_list]
        leg_of_edge = [
            *fixed.leg_of_edge,
            *[leg_index] * len(data.outbound_edge_indices), *[leg_index + 1] * len(return_edge_index_list),
        ]
        distance_km = _path_km(context, path)
        logger.debug(
            "trace_loop_from_turnaround bearing=%d outbound_km=%.1f loop_km=%.1f retrace_ratio=%.2f wall_ms=%d",
            turnaround.bearing, data.outbound_length_m / 1000, distance_km, retrace, trace_wall_ms,
        )
        return TracedLoop(
            bearing=turnaround.bearing if data.closes else None, distance_km=distance_km, data=path,
            leg_of_edge=leg_of_edge, reversible=data.reversible,
        )

    def build_traced_from_edge_ids(
        self, context: _RoadGraphContext, edge_ids: tuple[str, *tuple[str, ...]], destination: Coordinates,
    ) -> TracedLoop:
        """クライアントが組み立てたEdge id列を、評価できる経路として検証して`TracedLoop`にする。

        区間の乗り換えで使う。フロントは候補の`edge_ids`から
        「Aの前半＋Bの後半」を作って送り返すため、**このグラフに実在し・順につながり・
        起点から始まり・目的地へ着く**ことをここで確かめる（送られた列をそのまま信じると、
        評価は成功するのに経路として成立しないルートが候補一覧へ並ぶ）。

        終点は生成と同じく出て戻れるNodeへ寄せて解くため、比べる相手は元の候補が
        実際に終わったNodeになる——目的地を寄せ直した場合も、
        寄せ直した後の地点が条件として返っており、合成もその地点で送られてくる。

        合成経路はvia-nodeを持たないため、レグはこの経路自身の距離で`leg_of_edge_by_half`が
        切る。**レグ番号を振る側が、その番号のレグを
        `context.legs`へ用意する**——`prepare`が作るのは往路レグだけで、復路レグは探索
        （折返し点の選定・経由Nodeの選定）が作る。合成経路はどちらの探索も通らない。
        """
        resolved = [_lazy_index_of(context, edge_id) for edge_id in edge_ids]
        unknown = [edge_id for edge_id, index in zip(edge_ids, resolved, strict=True) if index is None]
        if unknown:
            # 区間の鍵はOSMの道のidを含むため、常時のログへ載る例外の文には件数だけを書く（logging.md 基本原則4）。
            logger.debug("経路に未知のEdgeが含まれています first=%s", unknown[0])
            raise RoutingError(f"経路に未知のEdgeが含まれています count={len(unknown)}")
        path = [index for index in resolved if index is not None]
        lazy_graph = context.lazy_graph
        tails = [int(lazy_graph.edge_from[index]) for index in path]
        heads = [int(lazy_graph.edge_to[index]) for index in path]
        if tails[0] != context.origin_node:
            _refuse_at_nodes(context, "経路が起点から始まっていません", expected=context.origin_node, actual=tails[0])
        for index, (head, following_tail) in enumerate(zip(heads, tails[1:])):
            if head != following_tail:
                _refuse_at_nodes(
                    context, f"経路がつながっていません index={index}", to_node=head, next_from_node=following_tail,
                )
        snapped = _snap(context, destination)
        if snapped is not None and heads[-1] != snapped[0]:
            _refuse_at_nodes(context, "経路が目的地に着いていません", expected=snapped[0], actual=heads[-1])

        lengths = context.statics.edge_length_m[path].tolist()
        total_m = sum(lengths)
        leg_of_edge = leg_of_edge_by_half(lengths)
        if max(leg_of_edge) > 0 and len(context.legs) < 2:
            total_hours = cruise_hours(total_m / 1000, context.composer.speed_kmh)
            context.legs = [
                context.legs[0],
                context.composer.compose(
                    "inbound", context.origin, total_hours, -1,
                    duration_hours=leg_duration_hours(total_m / 1000, context.composer.speed_kmh),
                ),
            ]
        return TracedLoop(
            bearing=None, distance_km=round(total_m / 1000, DISTANCE_KM_DECIMALS), data=path, leg_of_edge=leg_of_edge,
            reversible=False,
        )

    def is_loop_too_similar(
        self, context: _RoadGraphContext, fixed: FixedLegs, candidate: TracedLoop, accepted: list[TracedLoop]
    ) -> bool:
        """`candidate`が`accepted`のいずれかと、前段のあとの道（往路＋帰り）で
        `LOOP_MAX_OVERLAP_RATIO`を超えて重複するか。前段の道は全候補で同じなので比べない。進行方向を無視して
        比較するため、「同じ周回の逆回り」（往路と帰りが入れ替わっただけ）や「往路は違うが
        帰りが同じ裏道へ収束する」周回のどちらも同じ判定で弾ける。`TracedLoop.data`は
        区間の番号列（前段＋往路＋帰り、`trace_loop_from_turnaround`参照）。
        """
        fixed_count = len(fixed.edges)
        candidate_lengths = _physical_segments(context, candidate.data[fixed_count:])
        for other in accepted:
            ratio = physical_overlap_ratio(candidate_lengths, _physical_segments(context, other.data[fixed_count:]))
            if ratio > LOOP_MAX_OVERLAP_RATIO:
                logger.debug(
                    "loop dedup rejected bearing=%s overlap_ratio=%.2f vs accepted bearing=%s",
                    candidate.bearing, ratio, other.bearing,
                )
                return True
        return False

    def repeated_shares(self, context: _RoadGraphContext, traced: list[TracedLoop]) -> list[float]:
        """候補ごとの、同じ道（進行方向を問わない物理区間）を2度目以降に走る距離の割合（0〜1）。走った道を避けた
        効き目を、常時のサマリで数えるために出す。"""
        shares = []
        for candidate in traced:
            total_m = float(context.statics.edge_length_m[candidate.data].sum())
            once_m = sum(_physical_segments(context, candidate.data).values())
            shares.append(1.0 - once_m / total_m if total_m > 0 else 0.0)
        return shares

    async def evaluate_loops(
        self, context: _RoadGraphContext, traced: list[TracedLoop], start_time: datetime
    ) -> list[RouteCandidate]:
        # 実ジオメトリは距離フィルタを通った候補ぶんだけを、全候補まとめて1回で取り直す
        # （棄却済み候補ぶんは問い合わせない）。引けない区間があれば落とす——探索が通った
        # 区間の実体がDBに無いということで、線の欠けた経路を配るより落ちる方がよい。
        topology = {
            index: _lean_edge(context.road, context.lazy_graph, index)
            for index in dict.fromkeys(index for t in traced for index in t.data)
        }
        hydrated = await self._graph_service.get_edges_with_geometry(list(topology.values()))
        edges_by_candidate: list[list[LeanEdge]] = [
            [hydrated[topology[index].edge_id] for index in t.data] for t in traced
        ]
        return list(
            await asyncio.gather(
                *(
                    self._build_best_candidate(context, t, edges_in_path, start_time)
                    for t, edges_in_path in zip(traced, edges_by_candidate)
                )
            )
        )

    async def _build_best_candidate(
        self, context: _RoadGraphContext, traced: TracedLoop, edges_in_path: list[LeanEdge], start_time: datetime
    ) -> RouteCandidate:
        """1候補ぶんの周回を組み立てる。

        同じ周回の逆回りは追加のI/Oなしで合成できるため、合成して**難易度の小さい方だけ**を
        残す（両方向を別候補として並べない）。逆走は勾配・風で評点が変わるため常に意味がある。
        一方通行Edgeが1つでもあれば成立しないので、その場合は順方向のみ。

        逆に回ると置いた順が崩れる経路・出発地へ戻らない経路（`TracedLoop.reversible`が偽）は逆回りを作らない。
        """
        path: list[int] = traced.data
        elevation_by_edge = self._elevation_by_edge(context, edges_in_path, path)
        leg_of_edge = traced.leg_of_edge
        forward_candidate = self._build_candidate(
            context, traced, edges_in_path, path, elevation_by_edge, start_time, leg_of_edge
        )

        if not traced.reversible:
            return forward_candidate

        reversed_path = _reverse_traced_edges(edges_in_path, path, context)
        if reversed_path is None:
            return forward_candidate
        reverse_edges, reverse_path = reversed_path
        reverse_elevation = reverse_elevation_by_edge(edges_in_path, reverse_edges, elevation_by_edge)
        reverse_candidate = self._build_candidate(
            context, traced, reverse_edges, reverse_path, reverse_elevation, start_time,
            reverse_leg_assignment(leg_of_edge),
        )
        return pick_better_candidate(forward_candidate, reverse_candidate)

    def _elevation_by_edge(
        self, context: "_RoadGraphContext", edges_in_path: list[LeanEdge], path: list[int]
    ) -> dict[str, ElevationAttribute]:
        """経路の区間ぶんの標高属性。探索フェーズで読んだ材料がそのまま持っている。

        取り込んだ範囲の全区間ぶんを派生バッチが埋めるため、ここで外部へ取りに行く経路は
        無い（欠けているのは標高タイルが覆っていない区間だけで、そこは値なしのまま）。
        """
        found = {}
        for edge, index in zip(edges_in_path, path, strict=True):
            attribute = elevation_attribute(context.road.network, _network_row(context, index), edge.edge_id)
            if attribute is not None:
                found[edge.edge_id] = attribute
        return found

    def _build_candidate(
        self,
        context: _RoadGraphContext,
        traced: TracedLoop,
        edges_in_path: list[LeanEdge],
        path: list[int],
        elevation_by_edge: dict[str, ElevationAttribute],
        start_time: datetime,
        leg_of_edge: list[int],
    ) -> RouteCandidate:
        # 区間と標高属性を引数で受けるのは、逆回り候補も同じ組み立てを通すため。
        # distance_km・bearingは同じ物理経路なので順方向の`traced`のものをそのまま使う。
        geometry, edge_point_offsets = concat_edge_geometries(edges_in_path)
        segments, segment_categories, segment_raw_values = self._build_segment_details(
            edges_in_path, path, elevation_by_edge, context, start_time, leg_of_edge
        )
        rows = np.asarray([_slice_row(context, index) for index in path], dtype=np.int64)
        # categorical材料の延長割合は**集約より前に**Edge単位の値から畳む。集約後に
        # 計算すると、ビンの代表値を1つ選ぶ形になり割合がビンの粒度へ量子化される。
        material_category_shares = merge_material_category_shares(
            zip((segment.distance_km for segment in segments), segment_categories)
        )
        axis_raw_values = route_axis_raw_values(
            list(zip((segment.distance_km for segment in segments), segment_raw_values))
        )
        # 返すsegmentsは集約する。Edge単位のままだとペイロードとフロントの描画費用が嵩む。
        segments = aggregate_segments_into_bins(segments)

        return RouteCandidate(
            # 方位を持たない経路の名前は、種類と一緒に`route_generator.py: _label`が付ける。
            direction_label=compass_label(traced.bearing) if traced.bearing is not None else "",
            distance_km=traced.distance_km,
            geometry=geometry,
            edge_ids=[edge.edge_id for edge in edges_in_path],
            edge_point_offsets=edge_point_offsets,
            node_ids=(
                [edges_in_path[0].from_node_id, *(edge.to_node_id for edge in edges_in_path)]
                if edges_in_path else []
            ),
            segments=segments,
            material_category_shares=material_category_shares,
            axis_raw_values=axis_raw_values,
            estimated_duration_seconds=self._estimate_duration_seconds(context, edges_in_path, path, leg_of_edge),
            wind_unavailable=context.composer.wind_unavailable,
            missing_travel_data_share=context.composer.missing_travel_data_share(rows) if len(rows) else None,
            elevation_gain_m=route_elevation_gain(edges_in_path, elevation_by_edge),
        )

    def _estimate_duration_seconds(
        self, context: _RoadGraphContext, edges: list[LeanEdge], path: list[int], leg_of_edge: list[int]
    ) -> float | None:
        """候補の所要時間（秒）＝ 区間の走行時間 ＋ 停止の待ち ＋ ターンの待ち。経路を探索と同じ規則で
        たどった時刻（`_route_passages`）の終わりで、区間の到達予想と同じ時計を使う。"""
        if not edges:
            return None
        last = self._route_passages(context, edges, path, leg_of_edge)[-1]
        return last.elapsed_seconds + last.seconds

    def _route_passages(
        self, context: _RoadGraphContext, edges: list[LeanEdge], path: list[int], leg_of_edge: list[int]
    ) -> list[EdgePassage]:
        """経路を探索と同じ規則でたどった区間ごとの時刻（`domain/route_search.py: route_passages`）。"""
        return route_passages(
            context.legs, context.turn_structure, path, [_slice_row(context, index) for index in path],
            [edge.distance_m for edge in edges], leg_of_edge, context.composer.speed_kmh,
        )

    def _build_segment_details(
        self,
        edges: list[LeanEdge],
        path: list[int],
        elevation_by_edge: dict,
        context: _RoadGraphContext,
        start_time: datetime,
        leg_of_edge: list[int],
    ) -> tuple[list[RouteSegmentDetail], list[dict[str, str]], list[dict[str, float]]]:
        """区間ごとの表示値と、区間ごとのcategorical材料の値（材料id→値）・軸の生値（axis_id→値）を組み立てる。
        categorical材料の値は平均できず区間の器（ビンへ畳まれる）に載せられないため、軸の生値は画面が
        候補全体の値しか読まないため、どちらも候補全体へ畳む`_build_candidate`へ並びのまま渡す。

        軸別スコア・合成difficulty・寄与度・材料値は、
        そのEdgeが探索されたレグ（`leg_of_edge`）の合成済み配列（`context.legs`、
        区間の番号から行を引く）からそのまま読み、探索コストと表示を一致させる
        （二重計算を持たない）。到達予想時刻は経路を探索と同じ規則でたどった時刻（`_route_passages`）。
        """
        segments = []
        segment_categories: list[dict[str, str]] = []
        segment_raw_values: list[dict[str, float]] = []
        cumulative_km = 0.0
        active_material_ids = displayed_material_ids(context.composer.weights)
        passages = self._route_passages(context, edges, path, leg_of_edge)
        rows = [_slice_row(context, index) for index in path]
        timed = _values_at_passages(context, rows, leg_of_edge, passages)
        winds = context.composer.winds_at(
            rows,
            [_passage_hours_of(context, row, leg_index, passage)
             for row, leg_index, passage in zip(rows, leg_of_edge, passages)],
            [passage.beyond_bins for passage in passages],
        )

        for index, (edge, row, leg_index) in enumerate(zip(edges, rows, leg_of_edge)):
            leg = context.legs[leg_index]
            # 時刻で変わる値（難易度・軸・材料）は、探索がこの区間に使ったビンの値。ビンが1本のレグはレグの配列、
            # 2本以上のレグは経路上の行だけをそのビンの時刻で合成し直した値（`LegCostArrays.bin_start_hours`参照）。
            values, value_row = timed.get(index, (leg, row))
            distance_km = edge.distance_m / 1000
            elevation_attr = elevation_by_edge.get(edge.edge_id)

            gradient_percent = elevation_attr.average_grade if elevation_attr else None
            # 勾配だけは`leg.material_arrays`ではなくこのループが持つ値から載せる
            # （標高属性として既に引いてあり、改めて計算する必要が無いため）。
            static_material_values = (
                {GRADIENT_PERCENT: round(gradient_percent, GRADIENT_VALUE_DECIMALS)}
                if GRADIENT_PERCENT in active_material_ids and gradient_percent is not None
                else {}
            )

            axis_scores = {
                axis_id: float(arr[value_row])
                for axis_id, arr in values.axis_arrays.items()
                if not math.isnan(arr[value_row])
            }
            axis_contributions = values.axis_contributions_at(value_row)
            # 密度の軸は、ビンと候補で得点を作り直すために横軸の値を載せる（点数と同じ区間が欠損になる）。
            weight_shares = values.axis_weight_shares_at(value_row)
            density_inputs = {
                axis_id: DensityScoreInput(
                    value=float(column.inputs[row]),
                    distance_km=distance_km,
                    weight_share=weight_shares.get(axis_id),
                    shape=column.shape,
                )
                for axis_id, column in leg.density_axes.items()
                if not math.isnan(column.inputs[row])
            }
            # 折れ点を通す前の生値。静的スコア行列が持つ列をそのまま読む
            # （動的材料を参照する軸は行列側で除外済み）。
            segment_raw_values.append({
                axis_id: float(arr[row])
                for axis_id, arr in leg.axis_raw_arrays.items()
                if not math.isnan(arr[row])
            })
            difficulty_value = values.difficulty_array[value_row]
            composite_difficulty_value = None if math.isnan(difficulty_value) else float(difficulty_value)
            material_values = {
                **static_material_values,
                **{
                    material_id: value
                    for material_id in active_material_ids
                    if (value := material_value_at(values, material_id, value_row)) is not None
                },
            }
            segment_categories.append({
                material_id: raw
                for material_id, column in leg.categorical_material_arrays.items()
                if material_id in active_material_ids and (raw := column.value_at(row)) is not None
            })

            arrival_time = start_time + timedelta(seconds=passages[index].elapsed_seconds)

            start_lat, start_lon = edge.geometry[0]
            end_lat, end_lon = edge.geometry[-1]
            # 区間の道なり形状はEdgeの形状点列そのもの（追加取得なし）。2点未満のEdgeは
            # 形状にならないためNone（フロントは始点・終点の直線で代替描画する）。
            segment_coordinates = [[lon, lat] for lat, lon in edge.geometry]

            segments.append(
                RouteSegmentDetail(
                    geometry=(
                        {"type": "LineString", "coordinates": segment_coordinates}
                        if len(segment_coordinates) >= 2
                        else None
                    ),
                    start_latitude=start_lat,
                    start_longitude=start_lon,
                    end_latitude=end_lat,
                    end_longitude=end_lon,
                    cumulative_distance_km=round(cumulative_km, DISTANCE_KM_DECIMALS),
                    distance_km=round(distance_km, DISTANCE_KM_DECIMALS),
                    estimated_arrival_time=arrival_time.isoformat(),
                    axis_difficulties=axis_scores,
                    axis_contributions=axis_contributions,
                    material_values=material_values,
                    difficulty=composite_difficulty_value,
                    wind=winds[index],
                ).with_density_inputs(density_inputs)
            )
            cumulative_km += distance_km

        return segments, segment_categories, segment_raw_values


def _values_at_passages(
    context: _RoadGraphContext, rows: list[int], leg_of_edge: list[int], passages: list[EdgePassage]
) -> dict[int, tuple[RowValues, int]]:
    """ビンが2本以上あるレグの区間を、探索が使ったビンの時刻で合成し直す（区間の添字→（値, 値の中の位置））。
    同じレグ・同じビンの区間はまとめて1回で合成する。"""
    groups: dict[tuple[int, int], list[int]] = {}
    for index, (leg_index, passage) in enumerate(zip(leg_of_edge, passages)):
        if len(context.legs[leg_index].bin_start_hours) > 1:
            groups.setdefault((leg_index, passage.time_bin), []).append(index)
    timed: dict[int, tuple[RowValues, int]] = {}
    for (leg_index, time_bin), indices in groups.items():
        group_rows = np.array([rows[i] for i in indices], dtype=np.int64)
        hours = np.full(len(group_rows), context.legs[leg_index].bin_start_hours[time_bin])
        values = context.composer.values_at_rows(group_rows, hours)
        for position, index in enumerate(indices):
            timed[index] = (values, position)
    return timed


def _passage_hours_of(context: _RoadGraphContext, row: int, leg_index: int, passage: EdgePassage) -> float | None:
    """その区間の評価に使った通過時刻（出発からの経過[h]）。出発時点の値で合成したレグはNone。"""
    leg = context.legs[leg_index]
    if leg.bin_start_hours:
        return leg.bin_start_hours[passage.time_bin]
    if leg.passage_hours is not None:
        return float(leg.passage_hours[row])
    return None


def _slice_row(context: _RoadGraphContext, index: int) -> int:
    """区間の番号→切り出した区間の行（材料・スコア行列・表示用配列の行）。"""
    return int(context.lazy_graph.edge_rows[index])


def _network_row(context: _RoadGraphContext, index: int) -> int:
    """区間の番号→道路網全体の区間の行。"""
    return int(context.road.rows[context.lazy_graph.edge_rows[index]])


def _node_key_of(road: RoadSlice, node: int) -> str:
    return node_key(int(road.network.node_osm_id[road.nodes[node]]))


def _node_label(context: _RoadGraphContext, node: int) -> str:
    """常時のログに書くノードの地点。小数2桁の緯度経度で、OSMのidは書かない（logging.md 基本原則4）。"""
    return f"({float(context.node_lat[node]):.2f},{float(context.node_lon[node]):.2f})"


def _refuse_at_nodes(context: _RoadGraphContext, message: str, **nodes: int) -> NoReturn:
    """経路の形を断る。例外の文は常時のログへ載るため地点は`_node_label`で書き、OSMのidはDEBUGにだけ出す。"""
    logger.debug("%s %s", message, " ".join(f"{name}={_node_key_of(context.road, n)}" for name, n in nodes.items()))
    raise RoutingError(f"{message} " + " ".join(f"{name}={_node_label(context, n)}" for name, n in nodes.items()))


def _node_coordinates(context: _RoadGraphContext, node: int) -> Coordinates:
    return Coordinates(latitude=float(context.node_lat[node]), longitude=float(context.node_lon[node]))


def _snap(context: _RoadGraphContext, point: Coordinates) -> tuple[int, bool] | None:
    """置いた点を、起点と同じく出て戻れるNodeへ寄せる（`domain/routing.py: snap_to_accessible_node`）。"""
    return snap_to_accessible_node(context.node_index, context.accessible, point, MAX_SNAP_CORRECTION_KM)


def _snap_destination(context: _RoadGraphContext, destination: Coordinates) -> int | None:
    """目的地を寄せたNode。寄せ直したら、その座標を`context.destination_correction`に残す（利用者のピンを動かす）。"""
    snapped = _snap(context, destination)
    if snapped is None:
        logger.warning("destination has no accessible node nearby")
        return None
    node, moved = snapped
    if moved:
        context.destination_correction = _node_coordinates(context, node)
        logger.warning(
            "corrected destination to nearest accessible node lat=%.2f lon=%.2f",
            context.destination_correction.latitude, context.destination_correction.longitude,
        )
    return node


def _path_km(context: _RoadGraphContext, path: list[int]) -> float:
    return round(float(context.statics.edge_length_m[path].sum()) / 1000, DISTANCE_KM_DECIMALS)


def _lean_edge(road: RoadSlice, lazy_graph: LazyRoadGraph, index: int) -> LeanEdge:
    """区間の番号から、形を持たない`LeanEdge`（区間の文字列の鍵・両端のノードの鍵付き）を作る。"""
    network = road.network
    row = int(road.rows[lazy_graph.edge_rows[index]])
    return LeanEdge(
        edge_id=edge_key(int(network.edge_way_id[row]), int(network.edge_segment[row]), bool(network.edge_forward[row])),
        from_node_id=_node_key_of(road, int(lazy_graph.edge_from[index])),
        to_node_id=_node_key_of(road, int(lazy_graph.edge_to[index])),
        geometry=[],
        distance_m=float(network.distance_m[row]),
        osm_way_id=int(network.edge_way_id[row]),
        segment_index=int(network.edge_segment[row]),
        forward=bool(network.edge_forward[row]),
    )


def _lazy_index_of(context: _RoadGraphContext, edge_id: str) -> int | None:
    """区間の文字列の鍵→区間の番号。この探索範囲に無い・探索用グラフに載らない（並行区間の
    採られなかった側）区間はNone。"""
    parsed = parse_edge_key(edge_id)
    if parsed is None:
        return None
    network_row = edge_row_of(context.road.network, *parsed)
    if network_row is None:
        return None
    rows = context.road.rows
    position = int(np.searchsorted(rows, network_row))
    if position >= len(rows) or rows[position] != network_row:
        return None
    index = context.composer.lazy_row(position)
    return index if index >= 0 else None


def _origin_states(statics: SearchGraphStatics, node_index: int) -> np.ndarray:
    """`node_index`から出る有向Edge（＝辺基準の木の始点となる状態）。"""
    csr = statics.csr
    return csr.entry_edge_index[csr.indptr[node_index]:csr.indptr[node_index + 1]].astype(np.int64)


def _destination_states(structure: TurnExpandedStructure, node_index: int) -> np.ndarray:
    """`node_index`へ入る有向Edge（＝逆向きの辺基準木の始点となる状態）。"""
    return np.flatnonzero(structure.edge_to == node_index)


def _median_detour_ratio(
    context: _RoadGraphContext, start_node: int, node_indices: np.ndarray, length_m: np.ndarray,
) -> float:
    """木の根`start_node`から`node_indices`（ノード番号）への道なり距離`length_m`と直線距離の比の中央値（`median_detour_ratio`）。"""
    return median_detour_ratio(
        _node_coordinates(context, start_node),
        context.node_lat[node_indices], context.node_lon[node_indices], length_m,
    )


def _learn_detour_ratio(context: _RoadGraphContext, measured: float) -> float:
    """実測の迂回率が有効なら探索範囲（タイル集合）の学習値として保存し、そのまま返す。
    無効（NaN・非正）なら合成に使っている現在の値（学習値または既定値）を返す。"""
    if not is_usable_detour_ratio(measured):
        return context.composer.detour_ratio
    detour_ratio_cache.set_detour_ratio(context.tile_set, measured)
    return measured


def _estimate_to(context: _RoadGraphContext, node: int) -> list[float]:
    """帰りの探索（中継点→終点）のA*ヒューリスティックの素材（各Nodeから`node`への直線距離）。終点は1回の生成で
    固定のため初回だけ`straight_distances_m`で計算し、以降の候補はcontextに保持した配列を共有する。
    """
    estimate = context.end_estimates.get(node)
    if estimate is None:
        estimate = context.end_estimates[node] = straight_distances_m(context.node_lat, context.node_lon, node)
    return estimate


def _traveled_columns(context: _RoadGraphContext, edges: Sequence[int]) -> np.ndarray:
    """走った区間と、同じNode対の逆向きの区間の番号（重複なし）。走った道を避ける罰を置く列。"""
    lazy_graph = context.lazy_graph
    traveled: set[int] = set(edges)
    for edge_index in edges:
        reverse_index = edge_index_between(
            context.statics.csr, int(lazy_graph.edge_to[edge_index]), int(lazy_graph.edge_from[edge_index])
        )
        if reverse_index is not None:
            traveled.add(reverse_index)
    return np.fromiter(traveled, dtype=np.int64, count=len(traveled))


def _avoiding_traveled(costs: np.ndarray, columns: np.ndarray) -> np.ndarray:
    """`costs`（区間が最後の軸）の`columns`の区間へ、走った道を避ける罰を置いた配列。罰が要れば写しを作り、元の
    配列は変えない——同じ配列を区間の表示と、ほかのレグの探索も読む。"""
    if len(columns) == 0:
        return costs
    penalized = costs.copy()
    penalized[..., columns] = retrace_penalized(costs[..., columns])
    return penalized


def _physical_segments(context: _RoadGraphContext, path: list[int]) -> dict[frozenset[int], float]:
    """区間の番号列（`TracedLoop.data`）を物理区間キー→距離(m)へ（`lengths_by_physical_segment`）。"""
    return lengths_by_physical_segment(
        context.lazy_graph.edge_from, context.lazy_graph.edge_to, context.statics.edge_length_m, path
    )


def _reverse_traced_edges(
    edges_in_path: list[LeanEdge], path: list[int], context: _RoadGraphContext
) -> tuple[list[LeanEdge], list[int]] | None:
    """順方向の経路（起点→...→起点）を逆順に辿った場合の、対応する逆方向の区間の列と
    その番号列を構築する。経路中に一方通行（逆方向の区間が存在しない）区間が1つでもあれば
    物理的に逆走不可能なため`None`を返す。

    `geometry`だけは逆方向の区間自身（形を持たない）からではなく、順方向で取得済みの
    ものを反転して使う——同じ物理区間を逆順に辿るだけなので、取り直す必要が無い。
    進行方向に依存しない値も**逆方向の区間自身から**引く。
    """
    lazy_graph = context.lazy_graph
    reverse_edges: list[LeanEdge] = []
    reverse_path: list[int] = []
    for edge, index in zip(reversed(edges_in_path), reversed(path), strict=True):
        reverse_index = edge_index_between(
            context.statics.csr, int(lazy_graph.edge_to[index]), int(lazy_graph.edge_from[index])
        )
        if reverse_index is None:
            return None
        topology = _lean_edge(context.road, lazy_graph, reverse_index)
        reverse_edges.append(replace(topology, geometry=list(reversed(edge.geometry))))
        reverse_path.append(reverse_index)
    return reverse_edges, reverse_path
