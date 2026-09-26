"""APIのDI工場（FastAPIのDepends用ファクトリ）とルータ共通ヘルパー。

サービスの組み立て方（どのクライアント・タイムアウト・リポジトリを注入するか）はすべて
ここに集約し、ルータはエンドポイントの入出力とレート制限だけを持つ。
"""

from datetime import datetime
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import AsyncIterator, Awaitable, Callable, Iterable, Protocol

from fastapi import Depends, HTTPException, Request

from app.config import settings
from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.dynamic_way_values import dedicated_way_value_axes
from app.domain.errors import RoutingError
from app.domain.evaluation import resolve_penalty_strength
from app.domain.hard_filters import DEFAULT_HARD_FILTERS
from app.domain.route_preference import RoutePreference
from app.domain.route import Coordinates, RouteSegment
from app.infrastructure.accident_repository import AccidentTileQuery
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.basemap_client import BasemapClient
from cachetools import LRUCache

from app.infrastructure.gsi_tile_client import NOT_FOUND_MAX_ENTRIES, GsiTileClient
from app.infrastructure.database import get_route_generation_session_factory, get_session_factory
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.http_client import get_http_client
from app.infrastructure.jma_tile_client import JmaTileClient
from app.infrastructure.db_status import DbStatusQuery
from app.infrastructure.derived_data_freshness import DerivedDataFreshnessQuery
from app.infrastructure.material_coverage import MaterialCoverageQuery
from app.infrastructure.rate_limiter import check_rate_limit
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.accident_service import AccidentService
from app.services.axis_registry_service import AxisRegistryAdminService
from app.services.evaluation_service import load_route_preference
from app.services.graph_service import GraphService
from app.services.region_service import RegionService
from app.domain.wind import ASSUMED_SPEED_KMH
from app.services.road_graph_engine import RoadGraphEngine
from app.services.route_generator import RouteGenerator
from app.services.flood_service import FloodService
from app.services.gradient_way_service import GradientWayService
from app.services.jma_amedas_service import JmaAmedasService
from app.services.db_status_service import DbStatusService
from app.services.derived_data_freshness_service import DerivedDataFreshnessService
from app.services.material_coverage_service import MaterialCoverageService
from app.services.rain_way_service import RainWayService
from app.services.warning_service import WarningService
from app.services.wbgt_service import WbgtService
from app.services.weather_service import WeatherService
from app.services.wind_way_service import WindWayService

logger = logging.getLogger("ridecompass.dependencies")


def client_id(request: Request) -> str:
    """per-IPレート制限のキーに使うクライアント識別子。

    リバースプロキシ配下では、uvicornの`--proxy-headers`＋`--forwarded-allow-ips`
    （backend/Dockerfile）が正しくないと全アクセスがプロキシの単一IPへ潰れる。

    `request.client`がNoneのときは全リクエストが"unknown"の1バケットへ相乗りし、
    無関係なクライアントの通信量が合算される。プロキシ構成の調査に使えるよう記録する。
    """
    if request.client is None:
        logger.warning("request.client is None; rate-limit key falls back to shared 'unknown' bucket")
        return "unknown"
    return request.client.host


def enforce_rate_limit(request: Request, prefix: str, limit_per_minute: int) -> None:
    """per-IPレート制限を確認し、超過していれば記録した上で429を送出する。

    `prefix`はレート制限のキー・rejection集計カテゴリの両方を兼ねる。
    """
    client = client_id(request)
    if not check_rate_limit(f"{prefix}:{client}", limit_per_minute):
        record_rate_limit_rejection(prefix, client, f"{limit_per_minute}/min")
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")


# 以下のJMA/GSI系サービスはいずれも軽量なJSON・CSVしか取りに行かないため、共有の
# httpx.AsyncClient（同じタイムアウト）を使い回す。
def get_weather_service():
    return WeatherService()


def get_warning_service():
    return WarningService(get_http_client(10.0))


def get_amedas_service():
    return JmaAmedasService(get_http_client(10.0))


def get_wbgt_service():
    return WbgtService(get_http_client(10.0))


def get_flood_service():
    return FloodService(get_http_client(10.0))


