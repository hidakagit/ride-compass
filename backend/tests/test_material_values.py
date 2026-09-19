"""材料の値が、元データから**あるべき値**になることを人が書いた期待値で確かめる。

材料の値の求め方は`MaterialSpec.value_sql`だけが持つ（評価・地図タイル・欠損率の集計は
すべてこの式を読む）。ここはその1本へ、入力と期待値の表を当てる唯一の場所。

元データは4種類の出どころを持つ。表の1件はそのすべてを指定できる。

- `osm_raw_ways`の行（`w`）: 専用列（highway/surface）とtags jsonb。**行が無い**場合
  （未取込の地域・PBF再取込の途中）はタグ由来の材料がすべて不明になる。
- 区間の行（`re`）: highway・距離。区間はwayの行が無くても存在しうる。
- 集計・派生の表（`c`/`e`/`el`/`wl`/`d`）: 件数・標高・土地被覆・指定路線。
  **行の有無と値の有無を分ける**——行が無ければ不明、行があればキーが無くても0件。

実DBへ接続するが、テーブルは作らない——式はエイリアスだけを参照するため、同じ列を持つ
CTEをそのエイリアス名で用意すれば式そのものを評価できる。
"""

import json
from dataclasses import dataclass, field

import pytest
from sqlalchemy import ARRAY, Text, bindparam, text

from app.domain.attributes import WIRED_LANDCOVER_KEYS
from app.domain.material_catalog import material_value_sql
from app.domain.material_sql import LANDCOVER_SQL_KEYS
from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS
from app.domain.traffic import POI_COUNT_KINDS

pytestmark = [
    pytest.mark.postgis,
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.asyncio(loop_scope="module"),
]


@dataclass(frozen=True)
class _Case:
    label: str
    expected: dict[str, object]
    # osm_raw_waysの行。way_present=Falseは「その区間のwayの行が無い」。
    way_present: bool = True
    highway: str | None = "residential"
    surface: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    distance_m: float = 1000.0
    # 集計・派生の行。Noneは「行が無い」。
    accident_count: float | None = None
    intersection_count: float | None = None
    poi_counts: dict[str, int] | None = None
    average_grade: float | None = None
    is_designated: bool | None = None
    edge_landcover: dict[str, float] | None = None
    way_landcover: dict[str, float] | None = None
    accident_years: int = 1


