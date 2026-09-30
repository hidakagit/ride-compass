"""way_id→動的値の配信を、軸が参照する材料から選んで組み立てる。

**軸を名指ししない**——各サービスは自分が返す材料（`material_id`）だけを宣言し、軸との対応は軸定義が参照する
材料から都度引く。軸はDBの行で増減する（公開済みの軸は複製で改良する）ため、実装が軸の名前を持つと複製した軸が
配信されない。サービスごとにコンストラクタ依存が違うため、生成は`build`の統一シグネチャ越しに行う。
軸スタジオは`dedicated_way_value_layer=true`の軸を宣言だけで作れるが、配信できる値はここに実装がある材料だけ
——実装の無い軸は未知のaxis_idと同じく404で返す（500にするとフロントの「データなし」フォールバックが効かず、
その軸のタイルが全て失敗する）。
"""

from datetime import datetime
from functools import partial
from typing import Callable, Iterable, Protocol

from app.domain.axis_definitions import AXIS_DEFINITIONS
from app.domain.dynamic_way_values import dedicated_way_value_axes
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.gradient_way_service import GradientWayService
from app.services.rain_way_service import RainWayService
from app.services.weather_service import WeatherService
from app.services.wind_way_service import WindWayService


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


def dedicated_way_value_factory(axis_id: str) -> DedicatedWayValueServiceFactory | None:
    """軸の配信を組み立てる工場。専用配信の軸でないか、配信できる材料が無ければNone。"""
    if axis_id not in dedicated_way_value_axes():
        return None
    material = served_dedicated_way_value_material(AXIS_DEFINITIONS[axis_id].materials)
    return None if material is None else _DEDICATED_WAY_VALUE_SERVICE_FACTORIES[material]


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

        key = feature_key or str(osm_way_id)
        found: dict[str, float] = {}
        for material, factory in wanted.items():
            values = await factory(self._repository, self._weather_service).get_way_values(
                z, x, y, at, bearing_deg, speed_kmh
            )
            if key in values:
                found[material] = values[key]
        return found