@dataclass
class RouteGenerationSetup:
    """1回のルート生成に使う組み立て済みの部品と、実際に適用された評価条件。

    `route_preference`以降はレスポンスの条件エコーにもそのまま使う。
    """

    generator: RouteGenerator
    route_preference: RoutePreference
    # 主観的割増と時間の換算レート（P）。
    penalty_strength: float
    # 仮定巡航速度（km/h）。通過予定時刻・到達予想時刻・所要時間の算出に使う。
    assumed_speed_kmh: float
    # 0次ハードフィルタの勾配しきい値（%、Noneは無効）。
    max_average_grade_percent: float | None
    # 0次ハードフィルタ名の個別ON/OFF上書き。常に解決済み（Noneではなく実際に適用された集合）。
    hard_filters: frozenset[str]


async def get_graph_service():
    async with get_route_generation_session_factory()() as session:
        yield GraphService(repository=RoadGraphRepository(session))


def _assemble_route_generation_setup(
    graph_service: GraphService,
    weather_service: WeatherService,
    preference_override: RoutePreference | None = None,
    penalty_strength: float | None = None,
    max_average_grade_percent: float | None = None,
    hard_filters_override: frozenset[str] | None = None,
    assumed_speed_kmh: float = ASSUMED_SPEED_KMH,
    lens_axis_id: str | None = None,
) -> RouteGenerationSetup:
    """組み立て済みのサービスと評価条件から`RouteGenerationSetup`を作る。"""
    preference = preference_override or load_route_preference()
    hard_filters = hard_filters_override if hard_filters_override is not None else DEFAULT_HARD_FILTERS
    # 省略されたときの値はここで1度だけ決める。以後は解決済みの値だけを回し、
    # レスポンスのconditionsへも同じ値をエコーする（画面が見る値と探索が使う値を分けない）。
    resolved_penalty_strength = resolve_penalty_strength(penalty_strength)
    engine = RoadGraphEngine(
        graph_service,
        weather_service,
        preference,
        resolved_penalty_strength,
        max_average_grade_percent,
        hard_filters,
        assumed_speed_kmh,
        lens_axis_id=lens_axis_id,
    )
    return RouteGenerationSetup(
        generator=RouteGenerator(engine),
        route_preference=preference,
        penalty_strength=resolved_penalty_strength,
        assumed_speed_kmh=assumed_speed_kmh,
        max_average_grade_percent=max_average_grade_percent,
        hard_filters=hard_filters,
    )


@asynccontextmanager
async def open_route_generation_setup(
    preference_override: RoutePreference | None = None,
    penalty_strength: float | None = None,
    max_average_grade_percent: float | None = None,
    hard_filters_override: frozenset[str] | None = None,
    assumed_speed_kmh: float = ASSUMED_SPEED_KMH,
    lens_axis_id: str | None = None,
) -> AsyncIterator[RouteGenerationSetup]:
    """ルート生成ジョブが使う`RouteGenerationSetup`を組み立てる非同期コンテキストマネージャ。

    レスポンス送出後も走り続けるジョブ本体から使うため`Depends`は使えない——リクエストの
    DBセッションはハンドラ関数が返った時点で閉じられ、その後も使い続けると失敗する。
    セッション開閉を複製しないよう、DI用ジェネレータ関数をそのまま
    `asynccontextmanager()`で包んで`AsyncExitStack`へ載せる。
    """
    async with AsyncExitStack() as stack:
        weather_service = get_weather_service()
        graph_service = await stack.enter_async_context(asynccontextmanager(get_graph_service)())
        yield _assemble_route_generation_setup(
            graph_service, weather_service,
            preference_override, penalty_strength,
            max_average_grade_percent, hard_filters_override, assumed_speed_kmh, lens_axis_id,
        )


PreviewBuilder = Callable[[Coordinates, Coordinates, float], Awaitable[RouteSegment]]


def get_preview_builder(
    graph_service: GraphService = Depends(get_graph_service),
    weather_service: WeatherService = Depends(get_weather_service),
) -> PreviewBuilder:
    """`/api/routes/preview`（単一区間確認）向けのビルダー。

    previewはリクエストボディでの評価重み・換算レート（P）の上書きに対応しないため、
    どちらもルート生成が省略時に使うのと同じ既定を使う。
    """

    async def preview(
        origin: Coordinates, destination: Coordinates, assumed_speed_kmh: float = ASSUMED_SPEED_KMH
    ) -> RouteSegment:
        preference = load_route_preference()
        engine = RoadGraphEngine(
            graph_service,
            weather_service,
            preference,
            resolve_penalty_strength(None),
            assumed_speed_kmh=assumed_speed_kmh,
        )
        segment = await engine.preview_segment(origin, destination)
        if segment is None:
            raise RoutingError("road_graph: no path found between origin and destination")
        return segment

    return preview


