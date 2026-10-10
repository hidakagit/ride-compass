"""タイル内のフィーチャーの値をDBから引く（鍵ごとの値を配る配信サービスが共有する）。"""

from collections.abc import Awaitable, Sized
from typing import Any, TypeVar

import numpy as np

from app.domain.region import BoundingBox
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.infrastructure.debug_log import mark_failed
from app.infrastructure.road_graph_repository import RoadGraphRepository

Features = TypeVar("Features", bound=Sized)


async def tile_features(read: Awaitable[Features | None], fields: dict[str, Any]) -> Features | None:
    """タイル内のフィーチャーの値（鍵→値・フィーチャーごとの材料）を読む。

    DB障害・取込範囲外・フィーチャーが無いタイルは None（どれだったかは`fields`へ記録する）。
    """
    try:
        features = await read
    except DB_UNAVAILABLE_ERRORS as exc:
        mark_failed(fields, exc)
        return None
    if not features:
        fields["postgis"] = "uncovered" if features is None else "empty"
        return None
    fields["feature_count"] = len(features)
    return features


async def feature_midpoint_arrays(
    repository: RoadGraphRepository, z: int, x: int, y: int, bbox: BoundingBox, fields: dict[str, Any],
) -> tuple[list[str], np.ndarray, np.ndarray] | None:
    """鍵の並びと、同じ並びの緯度・経度の配列を返す。

    DB障害・取込範囲外・フィーチャーが無いタイルは None（どれだったかは`fields`へ記録する）。
    """
    midpoints = await tile_features(repository.get_feature_midpoints_in_tile(z, x, y, bbox), fields)
    if midpoints is None:
        return None
    keys = list(midpoints)
    latitudes = np.array([midpoints[key][0] for key in keys], dtype=float)
    longitudes = np.array([midpoints[key][1] for key in keys], dtype=float)
    return keys, latitudes, longitudes
