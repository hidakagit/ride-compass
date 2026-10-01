"""`infrastructure/dynamic_way_value_cache.py`——動的かつ向きに依存する材料の、タイル単位の
値を配るディスクキャッシュ。

ここで見ないもの:
- ディスクへの読み書き・容量上限・世代の掃除 → `test_tile_persistent_cache.py`
- 勾配の値そのものの作り方と、キャッシュを挟む制御フロー → `test_gradient_way_service.py`

**鍵は外から見えないため、書いてから読んで確かめる。** 観測できるのは「同じ鍵なら戻る／
違う鍵なら戻らない」だけで、鍵のタプルを並べて突き合わせるのは宣言の書き写しになる。
保存先はテストごとのtmpディレクトリ（`conftest.py`のautouseフィクスチャ）。
"""

import pytest

from app.infrastructure import dynamic_way_value_cache
from app.infrastructure.dynamic_way_value_cache import BEARING_BUCKET_DEG, bearing_bucket

MATERIAL = "material_a"
TILE = (14, 1000, 2000)
BEARING = 90.0
SURFACE_TILE_VERSION = "7.3-surface"
VALUE_SHAPE = "shape-1"
TTL_SECONDS = 60
VALUES = {"edge-1": 3.2, "edge-2": -1.5}


async def _put(
    *, material=MATERIAL, tile=TILE, bearing=BEARING, version=SURFACE_TILE_VERSION, value_shape=VALUE_SHAPE,
    values=VALUES,
):
    z, x, y = tile
    await dynamic_way_value_cache.set_tile_values(
        material, z, x, y, None, bearing, values, TTL_SECONDS, surface_tile_version=version, value_shape=value_shape
    )


async def _get(
    *, material=MATERIAL, tile=TILE, bearing=BEARING, version=SURFACE_TILE_VERSION, value_shape=VALUE_SHAPE
):
    z, x, y = tile
    return await dynamic_way_value_cache.get_tile_values(
        material, z, x, y, None, bearing, surface_tile_version=version, value_shape=value_shape
    )


class TestRoundTrip:
    async def test_what_was_stored_comes_back(self):
        await _put()

        assert await _get() == VALUES

    async def test_a_tile_nobody_computed_reads_as_nothing(self):
        assert await _get() is None

    async def test_a_tile_whose_features_all_came_out_valueless_is_remembered_as_empty(self):
        """未計算と同じ「なし」へ畳むと、値を持たないタイルだけがパンのたびにDBを引き直す。"""
        await _put(values={})

        assert await _get() == {}


class TestWhatMakesEntriesDifferent:
    @pytest.mark.parametrize(("stored", "asked"), [("7.3-surface", "8.3-surface"), ("x-surface", "7.3-surface"),
                                                   ("7.3-surface", "7.3-rebaked")])
    async def test_another_surface_tile_version_does_not_read_this_one(self, stored, asked):
        """鍵の中身は路面タイルの`feature_key`で、路面タイルの世代をまたぐとどの地物にも一致しない
        （バッチの作り直し・焼き方を変えたデプロイのどちらでも）。フロントは色を当てる先を失い、
        TTLが切れるまで静かに塗られないままになる。世代がまだ読めていない間に書いたものも同じ。
        """
        await _put(version=stored)

        assert await _get(version=asked) is None

    async def test_changing_how_one_material_is_computed_drops_only_that_materials_entries(self):
        """材料の計算を変えたデプロイの後、その材料は前の計算の値を配らず、他の材料は作り直さない。
        作り方の署名が鍵に無いと、DBの世代もタイルの形も動かないため、前の計算の値がTTLの間返り続ける。
        """
        await _put(material="material_a", value_shape="a-1")
        await _put(material="material_b", value_shape="b-1", values={"edge-9": 0.5})

        assert await _get(material="material_a", value_shape="a-2") is None
        assert await _get(material="material_b", value_shape="b-1") == {"edge-9": 0.5}

    async def test_another_material_does_not_read_this_one(self):
        await _put()

        assert await _get(material="material_b") is None

    @pytest.mark.parametrize("tile", [(15, 1000, 2000), (14, 1001, 2000), (14, 1000, 2001)])
    async def test_another_tile_does_not_read_this_one(self, tile):
        await _put()

        assert await _get(tile=tile) is None

    async def test_a_bearing_in_the_same_bucket_reads_the_same_entry(self):
        """生の方位を鍵にすると、コンパスを1度動かすたびに引き直しになりヒット率がほぼ0になる。"""
        await _put(bearing=BEARING)

        assert await _get(bearing=BEARING + BEARING_BUCKET_DEG / 4) == VALUES

    async def test_a_bearing_in_another_bucket_does_not(self):
        """勾配は進行方向で符号が変わる。別の向きの値を配ると、下りの道が登りの色で出る。"""
        await _put(bearing=BEARING)

        assert await _get(bearing=BEARING + BEARING_BUCKET_DEG) is None


class TestBearingBuckets:
    @pytest.mark.parametrize(("bearing", "same_as"), [(360.0, 0.0), (-10.0, 350.0), (710.0, 350.0)])
    def test_a_bearing_outside_one_turn_reads_as_the_same_direction(self, bearing, same_as):
        """地図が渡す方位は一周を越えることも負になることもある。別のバケットへ落ちると、
        同じ向きを向いているのに値を取り直す。
        """
        assert bearing_bucket(bearing) == bearing_bucket(same_as)

    def test_the_last_half_bucket_wraps_round_to_the_first(self):
        """丸めた先が一周を越えるため、折り返さないと北向きだけ鍵が2つに割れる。"""
        assert bearing_bucket(360 - BEARING_BUCKET_DEG / 2) == bearing_bucket(0.0)

    def test_the_bucket_boundary_rounds_a_half_upwards(self):
        """半分を偶数側へ倒すと、バケットの幅が5度と10度で交互になる。"""
        half = BEARING_BUCKET_DEG / 2

        assert bearing_bucket(half) == 1
        assert bearing_bucket(half - 0.1) == 0
