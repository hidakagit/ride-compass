"""材料の値が、元データから**あるべき値**になることを人が書いた期待値で確かめる。

材料の値の求め方は`MaterialSpec.value_sql`だけが持つ（評価・地図タイル・欠損率の集計は
すべてこの式を読む）。ここはその1本へ入力と期待値の表を当てる唯一の場所で、**式そのものと、
材料がその式へ配線されていることを同時に見る**——`material_value_sql()`から全材料ぶんの式を
並べて1回で評価するため、配線の抜けは値が出ないこととして現れる。

式はテーブルの別名を固定で参照し、FROM句は読み出し側が組み立てる。実DBへ接続するが
テーブルは作らない——同じ列を持つCTEをその別名で用意すれば式を評価できる。`w`が
`source_features`からどう作られるかは`ways_source_sql`自身の検査（末尾）が持つ。

元データは粒度ごとに1つの表から来る。表の1件はそのすべてを指定できる。

- 道の行（`w`）: 専用列（highway/surface）とtags jsonb。区間はwayの派生
  （`road_edges.osm_way_id`がNOT NULL + FK）のため、**行は必ずある**。
- 区間の行（`re`）: 距離。
- 区間に付く値（`em`）: 件数・標高・土地被覆。**未計算はNULL**で、0件とは別物。

区間の値が無いときに道の値へ落とすのは読み出し側（`road_graph_repository`）の仕事。
欠損率の測り方は`test_material_coverage.py`、材料の宣言から下流を導く部分は
`test_material_catalog.py`が持つ。
"""

import json
from dataclasses import dataclass, field

import pytest
from sqlalchemy import ARRAY, Text, bindparam, text

from app.domain.attributes import WIRED_LANDCOVER_KEYS
from app.domain.material_catalog import material_value_sql
from app.domain.material_sql import LANDCOVER_SQL_KEYS, ways_lookup_sql, ways_source_sql
from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS
from app.domain.traffic import POI_COUNT_KINDS

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


@dataclass(frozen=True)
class _Case:
    label: str
    expected: dict[str, object]
    highway: str | None = "residential"
    surface: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    distance_m: float = 1000.0
    # 区間に付く値（`em`）。Noneは未計算。
    accident_count: float | None = None
    intersection_count: float | None = None
    poi_counts: dict[str, int] | None = None
    average_grade: float | None = None
    landcover: dict[str, float] | None = None
    # 道に付く値。
    accident_years: int = 1


_CASES: list[_Case] = [
    # --- wayのタグ由来。外部の値をそのまま持つ列なので、汚い入力の読み方を押さえる ---
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
        label="タグが書かれていれば真偽の材料は立つ",
        tags={"tunnel": "yes", "bridge": "Yes", "lit": " yes ", "motor_vehicle": "no"},
        expected={"has_tunnel": True, "bridge": True, "lit": True, "motor_vehicle_no": True},
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
        label="0や非数値の制限速度・車線数は不明として扱う",
        tags={"maxspeed": "0", "lanes": "walk"},
        expected={"maxspeed_kmh": None, "lanes_count": None},
    ),
    _Case(
        label="小数の制限速度は切り捨てる",
        tags={"maxspeed": "49.9", "lanes": " 3 "},
        expected={"maxspeed_kmh": 49, "lanes_count": 3},
    ),
    _Case(
        label="自転車道は種別そのもので分かる",
        highway="cycleway",
        expected={"highway_is_cycleway": True, "shared_pedestrian_path": False},
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
        label="cyclewayの値も大文字を正規化する",
        tags={"cycleway:both": "Lane"},
        expected={"cycleway_has_lane": True, "cycleway_has_track": False},
    ),
    _Case(
        label="自転車が通れる歩道・小径は歩行者との共用路",
        highway="footway",
        tags={"bicycle": "yes"},
        expected={"shared_pedestrian_path": True},
    ),
    _Case(
        label="pathへdesignatedでも共用路",
        highway="path",
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
        label="勾配は区間の派生値をそのまま材料にする",
        average_grade=-3.5,
        expected={"gradient_percent": -3.5},
    ),
    _Case(
        label="標高が未計算なら勾配も不明",
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
        label="未計算なら件数由来の材料は不明",
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
        label="POIは数えた種別が無くても0件（未計算と取り違えない）",
        distance_m=100.0,
        poi_counts={"crossing": 3},
        expected={"poi_signal_per_km": 0.0, "poi_crossing_per_km": 30.0},
    ),
    _Case(
        label="どの種別も0件なら0件（未計算ではない）",
        distance_m=100.0,
        poi_counts={},
        expected={"poi_signal_per_km": 0.0},
    ),
    _Case(
        label="長さの無い区間は密度を持たない",
        distance_m=0.0,
        accident_count=4.0,
        intersection_count=3.0,
        poi_counts={"signal": 2},
        expected={
            "accident_count_per_km_year": None,
            "intersection_count_per_km": None,
            "poi_signal_per_km": None,
        },
    ),
]


def _em_columns() -> str:
    """区間に付く値。未計算はNULL、行はあるが0件なら0。"""
    landcover = ", ".join(
        f"CAST(:lc_{key} AS double precision) AS lc_{key}" for key in LANDCOVER_SQL_KEYS
    )
    poi = ", ".join(
        f"CAST(:poi_{kind} AS double precision) AS poi_{kind}" for kind in POI_COUNT_KINDS
    )
    return (
        "CAST(:accident_count AS double precision) AS accident_count, "
        "CAST(:intersection_count AS double precision) AS intersection_count, "
        "CAST(:average_grade AS double precision) AS average_grade, "
        f"{landcover}, {poi}"
    )


