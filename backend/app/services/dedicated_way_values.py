"""フィーチャー→動的値の配信を、軸が参照する材料から選んで組み立てる。

**軸を名指ししない**——各サービスは自分が返す材料（`material_id`）だけを宣言し、軸との対応は軸定義が参照する
材料から都度引く。軸はDBの行で増減する（公開済みの軸は複製で改良する）ため、実装が軸の名前を持つと複製した軸が
配信されない。サービスごとにコンストラクタ依存が違うため、生成は`build`の統一シグネチャ越しに行う。
軸スタジオは`dedicated_way_value_layer=true`の軸を宣言だけで作れるが、配信できる値はここに実装がある材料だけ
——実装の無い軸は未知のaxis_idと同じく404で返す（500にするとフロントの「データなし」フォールバックが効かず、
その軸のタイルが全て失敗する）。
"""

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Protocol, TypeVar, cast

from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.dynamic_way_values import (
    MissingConditions,
    WayValueConditionName,
    WayValueQuery,
    assemble_conditions,
    transform_dedicated_way_values,
)
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.gradient_way_service import GradientWayService
from app.services.rain_way_service import RainWayService
from app.services.weather_service import WeatherService
from app.services.wind_way_service import WindWayService


_Conditions = TypeVar("_Conditions")


class DedicatedWayValueService(Protocol[_Conditions]):
    """フィーチャー→動的値配信の実装が満たす形（地図のレンズと区間インスペクタは`way_values`越しに使う）。

    `get_way_values`は`conditions_type`の値だけを受け取る。要求からの組み立ては
    `domain/dynamic_way_values.py: assemble_conditions`が行い、要る条件が欠けていれば組み立てない。
    """

    material_id: str
    conditions_type: type[_Conditions]

    async def get_way_values(self, z: int, x: int, y: int, conditions: _Conditions) -> Mapping[str, float | None]:
        """フィーチャーの鍵→値。Noneは、その道の値が走行方位で決まらないこと（値が無い道は鍵ごと除く）。"""
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
    return by_material


_SERVICES_BY_MATERIAL = services_by_material(DEDICATED_WAY_VALUE_SERVICES)


def served_dedicated_way_value_material(materials: Iterable[str]) -> str | None:
    """軸が参照する材料のうち、フィーチャー→値の配信を実装している材料。ちょうど1つのときだけ返す。

    0件なら配信する値が無い。2件以上は、1つのサービスが1つの材料の値しか返さないため
    その軸を評価しきれない。どちらも「実装が無い」として扱う（書き込み時の検証が拒否し、
    配信側は404）。
    """
    served = {material for material in materials if material in _SERVICES_BY_MATERIAL}
    return next(iter(served)) if len(served) == 1 else None


def _served_material_of(axis_id: str) -> str | None:
    """専用配信を持つ軸（`dedicated_way_value_layer`）が配信を実装した材料を参照していれば、その材料。"""
    definition = AXIS_DEFINITIONS.get(axis_id)
    if definition is None or not definition.dedicated_way_value_layer:
        return None
    return served_dedicated_way_value_material(definition.materials)


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
    欠けた条件を返す（`assemble_conditions`）。地図のレンズと区間インスペクタが同じこの口で引く。"""
    conditions = assemble_conditions(service.conditions_type, query)
    if isinstance(conditions, MissingConditions):
        return conditions
    return await service.get_way_values(z, x, y, conditions)


class AxisWayValueLens:
    """地図のレンズが塗る、1つの軸の値（フィーチャーの鍵→値）。

    配信サービスは材料の生値を返し、キャッシュも生値のまま持つ。地図が塗る値（難易度か符号付き材料か）への
    変換は軸定義から都度行うため、軸スタジオで折れ点を変えてもキャッシュを捨てずに即座に効く。
    """

    def __init__(self, axis_id: str, service: DedicatedWayValueService[Any]):
        self._axis_id = axis_id
        self._service = service

    async def values(self, z: int, x: int, y: int, query: WayValueQuery) -> dict[str, float | None] | MissingConditions:
        raw = await way_values(self._service, z, x, y, query)
        if isinstance(raw, MissingConditions):
            return raw
        return transform_dedicated_way_values(AXIS_DEFINITIONS[self._axis_id], self._service.material_id, raw)


def axis_way_value_lens(
    axis_id: str, repository: RoadGraphRepository, weather_service: WeatherService
) -> AxisWayValueLens | None:
    """軸のレンズを組み立てる。専用配信の軸でないか、配信できる材料が無ければNone。"""
    material = _served_material_of(axis_id)
    return None if material is None else AxisWayValueLens(axis_id, _build_service(material, repository, weather_service))


@dataclass(frozen=True)
class DedicatedWayValueLayer:
    """地図が軸の専用配信を要求するときに要るもの。"""

    #: 要求へ載せる条件の名前（クエリパラメータの名前と同じ）。載せるのは配信サービスが受け取る条件の型の欄すべて
    #: ——既定値のある欄（風の時刻）も載せる。省略できるのは配信が既定値で補えるというだけで、地図が利用者の選んだ
    #: 値を持っているならそれで求めた値を塗る。専用配信の軸でないか、配信できる材料が無ければ空。
    conditions: list[WayValueConditionName]
    #: 配信が、走行方位しだいで値の決まらない道を返しうるか。専用配信の軸でなければFalse。
    undetermined_by_bearing: bool


def dedicated_way_value_layers() -> dict[str, DedicatedWayValueLayer]:
    """軸id → 地図が専用配信を要求するときに要るもの。今の`AXIS_DEFINITIONS`の全軸を持つ。"""
    out: dict[str, DedicatedWayValueLayer] = {}
    for axis_id in AXIS_DEFINITIONS:
        material = _served_material_of(axis_id)
        service = None if material is None else _SERVICES_BY_MATERIAL[material]
        out[axis_id] = DedicatedWayValueLayer(
            conditions=[] if service is None else [
                cast(WayValueConditionName, field.name) for field in fields(service.conditions_type)
            ],
            undetermined_by_bearing=service is not None and service.undetermined_by_bearing,
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

        **軸を名指ししない**——専用配信を持つ軸を回し、それぞれが参照する材料を引く。軸が増えても
        ここは変わらない。同じ材料を参照する軸が複数あっても、材料ごとに1回だけ引く。

        値は地図のレンズが引くのと同じ経路（同じキャッシュ）から取るので、**地図の色と
        内訳が一致する**。
        """
        materials = {material for material in map(_served_material_of, AXIS_DEFINITIONS) if material is not None}
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
