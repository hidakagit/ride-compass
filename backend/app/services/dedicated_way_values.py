"""地図の配信: 公開軸の値を、タイルのフィーチャーごとに探索と同じ評価から配る。

値はタイルの材料（`services/feature_materials.py: FeatureMaterialService`）と、軸の葉の材料のうちタイルへ焼けない材料
（時々刻々変わる・向きに依る）を配るサービスの値から、`domain/dynamic_way_values.py: paint_feature_values`で求める。

**軸を名指ししない**——各サービスは自分が返す材料（`material_id`）だけを宣言し、軸との対応は軸の葉の材料から都度引く。
軸はDBの行で増減する（公開済みの軸は複製で改良する）ため、実装が軸の名前を持つと複製した軸が配信されない。
サービスごとにコンストラクタ依存が違うため、生成は`build`の統一シグネチャ越しに行う。
"""

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence, TypeVar, cast

import numpy as np

from app.domain.attributes import MaterialColumn
from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, copy_axis_definitions
from app.domain.dynamic_way_values import (
    FeatureMaterials,
    FeatureSegments,
    MissingConditions,
    WayValueConditionName,
    WayValueQuery,
    assemble_conditions,
    axis_with_dependencies,
    folds_segments,
    leaf_materials,
    paint_feature_values,
    paint_folded_feature_values,
)
from app.domain.material_catalog import segment_material_ids
from app.domain.region import EDGE_UNIT_MIN_ZOOM
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.feature_materials import FeatureMaterialService
from app.services.gradient_way_service import GradientWayService
from app.services.rain_way_service import RainWayService
from app.services.weather_service import WeatherService
from app.services.wind_way_service import WindWayService


_Conditions = TypeVar("_Conditions")


class DedicatedWayValueService(Protocol[_Conditions]):
    """タイルへ焼けない材料をフィーチャーごとに配る実装が満たす形（地図のレンズと区間インスペクタが使う）。

    `get_way_values`は`conditions_type`の値だけを受け取る。要求からの組み立ては
    `domain/dynamic_way_values.py: assemble_conditions`が行い、要る条件が欠けていれば組み立てない。
    """

    material_id: str
    conditions_type: type[_Conditions]

    async def get_way_values(self, z: int, x: int, y: int, conditions: _Conditions) -> Mapping[str, float | None]:
        """フィーチャーの鍵→値。Noneは、その道の値が走行方位で決まらないこと（値が無い道は鍵ごと除く）。"""
        ...


_SegmentConditions = TypeVar("_SegmentConditions", contravariant=True)


class SegmentValueService(Protocol[_SegmentConditions]):
    """区間ごとに値が違いうる材料（`domain/material_catalog.py: segment_material_ids`）を配る実装が、`DedicatedWayValueService`に
    加えて満たす形。道1本のフィーチャーの値を区間から畳むとき（`paint_folded_feature_values`）に、区間ごとの値を配る。"""

    def segment_values(self, segments: FeatureSegments, conditions: _SegmentConditions) -> np.ndarray:
        """`segments`の区間ごとの値（区間と同じ並び。値が無い・決まらない区間はNaN）。"""
        ...


class DedicatedWayValueServiceType(Protocol):
    """配信の実装のクラスが満たす形。担当する材料・受け取る条件の型・組み立てを持つ。"""

    @property
    def material_ids(self) -> tuple[str, ...]: ...

    @property
    def conditions_type(self) -> type: ...

    @property
    def undetermined_by_bearing(self) -> bool:
        """走行方位しだいで値の決まらない道（`get_way_values`のNone）を返しうるか。"""
        ...

    def build(
        self, repository: RoadGraphRepository, weather_service: WeatherService, material_id: str
    ) -> DedicatedWayValueService[Any]: ...


# 各サービスは担当する材料を`material_ids`で宣言し、`build`は組み立てる材料を`material_id`で受け取る
# （1つの実装が同じ計算の材料群——雨の窓の長さ違い等——をまとめて担当できる）。
DEDICATED_WAY_VALUE_SERVICES: tuple[DedicatedWayValueServiceType, ...] = (
    WindWayService,
    GradientWayService,
    RainWayService,
)


def services_by_material(
    services: Iterable[DedicatedWayValueServiceType],
) -> dict[str, DedicatedWayValueServiceType]:
    """材料id→担当するサービス。1つの材料を2つのサービスが担当していたら起動時に落とす
    ——どちらを選ぶかを黙って決めない。"""
    by_material: dict[str, DedicatedWayValueServiceType] = {}
    for service in services:
        for material_id in service.material_ids:
            if material_id in by_material:
                raise RuntimeError(
                    f"material '{material_id}' is served by more than one dedicated way value service"
                )
            by_material[material_id] = service
    # 区間ごとに値が違いうる材料を配るのに区間の値の口が無いと、道1本の値を区間から畳む軸の配信が要求のたびに落ちる。
    lacking = sorted(material_id for material_id, service in by_material.items()
                     if material_id in segment_material_ids() and not hasattr(service, "segment_values"))
    if lacking:
        raise RuntimeError(f"materials {lacking} vary by segment but their service has no segment_values")
    return by_material