async def get_road_graph_repository():
    """`RoadGraphRepository`を直接使いたい読み取り専用の管理API向け。

    利用者はいずれも全表走査寄りのため、タイル配信保護用の短いcommand_timeoutで
    キャンセルされないようルート生成用のセッション工場を使う。
    """
    async with get_route_generation_session_factory()() as session:
        yield RoadGraphRepository(session)


async def get_region_service():
    async with get_session_factory()() as session:
        yield RegionService(repository=RoadGraphRepository(session))


# way_id→動的値配信の実装。**軸を名指ししない**——各サービスは自分が返す材料
# （`material_id`）だけを宣言し、軸との対応は軸定義が参照する材料から都度引く。軸はDBの行で
# 増減する（公開済みの軸は複製で改良する）ため、実装が軸の名前を持つと複製した軸が配信されない。
# サービスごとにコンストラクタ依存が違うため、生成は`build`の統一シグネチャ越しに行う。
# 軸スタジオは`dedicated_way_value_layer=true`の軸を宣言だけで作れるが、配信できる値は
# ここに実装がある材料だけ——実装の無い軸は未知のaxis_idと同じく404で返す（500にすると
# フロントの「データなし」フォールバックが効かず、その軸のタイルが全て失敗する）。
class DedicatedWayValueService(Protocol):
    """way_id→動的値配信の実装が満たす形（ルーターが使うのはこれだけ）。"""

    material_id: str

    async def get_way_values(
        self, z: int, x: int, y: int, at: datetime | None, bearing_deg: float | None, speed_kmh: float | None = None
    ) -> dict[str, float]: ...


DedicatedWayValueServiceFactory = Callable[[RoadGraphRepository, WeatherService], DedicatedWayValueService]

# 各サービスは担当する材料を`material_ids`で宣言し、`build`は組み立てる材料を`material_id`で受け取る
# （1つの実装が同じ計算の材料群——雨の窓の長さ違い等——をまとめて担当できる）。
_DEDICATED_WAY_VALUE_SERVICES = (
    WindWayService,
    GradientWayService,
    RainWayService,
)


def _factories_by_material(services) -> dict[str, DedicatedWayValueServiceFactory]:
    """材料id→サービスの組み立て。1つの材料を2つのサービスが担当していたら起動時に落とす
    ——どちらを選ぶかを黙って決めない。"""
    factories: dict[str, DedicatedWayValueServiceFactory] = {}
    for service in services:
        for material_id in service.material_ids:
            if material_id in factories:
                raise RuntimeError(
                    f"material '{material_id}' is served by more than one dedicated way value service"
                )
            factories[material_id] = partial(service.build, material_id=material_id)
    return factories


_DEDICATED_WAY_VALUE_SERVICE_FACTORIES = _factories_by_material(_DEDICATED_WAY_VALUE_SERVICES)


def served_dedicated_way_value_material(materials: Iterable[str]) -> str | None:
    """軸が参照する材料のうち、way_id→値の配信を実装している材料。ちょうど1つのときだけ返す。

    0件なら配信する値が無い。2件以上は、1つのサービスが1つの材料の値しか返さないため
    その軸を評価しきれない。どちらも「実装が無い」として扱う（書き込み時の検証が拒否し、
    配信側は404）。
    """
    served = {material for material in materials if material in _DEDICATED_WAY_VALUE_SERVICE_FACTORIES}
    return next(iter(served)) if len(served) == 1 else None


def _dedicated_way_value_factory(axis_id: str) -> DedicatedWayValueServiceFactory | None:
    if axis_id not in dedicated_way_value_axes():
        return None
    material = served_dedicated_way_value_material(AXIS_DEFINITIONS[axis_id].materials)
    return None if material is None else _DEDICATED_WAY_VALUE_SERVICE_FACTORIES[material]


