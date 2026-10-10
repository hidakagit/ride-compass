"""タイル内のフィーチャーの中ほどを、鍵と緯度・経度の配列で引く（地点の値を引く配信サービスが共有する）。"""

from typing import Any

import numpy as np

from app.domain.region import BoundingBox
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.infrastructure.debug_log import mark_failed
from app.infrastructure.road_graph_repository import RoadGraphRepository


async def feature_midpoint_arrays(
    repository: RoadGraphRepository, z: int, x: int, y: int, bbox: BoundingBox, fields: dict[str, Any],
) -> tuple[list[str], np.ndarray, np.ndarray] | None:
    """鍵の並びと、同じ並びの緯度・経度の配列を返す。

    DB障害・取込範囲外・フィーチャーが無いタイルは None（どれだったかは`fields`へ記録する）。
    """
    try:
        midpoints = await repository.get_feature_midpoints_in_tile(z, x, y, bbox)
    except DB_UNAVAILABLE_ERRORS as exc:
        mark_failed(fields, exc)
        return None
    if not midpoints:
        fields["postgis"] = "uncovered" if midpoints is None else "empty"
        return None
    fields["feature_count"] = len(midpoints)
    keys = list(midpoints)
    latitudes = np.array([midpoints[key][0] for key in keys], dtype=float)
    longitudes = np.array([midpoints[key][1] for key in keys], dtype=float)
    return keys, latitudes, longitudes
