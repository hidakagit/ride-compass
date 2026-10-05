"""`domain/landcover.py`——道の周りの土地被覆の画素数を、クラスごとの割合へ変える。

入口は次のとおり。
- `class_percentages_sql`: 区間ごとのクラス別の画素数から割合の行を返すSQL（PostGISで実行して確かめる）
- `LandcoverPercentages`: その行を受け取るモデル
- `raster_set_fingerprint`: 開いているラスタの構成の指紋
- `LANDCOVER_CLASSES`: クラスの宣言（凡例・区間インスペクタ・集計が読む）。型でも導出でも保証できない不変条件だけを見る

ここで見ないもの:
- 道の周りの帯から画素を数えること → `test_derive_landcover.py`
- ラスタを読んでタイルを塗ること → `test_landcover_raster.py`
- どのクラスが難易度に効くか（評価軸の項）→ 軸の宣言のテスト
- 割合列の名前から材料の列と焼き込み列の名前を導く規則（`landcover_key`・`landcover_tile_property`）→ 書く側も読む側も
  同じ関数で名前を導くので、食い違いようが無い
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import text

from app.domain import landcover



def on_postgis(test):
    """SQLを実行するテストにだけ付ける。純関数のテストはDBの無い環境でも走る。"""
    for mark in (pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis"), pytest.mark.postgis):
        test = mark(test)
    return test

# 配布元の画素値のうち、どのクラスでもないもの（No Data と Clouds）。
NO_DATA = 0
CLOUDS = 10

CLASS_VALUES = [value for _, value in landcover.PERCENT_CLASSES]
FIRST, SECOND = CLASS_VALUES[0], CLASS_VALUES[1]


def field_of(value: int) -> str:
    return next(cls.percent_field for cls in landcover.LANDCOVER_CLASSES if cls.value == value)


async def percentages(session, counts: list[tuple[int, int, int, int]]) -> list[dict]:
    """`(osm_way_id, segment_index, cls, n)`の行を関係として渡し、返った行を辞書で返す。"""
    rows = ", ".join(f"({way}, {segment}, {cls}, {n})" for way, segment, cls, n in counts)
    relation = f"SELECT * FROM (VALUES {rows}) AS c(osm_way_id, segment_index, cls, n)"
    result = await session.execute(text(landcover.class_percentages_sql(relation)))
    return [dict(row._mapping) for row in result]


@on_postgis
async def test_no_data_and_clouds_are_left_out_of_the_denominator(road_graph_session):
    [row] = await percentages(
        road_graph_session, [(1, 0, FIRST, 30), (1, 0, NO_DATA, 500), (1, 0, CLOUDS, 500)]
    )

    assert row["valid_pixels"] == 30
    assert row[field_of(FIRST)] == pytest.approx(100.0)


@on_postgis
async def test_a_segment_with_too_few_valid_pixels_has_no_row(road_graph_session):
    enough = landcover.MIN_VALID_PIXELS
    rows = await percentages(
        road_graph_session,
        [
            (1, 0, FIRST, enough),  # ちょうど下限は行を持つ
            (2, 0, FIRST, enough - 1),
        ],
    )

    assert [row["osm_way_id"] for row in rows] == [1]


@on_postgis
async def test_segments_are_counted_separately(road_graph_session):
    rows = await percentages(
        road_graph_session,
        [(1, 0, FIRST, 20), (1, 1, SECOND, 20), (2, 0, FIRST, 10), (2, 0, SECOND, 30)],
    )

    by_segment = {(row["osm_way_id"], row["segment_index"]): row for row in rows}
    assert by_segment[(1, 0)][field_of(FIRST)] == pytest.approx(100.0)
    assert by_segment[(1, 1)][field_of(SECOND)] == pytest.approx(100.0)
    assert by_segment[(2, 0)][field_of(FIRST)] == pytest.approx(25.0)


@on_postgis
async def test_every_class_in_the_declaration_is_counted_and_the_row_fits_the_model(road_graph_session):
    """クラスごとに違う画素数を与え、どのクラスの数もそのクラスの列にだけ入ることを見る。画素の無いクラスは0。"""
    counts = {value: 10 * (position + 1) for position, value in enumerate(CLASS_VALUES[:-1])}
    [row] = await percentages(road_graph_session, [(1, 0, value, n) for value, n in counts.items()])
    total = sum(counts.values())

    percentages_row = landcover.LandcoverPercentages(
        **{name: value for name, value in row.items() if name not in ("osm_way_id", "segment_index", "valid_pixels")}
    )

    for cls in landcover.LANDCOVER_CLASSES:
        assert getattr(percentages_row, cls.percent_field) == pytest.approx(100.0 * counts.get(cls.value, 0) / total)


def test_the_class_declaration_can_be_told_apart_everywhere_it_is_read():
    """画素値が重なると1つの画素が2クラスに数えられ、割合列の名前が重なると材料の列と焼き込み列がぶつかる。
    表示名・色が重なると凡例と区間インスペクタで見分けられない。"""
    classes = landcover.LANDCOVER_CLASSES
    for attribute in ("value", "percent_field", "label", "color"):
        values = [getattr(cls, attribute) for cls in classes]
        assert len(set(values)) == len(values), attribute
    assert all(cls.percent_field.endswith("_percent") for cls in classes)
    assert not {cls.value for cls in classes} & {NO_DATA, CLOUDS}


def test_the_fingerprint_reads_only_the_file_names():
    assert landcover.raster_set_fingerprint(["/data/a/10N.tif", "/data/b/11N.tif"]) == (
        landcover.raster_set_fingerprint(["other/10N.tif", "11N.tif"])
    )


def test_adding_a_raster_changes_the_fingerprint():
    assert landcover.raster_set_fingerprint(["10N.tif"]) != landcover.raster_set_fingerprint(
        ["10N.tif", "11N.tif"]
    )


@given(names=st.lists(st.from_regex(r"[0-9A-Z]{2,4}\.tif", fullmatch=True), min_size=1, unique=True), data=st.data())
def test_the_order_of_the_rasters_does_not_change_the_fingerprint(names, data):
    shuffled = data.draw(st.permutations(names))

    assert landcover.raster_set_fingerprint(shuffled) == landcover.raster_set_fingerprint(names)