async def get_dedicated_way_value_service(
    axis_id: str,
    weather_service: WeatherService = Depends(get_weather_service),
):
    """way_id→動的値配信層の、軸id駆動な単一の注入点。

    `axis_id`はパスパラメータで、ルーター側と同名でなければFastAPIが解決できない。
    router側で軸ごとのサービスをそれぞれ`Depends`するとリクエストごとにDBセッションが
    重複して開くため、この関数自体が分岐して1セッションで済ませる。配信できない`axis_id`には
    Noneを返し、呼び出し元が404を返す。
    """
    factory = _dedicated_way_value_factory(axis_id)
    if factory is None:
        yield None
        return

    async with get_session_factory()() as session:
        yield factory(RoadGraphRepository(session), weather_service)


async def directional_materials(
    osm_way_id: int,
    feature_key: str | None,
    z: int | None,
    x: int | None,
    y: int | None,
    at: datetime | None,
    bearing_deg: float | None,
    speed_kmh: float | None,
) -> dict[str, float]:
    """専用配信の材料（進行方向に依存する勾配・風、観測で変わる雨等）を、指定された条件でまとめて引く。

    進行方向に依存する材料は**1本の道が往復2方向で値が違う**ため、方向が決まらないと算出できない。方向・時刻・
    想定速度が揃った軸だけを引き、揃わない軸は黙って飛ばす（呼び出し側では「データなし」
    になる）。

    **軸を名指ししない**——`dedicated_way_value_axes()`の宣言を回し、その軸が必要とする
    ものが揃っているかで判断する。軸が増えてもここは変わらない。同じ材料を参照する軸が
    複数あっても、材料ごとに1回だけ引く。

    値は地図のレンズが引くのと同じ経路（同じキャッシュ）から取るので、**地図の色と
    内訳が一致する**。
    """
    if z is None or x is None or y is None:
        return {}
    wanted: dict[str, DedicatedWayValueServiceFactory] = {}
    for axis_id, axis in dedicated_way_value_axes().items():
        if (axis.needs_bearing and bearing_deg is None) or (axis.needs_speed and speed_kmh is None):
            continue
        material = served_dedicated_way_value_material(AXIS_DEFINITIONS[axis_id].materials)
        if material is not None:
            wanted[material] = _DEDICATED_WAY_VALUE_SERVICE_FACTORIES[material]
    if not wanted:
        return {}

    weather_service = get_weather_service()
    key = feature_key or str(osm_way_id)

    found: dict[str, float] = {}
    async with get_session_factory()() as session:
        repository = RoadGraphRepository(session)
        for material, factory in wanted.items():
            values = await factory(repository, weather_service).get_way_values(z, x, y, at, bearing_deg, speed_kmh)
            if key in values:
                found[material] = values[key]
    return found


async def get_accident_service():
    async with get_session_factory()() as session:
        yield AccidentService(repository=AccidentTileQuery(session))


def get_basemap_client():
    return BasemapClient(get_http_client(15.0), settings.basemap_public_base_url)


def get_jma_tile_client():
    return JmaTileClient(get_http_client(15.0))


#: 整備区域外の記憶。クライアントはリクエストごとに作られるため、プロセスの側で持つ。
_gsi_not_found_paths: LRUCache = LRUCache(maxsize=NOT_FOUND_MAX_ENTRIES)


def get_gsi_tile_client():
    return GsiTileClient(get_http_client(15.0), _gsi_not_found_paths)


# 以下の管理API向けのうち、書き込み・1テーブル読みで足りるものはタイル配信と同じ
# セッション工場を使い、全表走査を伴う集計はルート生成用の長いcommand_timeoutを使う
# （短い方だと集計が最後まで走らずキャンセルされる）。
async def get_axis_registry_admin_service():
    async with get_session_factory()() as session:
        yield AxisRegistryAdminService(AxisDefinitionRepository(session))


async def get_tuning_session():
    async with get_session_factory()() as session:
        yield session


async def get_material_coverage_service():
    async with get_route_generation_session_factory()() as session:
        yield MaterialCoverageService(MaterialCoverageQuery(session))


async def get_db_status_service():
    async with get_route_generation_session_factory()() as session:
        yield DbStatusService(DbStatusQuery(session))


async def get_derived_data_freshness_service():
    async with get_route_generation_session_factory()() as session:
        yield DerivedDataFreshnessService(DerivedDataFreshnessQuery(session))