_SELECT_SQL = text(
    "WITH w AS (SELECT CAST(:osm_way_id AS bigint) AS osm_way_id, CAST(:tags AS jsonb) AS tags, "
    "CAST(:surface AS text) AS surface, CAST(:highway AS text) AS highway), "
    "re AS (SELECT CAST(:distance_m AS double precision) AS distance_m), "
    f"em AS (SELECT {_em_columns()}) "
    "SELECT "
    + ", ".join(f"({expr}) AS m_{name}" for name, expr in sorted(material_value_sql().items()))
    + " FROM w, re, em"
).bindparams(
    bindparam("good_tags", value=sorted(GOOD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
    bindparam("bad_tags", value=sorted(BAD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
)


def _params(case: _Case) -> dict[str, object]:
    params: dict[str, object] = {
        "osm_way_id": 1,
        "tags": json.dumps(case.tags),
        "surface": case.surface,
        "highway": case.highway,
        "distance_m": case.distance_m,
        "accident_count": case.accident_count,
        "intersection_count": case.intersection_count,
        "average_grade": case.average_grade,
        "accident_years": case.accident_years,
    }
    for key in LANDCOVER_SQL_KEYS:
        params[f"lc_{key}"] = (
            None if case.landcover is None else case.landcover.get(f"{key}_percent")
        )
    for kind in POI_COUNT_KINDS:
        params[f"poi_{kind}"] = None if case.poi_counts is None else case.poi_counts.get(kind, 0)
    return params


async def _row(session, case: _Case):
    return (await session.execute(_SELECT_SQL, _params(case))).one()


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c.label)
async def test_material_values_match_written_expectations(road_graph_session, case: _Case):
    row = await _row(road_graph_session, case)
    for material_id, expected in case.expected.items():
        actual = getattr(row, f"m_{material_id}")
        if isinstance(expected, float) and actual is not None:
            assert actual == pytest.approx(expected), f"{material_id}: {actual!r} ≠ 期待{expected!r}"
        else:
            assert actual == expected, f"{material_id}: {actual!r} ≠ 期待{expected!r}"


class TestEveryDeclaredValueReachesAMaterial:
    """語彙・クラス・種別を1つ足したときに発火する。集合や表へ入れただけでは、その値が
    材料として引けるとは限らない。
    """

    @pytest.mark.parametrize("tag", sorted(GOOD_OSM_SURFACE_TAGS))
    async def test_every_good_surface_tag_lands_on_good(self, road_graph_session, tag):
        case = _Case(label=tag, expected={}, surface=tag)

        assert getattr(await _row(road_graph_session, case), "m_surface_good") is True

    @pytest.mark.parametrize("tag", sorted(BAD_OSM_SURFACE_TAGS))
    async def test_every_bad_surface_tag_lands_on_bad(self, road_graph_session, tag):
        case = _Case(label=tag, expected={}, surface=tag)

        assert getattr(await _row(road_graph_session, case), "m_surface_good") is False

    async def test_every_wired_landcover_class_reaches_a_material(self, road_graph_session):
        case = _Case(
            label="全クラス",
            expected={},
            landcover={key: 10.0 for key in WIRED_LANDCOVER_KEYS},
        )
        row = await _row(road_graph_session, case)

        for key in WIRED_LANDCOVER_KEYS:
            assert getattr(row, f"m_{key}") == pytest.approx(10.0), key

    async def test_every_poi_kind_reaches_a_material(self, road_graph_session):
        case = _Case(
            label="全種別",
            expected={},
            distance_m=1000.0,
            poi_counts={kind: 2 for kind in POI_COUNT_KINDS},
        )
        row = await _row(road_graph_session, case)

        for kind in POI_COUNT_KINDS:
            assert getattr(row, f"m_poi_{kind}_per_km") == pytest.approx(2.0), kind


class TestTheWaySubquery:
    """上の表は`w`をCTEで与える。その`w`を生データから作る側だけをここで見る。"""

    async def test_it_exposes_the_columns_the_expressions_reference(self, road_graph_session):
        """式は`w.tags`・`w.highway`・`w.surface`を名前で参照する。1つ欠けると、それを
        参照する材料の読み出しだけがSQLエラーになる。
        """
        query = f"SELECT osm_way_id, geom, tags, highway, surface FROM {ways_source_sql()} w"

        assert (await road_graph_session.execute(text(query))).keys() == [
            "osm_way_id",
            "geom",
            "tags",
            "highway",
            "surface",
        ]

    async def test_the_sampling_clause_goes_inside_the_subquery(self, road_graph_session):
        """外へ付けると構文エラーになる。抽選は副問い合わせの中にしか置けない。"""
        query = f"SELECT count(*) FROM {ways_source_sql('TABLESAMPLE SYSTEM (100)')} w"

        assert (await road_graph_session.execute(text(query))).scalar() is not None

    async def test_a_single_way_is_looked_up_by_the_untouched_key(self, road_graph_session):
        """主キーは`(source, natural_key)`。`natural_key::bigint`と比べると索引が使えず、
        道の全件に対する総当たりになる。
        """
        query = f"SELECT count(*) FROM {ways_lookup_sql('42')} w"

        assert (await road_graph_session.execute(text(query))).scalar() == 0
