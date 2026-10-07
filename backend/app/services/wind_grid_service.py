"""風・降水（MSM）の格子点マップの段取り: 対象範囲を読み、格子点を作り、格子点ぶんの時系列を読む。

格子を敷く範囲はサービスの対象範囲（取り込んだ道路の範囲、`RegionService.get_ingested_area`）で、点の作り方は
`domain/wind_grid.py`、時系列の読み出しは`WeatherService.get_wind_grid`が持つ。
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from app.domain.region import BoundingBox
from app.domain.route import Coordinates
from app.domain.wind_grid import (
    WIND_GRID_DETAIL_MAX_POINTS,
    WindGridResponse,
    count_wind_grid_detail_points,
    generate_wind_grid_detail_points,
    generate_wind_grid_points,
)
from app.infrastructure.debug_log import log_throttled_warning
from app.services.region_service import RegionService
from app.services.weather_service import WeatherService


class WindGridAreaUnavailable(Exception):
    """対象範囲を読めない（原因は`RegionService.get_ingested_area`がWARNINGで残す）。格子を組めない。"""


class WindGridUnavailable(Exception):
    """格子を読めない（MSMの同期が未完了・予報が現在時刻へ追いついていない等）。空の格子で返すと、画面は風が
    無いのと区別できない。"""


class WindGridTooLarge(Exception):
    """詳細格子の点が`WIND_GRID_DETAIL_MAX_POINTS`を超える。点を作る処理は同期でイベントループを止めるため、
    作る前に断る。"""


class WindGridService:
    """風・降水の格子点マップ。対象範囲は読む間だけ地域サービスを開く——時系列を読む間にDBの接続を持たない。"""

    def __init__(
        self,
        weather_service: WeatherService,
        open_region_service: Callable[[], AbstractAsyncContextManager[RegionService]],
    ):
        self._weather_service = weather_service
        self._open_region_service = open_region_service

    async def _area(self) -> BoundingBox:
        async with self._open_region_service() as region_service:
            area = await region_service.get_ingested_area()
        if area is None:
            raise WindGridAreaUnavailable
        return area

    async def _read(self, label: str, points: list[Coordinates]) -> WindGridResponse:
        grid = await self._weather_service.get_wind_grid(points)
        if grid is None:
            log_throttled_warning(f"weather:{label}", "%s: 格子を読めませんでした（MSM未同期の可能性）", label)
            raise WindGridUnavailable
        return grid

    async def get_grid(self) -> WindGridResponse:
        """対象範囲全体の固定格子点（`generate_wind_grid_points`）ぶんの時系列。"""
        return await self._read("wind-grid", generate_wind_grid_points(await self._area()))

    async def get_detail_grid(self, bbox: BoundingBox, spacing_deg: float) -> WindGridResponse:
        """`bbox`に交差する密格子点（`generate_wind_grid_detail_points`、間隔`spacing_deg`）ぶんの時系列。"""
        area = await self._area()
        if count_wind_grid_detail_points(area, bbox, spacing_deg) > WIND_GRID_DETAIL_MAX_POINTS:
            raise WindGridTooLarge
        return await self._read("wind-grid-detail", generate_wind_grid_detail_points(area, bbox, spacing_deg))