_SERVICES_BY_MATERIAL = services_by_material(DEDICATED_WAY_VALUE_SERVICES)


def served_materials(axis_id: str, definitions: Mapping[str, AxisDefinition]) -> list[str]:
    """軸が内部軸まで辿って読む材料のうち、配信のサービスが値を配る材料（材料idの順）。"""
    leaves = leaf_materials(axis_with_dependencies(axis_id, definitions))
    return sorted(material for material in leaves if material in _SERVICES_BY_MATERIAL)


def _condition_names(kinds: Iterable[type]) -> list[WayValueConditionName]:
    """条件の型の欄の名前を、型の並び・欄の並びで重ねずに並べる。"""
    names = (cast(WayValueConditionName, field.name) for kind in kinds for field in fields(kind))
    return list(dict.fromkeys(names))


def _build_service(
    material: str, repository: RoadGraphRepository, weather_service: WeatherService
) -> DedicatedWayValueService[Any]:
    return _SERVICES_BY_MATERIAL[material].build(repository, weather_service, material)


#: 材料id→その材料の配信サービス。
MaterialServiceBuilder = Callable[[str], DedicatedWayValueService[Any]]


def material_service_builder(repository: RoadGraphRepository, weather_service: WeatherService) -> MaterialServiceBuilder:
    """材料ごとの配信サービスを、同じリポジトリ・気象サービスで組み立てる。"""
    return lambda material: _build_service(material, repository, weather_service)


async def way_values(
    service: DedicatedWayValueService[Any], z: int, x: int, y: int, query: WayValueQuery
) -> Mapping[str, float | None] | MissingConditions:
    """配信サービスが要る条件を`query`から組み、タイル内のフィーチャーの値を引く。要る条件が欠けていれば引かずに
    欠けた条件を返す（`assemble_conditions`）。区間インスペクタがこの口で引く。"""
    conditions = assemble_conditions(service.conditions_type, query)
    if isinstance(conditions, MissingConditions):
        return conditions
    return await service.get_way_values(z, x, y, conditions)


class FeatureMaterialSource(Protocol):
    """タイルのフィーチャーごとの材料を読む口（`services/feature_materials.py: FeatureMaterialService`）。"""

    async def materials(self, z: int, x: int, y: int) -> FeatureMaterials | None: ...

    async def segments(self, z: int, x: int, y: int) -> FeatureSegments | None: ...


class AxisWayValueLens:
    """地図のレンズが塗る、1つの軸の値（フィーチャーの鍵→値）。

    材料もサービスの値も軸に依らずに引き（キャッシュも材料のまま持つ）、地図が塗る値へは軸定義から都度求めるため、
    軸スタジオで折れ点を変えてもキャッシュを捨てずに即座に効く。
    """

    def __init__(
        self,
        axis_id: str,
        definitions: Mapping[str, AxisDefinition],
        feature_materials: FeatureMaterialSource,
        build_service: MaterialServiceBuilder,
    ):
        self._axis_id = axis_id
        self._definitions = definitions
        self._feature_materials = feature_materials
        self._build_service = build_service

    async def values(self, z: int, x: int, y: int, query: WayValueQuery) -> dict[str, float | None] | MissingConditions:
        """要る条件が欠けていれば、何も読まずに欠けた条件を返す。要る条件は、軸の葉の材料を配るサービスが受け取る
        条件の型を合わせたもの。

        葉の材料がどれも配信のサービスの材料なら、タイルの材料を読まずにサービスが値を返したフィーチャーだけを塗る。
        道1本を1つのフィーチャーにするズームで、区間から畳む軸（`folds_segments`）は、フィーチャーごとの区間の材料も読んで
        畳む（取込範囲外・DB障害は値なし）。
        """
        served_ids = served_materials(self._axis_id, self._definitions)
        services = {material: self._build_service(material) for material in served_ids}
        conditions = {material: assemble_conditions(service.conditions_type, query)
                      for material, service in services.items()}
        missing = [names for names in conditions.values() if isinstance(names, MissingConditions)]
        if missing:
            return MissingConditions(tuple(dict.fromkeys(name for names in missing for name in names.names)))
        served = {material: await service.get_way_values(z, x, y, conditions[material])
                  for material, service in services.items()}
        if leaf_materials(axis_with_dependencies(self._axis_id, self._definitions)) <= set(served_ids):
            feature_keys: Sequence[str] = list(dict.fromkeys(key for values in served.values() for key in values))
            materials: Mapping[str, MaterialColumn] = {}
        else:
            read = await self._feature_materials.materials(z, x, y)
            if read is None:
                return {}
            feature_keys, materials = read.feature_keys, read.columns
        if z >= EDGE_UNIT_MIN_ZOOM or not folds_segments(self._axis_id, self._definitions):
            return paint_feature_values(self._axis_id, self._definitions, feature_keys, materials, served)
        segments = await self._feature_materials.segments(z, x, y)
        if segments is None:
            return {}
        served_segments = {
            material: cast(SegmentValueService[Any], service).segment_values(segments, conditions[material])
            for material, service in services.items()
            if material in segment_material_ids()
        }
        return paint_folded_feature_values(
            self._axis_id, self._definitions, feature_keys, materials, served, segments, served_segments
        )


