"""フィーチャー→動的値の配信を、軸が参照する材料から選んで組み立てる。

**軸を名指ししない**——各サービスは自分が返す材料（`material_id`）だけを宣言し、軸との対応は軸定義が参照する
材料から都度引く。軸はDBの行で増減する（公開済みの軸は複製で改良する）ため、実装が軸の名前を持つと複製した軸が
配信されない。サービスごとにコンストラクタ依存が違うため、生成は`build`の統一シグネチャ越しに行う。
軸スタジオは`dedicated_way_value_layer=true`の軸を宣言だけで作れるが、配信できる値はここに実装がある材料だけ
——実装の無い軸は未知のaxis_idと同じく404で返す（500にするとフロントの「データなし」フォールバックが効かず、
その軸のタイルが全て失敗する）。
"""

from dataclasses import fields
from datetime import datetime
from functools import partial
from typing import Any, Callable, Iterable, Protocol, TypeVar, cast

from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.dynamic_way_values import (
    MissingConditions,
    WayValueConditionName,
    WayValueQuery,
    assemble_conditions,
)
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.gradient_way_service import GradientWayService
from app.services.rain_way_service import RainWayService
from app.services.weather_service import WeatherService
from app.services.wind_way_service import WindWayService


_Conditions = TypeVar("_Conditions")


class DedicatedWayValueService(Protocol[_Conditions]):
    """フィーチャー→動的値配信の実装が満たす形（ルーターが使うのはこれだけ）。

    `get_way_values`は`conditions_type`の値だけを受け取る。要求からの組み立ては
    `domain/dynamic_way_values.py: assemble_conditions`が行い、要る条件が欠けていれば組み立てない。
    """

    material_id: str
    conditions_type: type[_Conditions]

    async def get_way_values(self, z: int, x: int, y: int, conditions: _Conditions) -> dict[str, float]: ...


DedicatedWayValueServiceFactory = Callable[[RoadGraphRepository, WeatherService], DedicatedWayValueService[Any]]


class DedicatedWayValueServiceType(Protocol):
    """配信の実装のクラスが満たす形。担当する材料・受け取る条件の型・組み立てを持つ。"""

    @property
    def material_ids(self) -> tuple[str, ...]: ...

    @property
    def conditions_type(self) -> type: ...

    def build(
        self, repository: RoadGraphRepository, weather_service: WeatherService, material_id: str
    ) -> DedicatedWayValueService[Any]: ...


# 各サービスは担当する材料を`material_ids`で宣言し、`build`は組み立てる材料を`material_id`で受け取る
# （1つの実装が同じ計算の材料群——雨の窓の長さ違い等——をまとめて担当できる）。
_DEDICATED_WAY_VALUE_SERVICES: tuple[DedicatedWayValueServiceType, ...] = (
    WindWayService,
    GradientWayService,
    RainWayService,
)


def _services_by_material(
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


_DEDICATED_WAY_VALUE_SERVICES_BY_MATERIAL = _services_by_material(_DEDICATED_WAY_VALUE_SERVICES)


def served_dedicated_way_value_material(materials: Iterable[str]) -> str | None:
    """軸が参照する材料のうち、フィーチャー→値の配信を実装している材料。ちょうど1つのときだけ返す。

    0件なら配信する値が無い。2件以上は、1つのサービスが1つの材料の値しか返さないため
    その軸を評価しきれない。どちらも「実装が無い」として扱う（書き込み時の検証が拒否し、
    配信側は404）。
    """
    served = {material for material in materials if material in _DEDICATED_WAY_VALUE_SERVICES_BY_MATERIAL}
    return next(iter(served)) if len(served) == 1 else None


def _served_material_of(axis_id: str) -> str | None:
    """専用配信を持つ軸（`dedicated_way_value_layer`）が配信を実装した材料を参照していれば、その材料。"""
    definition = AXIS_DEFINITIONS.get(axis_id)
    if definition is None or not definition.dedicated_way_value_layer:
        return None
    return served_dedicated_way_value_material(definition.materials)


def _factory_of(material: str) -> DedicatedWayValueServiceFactory:
    return partial(_DEDICATED_WAY_VALUE_SERVICES_BY_MATERIAL[material].build, material_id=material)


def dedicated_way_value_factory(axis_id: str) -> DedicatedWayValueServiceFactory | None:
    """軸の配信を組み立てる工場。専用配信の軸でないか、配信できる材料が無ければNone。"""
    material = _served_material_of(axis_id)
    return None if material is None else _factory_of(material)


def dedicated_way_value_conditions(axis_id: str) -> list[WayValueConditionName]:
    """地図がこの軸の配信の要求へ載せる条件の名前（クエリパラメータの名前と同じ）。

    載せるのは、配信サービスが受け取る条件の型の欄すべて——既定値のある欄（風の時刻）も載せる。
    省略できるのは配信が既定値で補えるというだけで、地図が利用者の選んだ値を持っているなら
    それで求めた値を塗る。専用配信の軸でないか、配信できる材料が無ければ空。
    """
    material = _served_material_of(axis_id)
    if material is None:
        return []
    conditions_type = _DEDICATED_WAY_VALUE_SERVICES_BY_MATERIAL[material].conditions_type
    return [cast(WayValueConditionName, field.name) for field in fields(conditions_type)]


class DirectionalMaterialService:
    """区間インスペクタが足す専用配信の材料（進行方向に依存する勾配・風、観測で変わる雨等）を引く。"""

    def __init__(self, repository: RoadGraphRepository, weather_service: WeatherService):
        self._repository = repository
        self._weather_service = weather_service

    async def materials(
        self,
        osm_way_id: int,
        feature_key: str | None,
        z: int | None,
        x: int | None,
        y: int | None,
        at: datetime | None,
        bearing_deg: float | None,
        speed_kmh: float | None,
    ) -> dict[str, float]:
        """専用配信の材料を、指定された条件でまとめて引く。

        進行方向に依存する材料は**1本の道が往復2方向で値が違う**ため、方向が決まらないと算出できない。
        サービスが要る条件（`assemble_conditions`）が揃った材料だけを引き、揃わない材料は飛ばす
        （呼び出し側では「データなし」になる）。

        **軸を名指ししない**——専用配信を持つ軸を回し、それぞれが参照する材料を引く。軸が増えても
        ここは変わらない。同じ材料を参照する軸が複数あっても、材料ごとに1回だけ引く。

        値は地図のレンズが引くのと同じ経路（同じキャッシュ）から取るので、**地図の色と
        内訳が一致する**。
        """
        if z is None or x is None or y is None:
            return {}
        materials = {material for material in map(_served_material_of, AXIS_DEFINITIONS) if material is not None}
        query = WayValueQuery(at=at, bearing_deg=bearing_deg, speed_kmh=speed_kmh)

        key = feature_key or str(osm_way_id)
        found: dict[str, float] = {}
        for material in materials:
            service = _factory_of(material)(self._repository, self._weather_service)
            conditions = assemble_conditions(service.conditions_type, query)
            if isinstance(conditions, MissingConditions):
                continue
            values = await service.get_way_values(z, x, y, conditions)
            if key in values:
                found[material] = values[key]
        return found