_CASES: list[_Case] = [
    # --- wayのタグ由来 ---
    _Case(
        label="タグが何も無い住宅道路",
        expected={
            "surface_good": None,
            "surface": None,
            "highway": "residential",
            "smoothness": None,
            "tracktype": None,
            "has_tunnel": False,
            "bridge": False,
            "maxspeed_kmh": None,
            "lanes_count": None,
            "motor_vehicle_no": False,
            "lit": False,
            "highway_is_cycleway": False,
            "cycleway_has_track": False,
            "cycleway_has_lane": False,
            "cycleway_has_shared": False,
            "shared_pedestrian_path": False,
        },
    ),
    _Case(
        label="wayの行が無い区間はタグ由来の材料がすべて不明",
        way_present=False,
        tags={"lit": "yes", "tunnel": "yes"},
        expected={
            "lit": None,
            "has_tunnel": None,
            "bridge": None,
            "motor_vehicle_no": None,
            "highway_is_cycleway": None,
            "cycleway_has_track": None,
            "cycleway_has_lane": None,
            "cycleway_has_shared": None,
            "shared_pedestrian_path": None,
            "is_designated": None,
            # 種別と距離は区間の行が持つため、wayの行が無くても求まる。
            "highway": "residential",
        },
    ),
    _Case(
        label="舗装・街灯あり・制限速度40・2車線",
        highway="primary",
        surface="asphalt",
        tags={"lit": "yes", "maxspeed": "40", "lanes": "2"},
        expected={
            "surface_good": True,
            "surface": "asphalt",
            "highway": "primary",
            "lit": True,
            "maxspeed_kmh": 40,
            "lanes_count": 2,
        },
    ),
    _Case(
        label="未舗装",
        surface="gravel",
        expected={"surface_good": False, "surface": "gravel"},
    ),
    _Case(
        label="未知のsurfaceは悪路ではなく不明",
        surface="unknown_tag",
        expected={"surface_good": None, "surface": "unknown_tag"},
    ),
    _Case(
        label="surfaceタグ自体が無ければ路面の良し悪しは不明",
        expected={"surface_good": None, "surface": None},
    ),
    _Case(
        label="大文字・前後空白のタグ値は正規化する",
        surface=" Asphalt ",
        tags={"smoothness": " Good ", "tracktype": " Grade2 "},
        expected={
            "surface_good": True,
            "surface": "asphalt",
            "smoothness": "good",
            "tracktype": "grade2",
        },
    ),
    _Case(
        label="トンネルと橋",
        tags={"tunnel": "yes", "bridge": "yes"},
        expected={"has_tunnel": True, "bridge": True},
    ),
    _Case(
        label="自動車進入禁止",
        tags={"motor_vehicle": "no"},
        expected={"motor_vehicle_no": True},
    ),
    _Case(
        label="0や非数値の制限速度・車線数は不明として扱う",
        tags={"maxspeed": "0", "lanes": "walk"},
        expected={"maxspeed_kmh": None, "lanes_count": None},
    ),
    _Case(
        label="自転車道",
        highway="cycleway",
        expected={"highway_is_cycleway": True, "cycleway_has_track": False},
    ),
    _Case(
        label="片側だけのcycleway_left_track",
        tags={"cycleway:left": "track"},
        expected={
            "cycleway_has_track": True,
            "cycleway_has_lane": False,
            "cycleway_has_shared": False,
        },
    ),
    _Case(
        label="cycleway_lane",
        tags={"cycleway": "lane"},
        expected={"cycleway_has_lane": True, "cycleway_has_track": False},
    ),
    _Case(
        label="cycleway_both_shared_lane",
        tags={"cycleway:both": "shared_lane"},
        expected={"cycleway_has_shared": True, "cycleway_has_lane": False},
    ),
    _Case(
        label="cycleway_share_busway",
        tags={"cycleway": "share_busway"},
        expected={"cycleway_has_shared": True},
    ),
    _Case(
        label="河川敷の歩道兼サイクリングロード",
        highway="footway",
        tags={"bicycle": "designated"},
        expected={"shared_pedestrian_path": True},
    ),
    _Case(
        label="自転車通行不可の歩道",
        highway="footway",
        tags={"bicycle": "no"},
        expected={"shared_pedestrian_path": False},
    ),
    _Case(
        label="bicycle_designatedでもfootway_path以外は該当しない",
        tags={"bicycle": "designated"},
        expected={"shared_pedestrian_path": False},
    ),
    # --- 標高（区間単位の派生表） ---
    _Case(
        label="勾配は標高の平均勾配をそのまま使う",
        average_grade=4.5,
        expected={"gradient_percent": 4.5},
    ),
    _Case(
        label="標高が未計算なら勾配は不明",
        expected={"gradient_percent": None},
    ),
    # --- 件数（集計表） ---
    _Case(
        label="事故は件/(km・年)へ正規化する",
        distance_m=100.0,
        accident_count=4.0,
        accident_years=2,
        expected={"accident_count_per_km_year": (4 / 0.1) / 2},
    ),
    _Case(
        label="収録年数が0なら事故密度は求まらない",
        distance_m=100.0,
        accident_count=4.0,
        accident_years=0,
        expected={"accident_count_per_km_year": None},
    ),
    _Case(
        label="集計行が無ければ件数由来の材料は不明",
        expected={
            "accident_count_per_km_year": None,
            "intersection_count_per_km": None,
            "poi_signal_per_km": None,
        },
    ),
    _Case(
        label="交差点は件/kmへ正規化する",
        distance_m=500.0,
        intersection_count=3.0,
        expected={"intersection_count_per_km": 6.0},
    ),
    _Case(
        label="POIは行があればキーが無くても0件（未集計と取り違えない）",
        distance_m=100.0,
        poi_counts={"crossing": 3},
        expected={"poi_signal_per_km": 0.0, "poi_crossing_per_km": 30.0},
    ),
    _Case(
        label="POIの集計行が空でも行があれば0件",
        distance_m=100.0,
        poi_counts={},
        expected={"poi_signal_per_km": 0.0},
    ),
    # --- 土地被覆（区間単位が優先、無ければway単位） ---
    _Case(
        label="土地被覆は区間単位の行を使う",
        edge_landcover={"trees_percent": 42.5, "built_percent": 30.0},
        way_landcover={"trees_percent": 1.0, "built_percent": 2.0},
        expected={"trees_percent": 42.5, "built_percent": 30.0},
    ),
    _Case(
        label="区間単位の行が無ければway単位へ落とす",
        way_landcover={"trees_percent": 1.0},
        expected={"trees_percent": 1.0},
    ),
    _Case(
        label="どちらの行も無ければ土地被覆は不明",
        expected={"trees_percent": None, "built_percent": None},
    ),
    # --- 指定路線 ---
    _Case(
        label="指定路線に該当する",
        is_designated=True,
        expected={"is_designated": True},
    ),
    _Case(
        label="指定路線の行が無ければ非該当（wayの行はあるため不明ではない）",
        expected={"is_designated": False},
    ),
]


