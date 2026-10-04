"""`infrastructure/dynamic_way_value_cache.py`——路面タイルのフィーチャーごとの値のディスクキャッシュ
（`set_tile_values`・`get_tile_values`）と、向きの丸め（`bearing_bucket`）。

置き場は`tests/conftest.py`のautouseがテストごとの空の一時ディレクトリへ差し替える。

ここで見ないもの:
- 置き場の読み書きに失敗したときに未キャッシュへ倒すこと・失効（TTLは置き場へそのまま渡す） → `test_tile_persistent_cache.py`
- どの材料をキャッシュし、どの世代・署名・TTLを渡すか → 材料のサービスのテスト（例: `test_gradient_way_service.py`）
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.infrastructure.dynamic_way_value_cache import (
    BEARING_BUCKET_DEG,
    bearing_bucket,
    get_tile_values,
    set_tile_values,
)

VALUES = {"way-1": 3.5, "way-2": -1.0}
KEY = {"material_id": "material_a", "z": 14, "x": 14550, "y": 6451}
VERSIONS = {"surface_tile_version": "tiles-1", "value_shape": "shape-1"}
HALF_BUCKET = BEARING_BUCKET_DEG / 2


async def store(bearing_deg: float = 0.0) -> None:
    await set_tile_values(**KEY, bearing_deg=bearing_deg, values=VALUES, ttl_seconds=3600, **VERSIONS)


async def test_a_tile_whose_features_all_came_out_without_a_value_is_remembered_as_empty():
    """空も計算の結果で、未キャッシュと取り違えると値の無いタイルを毎回計算し直す。"""
    await set_tile_values(**KEY, bearing_deg=0.0, values={}, ttl_seconds=3600, **VERSIONS)

    assert await get_tile_values(**KEY, bearing_deg=0.0, **VERSIONS) == {}


@pytest.mark.parametrize(
    "other",
    [
        {"material_id": "material_b"},
        {"z": 15},
        {"x": 14551},
        {"y": 6452},
        # 路面タイルを作り直すとフィーチャーの鍵が変わり、前の世代の値はどの地物にも一致しない。
        {"surface_tile_version": "tiles-2"},
        # 材料の計算を変えたデプロイの後は、前の作り方の値を読まない。
        {"value_shape": "shape-2"},
        {"bearing_deg": BEARING_BUCKET_DEG},
    ],
)
async def test_a_read_that_differs_in_any_part_of_the_key_does_not_see_the_stored_values(other):
    await store()

    request = {**KEY, "bearing_deg": 0.0, **VERSIONS, **other}

    assert await get_tile_values(**request) is None


async def test_a_nearby_heading_reads_the_values_stored_for_the_same_bucket():
    """コンパスを少し回しただけでは、同じタイルを計算し直さない。"""
    await store(bearing_deg=0.0)

    assert await get_tile_values(**KEY, bearing_deg=HALF_BUCKET - 0.01, **VERSIONS) == VALUES


@pytest.mark.parametrize(
    ("bearing_deg", "bucket"),
    [
        # 境界ちょうどは上のバケットへ。偶数への丸めだと、境界ごとに上下が入れ替わり幅が揃わない。
        (HALF_BUCKET, 1),
        (360.0 - HALF_BUCKET, 0),
    ],
)
def test_a_heading_on_a_bucket_edge_goes_to_the_bucket_above(bearing_deg, bucket):
    assert bearing_bucket(bearing_deg) == bucket


@given(st.floats(min_value=-720.0, max_value=720.0))
def test_a_heading_is_never_further_than_half_a_bucket_from_its_bucket(bearing_deg):
    """キャッシュから返る値は、要求した向きと最大で半バケットずれた向きで計算したもの。"""
    center = bearing_bucket(bearing_deg) * BEARING_BUCKET_DEG
    gap = abs((bearing_deg - center + 180.0) % 360.0 - 180.0)

    assert gap <= HALF_BUCKET + 1e-9