def axis_way_value_lens(
    axis_id: str, repository: RoadGraphRepository, weather_service: WeatherService
) -> AxisWayValueLens | None:
    """公開軸のレンズを組み立てる。軸は組み立てた時点の軸の集合で評価する。公開軸でなければNone。"""
    definitions = copy_axis_definitions()
    definition = definitions.get(axis_id)
    if definition is None or not definition.is_published:
        return None
    return AxisWayValueLens(
        axis_id, definitions, FeatureMaterialService(repository), material_service_builder(repository, weather_service)
    )


@dataclass(frozen=True)
class DedicatedWayValueLayer:
    """地図が軸の配信を要求するときに要るもの。"""

    #: 要求へ載せる条件の名前（クエリパラメータの名前と同じ）。載せるのは、軸の葉の材料を配るサービスが受け取る条件の
    #: 型の欄すべて——既定値のある欄（風の時刻）も載せる。省略できるのは配信が既定値で補えるというだけで、地図が
    #: 利用者の選んだ値を持っているならそれで求めた値を塗る。葉の材料にサービスの材料が無ければ空。
    conditions: list[WayValueConditionName]
    #: 配信が、走行方位しだいで値の決まらない道を返しうるか。
    undetermined_by_bearing: bool


def dedicated_way_value_layers() -> dict[str, DedicatedWayValueLayer]:
    """軸id → 地図が配信を要求するときに要るもの。今の`AXIS_DEFINITIONS`の全軸を持つ。"""
    definitions = copy_axis_definitions()
    out: dict[str, DedicatedWayValueLayer] = {}
    for axis_id in definitions:
        service_types = [_SERVICES_BY_MATERIAL[material] for material in served_materials(axis_id, definitions)]
        out[axis_id] = DedicatedWayValueLayer(
            conditions=_condition_names(service.conditions_type for service in service_types),
            undetermined_by_bearing=any(service.undetermined_by_bearing for service in service_types),
        )
    return out


class DirectionalMaterialService:
    """区間インスペクタが足す専用配信の材料（進行方向に依存する勾配・風、観測で変わる雨等）を引く。"""

    def __init__(self, build_service: MaterialServiceBuilder):
        self._build_service = build_service

    async def materials(
        self,
        osm_way_id: int,
        feature_key: str | None,
        z: int,
        x: int,
        y: int,
        at: datetime | None,
        bearing_deg: float,
        speed_kmh: float | None,
    ) -> dict[str, float]:
        """専用配信の材料を、指定された条件でまとめて引く。

        進行方向に依存する材料は**1本の道が往復2方向で値が違う**ため、方向が決まらないと算出できない。
        サービスが要る条件（`assemble_conditions`）が揃った材料だけを引き、揃わない材料と、その向きでは
        値が決まらない材料は飛ばす（呼び出し側では「データなし」になる）。

        **軸を名指ししない**——地図を配信で塗る印（`dedicated_way_value_layer`）の軸を回し、それぞれの葉の材料のうち
        サービスが配る材料を引く。軸が増えてもここは変わらない。同じ材料を参照する軸が複数あっても、材料ごとに1回だけ引く。

        値は地図のレンズが引くのと同じ経路（同じキャッシュ）から取るので、**地図の色と
        内訳が一致する**。
        """
        materials = {
            material
            for axis_id, definition in AXIS_DEFINITIONS.items()
            if definition.dedicated_way_value_layer
            for material in served_materials(axis_id, AXIS_DEFINITIONS)
        }
        query = WayValueQuery(at=at, bearing_deg=bearing_deg, speed_kmh=speed_kmh)

        key = feature_key or str(osm_way_id)
        found: dict[str, float] = {}
        for material in materials:
            values = await way_values(self._build_service(material), z, x, y, query)
            if isinstance(values, MissingConditions):
                continue
            value = values.get(key)
            if value is not None:
                found[material] = value
        return found