def _landcover_columns(alias_values: dict[str, float] | None, prefix: str) -> str:
    return ", ".join(
        f"CAST(:{prefix}_{key} AS double precision) AS {key}_percent" for key in LANDCOVER_SQL_KEYS
    )


_SELECT_SQL = text(
    "WITH w AS (SELECT CAST(:osm_way_id AS bigint) AS osm_way_id, CAST(:tags AS jsonb) AS tags, "
    "CAST(:surface AS text) AS surface, CAST(:highway AS text) AS highway), "
    "re AS (SELECT CAST(:highway AS text) AS highway, "
    "CAST(:distance_m AS double precision) AS distance_m), "
    "c AS (SELECT CAST(:accident_count AS double precision) AS accident_count, "
    "CAST(:intersection_count AS double precision) AS intersection_count, "
    "CAST(:poi_counts AS jsonb) AS poi_counts), "
    "e AS (SELECT CAST(:average_grade AS double precision) AS average_grade), "
    f"el AS (SELECT {_landcover_columns(None, 'el')}), "
    f"wl AS (SELECT {_landcover_columns(None, 'wl')}), "
    "d AS (SELECT CAST(:is_designated AS boolean) AS is_designated) "
    "SELECT "
    + ", ".join(f"({expr}) AS m_{name}" for name, expr in sorted(material_value_sql().items()))
    + " FROM w, re, c, e, el, wl, d"
).bindparams(
    bindparam("good_tags", value=sorted(GOOD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
    bindparam("bad_tags", value=sorted(BAD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
)


def _params(case: _Case) -> dict[str, object]:
    params: dict[str, object] = {
        "osm_way_id": 1 if case.way_present else None,
        "tags": json.dumps(case.tags),
        "surface": case.surface,
        "highway": case.highway,
        "distance_m": case.distance_m,
        "accident_count": case.accident_count,
        "intersection_count": case.intersection_count,
        "poi_counts": None if case.poi_counts is None else json.dumps(case.poi_counts),
        "average_grade": case.average_grade,
        "is_designated": case.is_designated,
        "accident_years": case.accident_years,
    }
    for prefix, values in (("el", case.edge_landcover), ("wl", case.way_landcover)):
        for key in LANDCOVER_SQL_KEYS:
            params[f"{prefix}_{key}"] = None if values is None else values.get(f"{key}_percent")
    return params


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c.label)
async def test_material_values_match_written_expectations(road_graph_session, case: _Case):
    row = (await road_graph_session.execute(_SELECT_SQL, _params(case))).one()
    for material_id, expected in case.expected.items():
        actual = getattr(row, f"m_{material_id}")
        if isinstance(expected, float) and actual is not None:
            assert actual == pytest.approx(expected), f"{material_id}: {actual!r} ≠ 期待{expected!r}"
        else:
            assert actual == expected, f"{material_id}: {actual!r} ≠ 期待{expected!r}"


async def test_every_wired_landcover_class_reaches_a_material(road_graph_session):
    """配線したクラスはすべて材料として引ける（クラスを1つ足したときに追従が要らない）。"""
    case = _Case(
        label="全クラス",
        expected={},
        edge_landcover={key: 10.0 for key in WIRED_LANDCOVER_KEYS},
    )
    row = (await road_graph_session.execute(_SELECT_SQL, _params(case))).one()
    for key in WIRED_LANDCOVER_KEYS:
        assert getattr(row, f"m_{key}") == pytest.approx(10.0), key


async def test_every_poi_kind_reaches_a_material(road_graph_session):
    """停止要因POIの種別はすべて材料として引ける（種別を1つ足したときに追従が要らない）。"""
    case = _Case(
        label="全種別",
        expected={},
        distance_m=1000.0,
        poi_counts={kind: 2 for kind in POI_COUNT_KINDS},
    )
    row = (await road_graph_session.execute(_SELECT_SQL, _params(case))).one()
    for kind in POI_COUNT_KINDS:
        assert getattr(row, f"m_poi_{kind}_per_km") == pytest.approx(2.0), kind
