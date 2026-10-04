"""`infrastructure/road_network_store.py`——取込範囲全体の道路網をDBから組み、ディスクの置き場へ置き、読む。

入口は`ensure_current`（DBから組んで置く）・`write_pending`と`publish`（派生の作り直しが置く2段）・`save`・
`current`（読む）・`prune_other_shapes`（起動後の片付け）。置き場（`ROOT`）はテストごとの一時ディレクトリへ差し替える。

DBから組むテストは、道とノードを取込の入口から入れ、派生の作り直し（`batch/derive_cli.py: run`）で区間と材料まで
作ってから組む（本番で作れる行だけを使う。docs/conventions/testing.md パターン8）。置き場を読み書きするテストは、
形だけを持つ小さな`RoadNetwork`を組んで渡す。

ここで見ないもの:
- 区間の切り方・通行方向・信号の導出（派生の段） → `test_derive_topology.py`・`test_derive_way_materials.py`・
  `test_derive_node_materials.py`
- 材料の値そのもの → `test_material_values.py`
- 置いた道路網から探索範囲を切り出すこと → `test_road_network.py`
- 形の署名の組み立て → `test_cache_identity.py`

材料を束（`_MATERIAL_BATCH`区間）に分けて引くとき、束をまたいで分類の語彙を1つへ付け替えることは見ない
——束の大きさは本物の定数のまま通し、その数の区間をテストのDBに作らない。
"""

import json
import logging
import shutil
from dataclasses import fields

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.batch import derive_cli
from app.domain.road_network import RoadNetwork
from app.infrastructure import road_network_store
from app.infrastructure.road_graph_repository import RoadGraphRepository
from tests.conftest import postgis_database_url
from tests.source_ingest import ingest_records, point_record, way_record

#: DBから組むテストの印（テスト用DBへ繋ぎ、接続とイベントループをファイルで共有する。testing.md パターン2）。
_ON_TEST_DB = (pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis"), pytest.mark.postgis,
               pytest.mark.usefixtures("road_graph_session"))


def _on_test_db(test):
    for mark in _ON_TEST_DB:
        test = mark(test)
    return test


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    """置き場を空の一時ディレクトリにする（前のテストが読み込んだ道路網は置き場の場所が違うので使われない）。"""
    monkeypatch.setattr(road_network_store, "ROOT", tmp_path / "road_network")
    return tmp_path / "road_network"


# --- 置き場の読み書き（DBを使わない） -------------------------------------------------


def _network(revision: int | None, distance_m: float = 100.0) -> RoadNetwork:
    """ノード2つ・有向の区間2本（同じ区間の両向き）の道路網。材料の名前は架空。"""
    return RoadNetwork(
        revision=revision,
        node_osm_id=np.array([1, 2], dtype=np.int64),
        node_lat=np.array([35.0, 35.001]),
        node_lon=np.array([139.0, 139.001]),
        node_has_signals=np.array([False, True]),
        node_max_rank=np.array([0, 3], dtype=np.int64),
        edge_way_id=np.array([10, 10], dtype=np.int64),
        edge_segment=np.array([0, 0], dtype=np.int32),
        edge_forward=np.array([True, False]),
        edge_from=np.array([0, 1], dtype=np.int32),
        edge_to=np.array([1, 0], dtype=np.int32),
        edge_highway=np.array([1, 1], dtype=np.int16),
        highway_vocab=(None, "residential"),
        edge_min_lon=np.array([139.0, 139.0]),
        edge_min_lat=np.array([35.0, 35.0]),
        edge_max_lon=np.array([139.001, 139.001]),
        edge_max_lat=np.array([35.001, 35.001]),
        numeric_ids=("num_a",),
        numeric_values=np.array([[1.5], [np.nan]]),
        boolean_ids=("bool_a",),
        boolean_values=np.array([[True], [False]]),
        categorical_ids=("cat_a", "cat_b"),
        categorical_codes=np.array([[1, 0], [2, 1]], dtype=np.int16),
        categorical_vocab=((None, "x", "y"), (None, "z")),
        hard_filter_ids=("filter_a",),
        hard_filter_flags=np.array([[False], [True]]),
        distance_m=np.array([distance_m, distance_m]),
        bearing_deg=np.array([45.0, np.nan]),
        mid_lat=np.array([35.0005, 35.0005]),
        mid_lon=np.array([139.0005, 139.0005]),
        elevation_present=np.array([True, False]),
        elevation_start_m=np.array([10.0, np.nan]),
        elevation_end_m=np.array([12.0, np.nan]),
        elevation_gain_m=np.array([2.0, np.nan]),
        elevation_loss_m=np.array([0.0, np.nan]),
        elevation_max_grade=np.array([2.0, np.nan]),
        elevation_min_grade=np.array([1.0, np.nan]),
    )


def _assert_same(actual: RoadNetwork, expected: RoadNetwork) -> None:
    for f in fields(RoadNetwork):
        got, want = getattr(actual, f.name), getattr(expected, f.name)
        if isinstance(want, np.ndarray):
            assert got.dtype == want.dtype, f.name
            np.testing.assert_array_equal(got, want, err_msg=f.name)
        else:
            assert got == want, f.name


def _other_shape(revision: int) -> str:
    shape = "0" * 12 if road_network_store.NETWORK_SHAPE != "0" * 12 else "1" * 12
    return f"{shape}-r{revision}"


def _place(store, name: str, size: int = 0) -> None:
    (store / name).mkdir(parents=True)
    (store / name / "a.npy").write_bytes(b"\0" * size)


def test_without_any_placed_network_reading_is_refused():
    with pytest.raises(road_network_store.RoadNetworkUnavailableError):
        road_network_store.current()


def test_a_published_network_reads_back_as_it_was_built():
    road_network_store.publish(road_network_store.write_pending(_network(revision=4)))

    network = road_network_store.current()

    _assert_same(network, _network(revision=4))
    # 読むのはメモリマップを開くだけ（全リクエストが1つを共有し、常に要る列だけがメモリに載る）。
    assert isinstance(network.distance_m, np.memmap)


def test_a_network_being_written_is_not_read_until_it_is_published(store):
    pending = road_network_store.write_pending(_network(revision=4))

    with pytest.raises(road_network_store.RoadNetworkUnavailableError):
        road_network_store.current()
    road_network_store.publish(pending)
    assert road_network_store.current().revision == 4
    assert [path.name for path in store.iterdir()] == [road_network_store.directory_name(4)]


def test_publishing_removes_older_revisions_of_the_same_shape_but_not_other_shapes(store):
    road_network_store.publish(road_network_store.write_pending(_network(revision=3)))
    _place(store, _other_shape(1))

    road_network_store.publish(road_network_store.write_pending(_network(revision=4)))

    assert sorted(path.name for path in store.iterdir()) == sorted(
        [road_network_store.directory_name(4), _other_shape(1)])


def test_publishing_a_revision_that_another_process_published_first_keeps_the_first(store):
    road_network_store.publish(road_network_store.write_pending(_network(revision=4, distance_m=100.0)))
    late = road_network_store.write_pending(_network(revision=4, distance_m=999.0))

    placed = road_network_store.publish(late)

    assert placed == store / road_network_store.directory_name(4)
    assert not late.exists()
    assert road_network_store.current().distance_m[0] == 100.0


def test_saving_a_revision_that_is_already_placed_writes_nothing():
    first = road_network_store.save(_network(revision=4, distance_m=100.0))

    again = road_network_store.save(_network(revision=4, distance_m=999.0))

    assert again == first
    assert road_network_store.current().distance_m[0] == 100.0


@pytest.mark.parametrize(("revisions", "expected"), [
    ((None, 1), 1),  # 世代が読めなかったDBで作ったものは、世代のあるものより古い
    ((2, None, 1), 2),
])
def test_the_newest_revision_of_the_current_shape_is_read(store, revisions, expected):
    """付け替えたあと古い世代を消す前に落ちた置き場が残っていても、最も新しい世代を読む。"""
    store.mkdir()
    for revision in revisions:
        road_network_store.write_pending(_network(revision)).rename(store / road_network_store.directory_name(revision))
    _place(store, _other_shape(9))
    (store / "not-a-network").mkdir()
    (store / f"{road_network_store.NETWORK_SHAPE}-r99").write_text("ディレクトリではない")

    assert road_network_store.current().revision == expected


def test_a_newer_revision_placed_by_the_batch_is_read_on_the_next_call():
    road_network_store.save(_network(revision=2))
    first = road_network_store.current()
    assert road_network_store.current() is first

    road_network_store.save(_network(revision=3, distance_m=250.0))

    assert road_network_store.current().revision == 3
    assert road_network_store.current().distance_m[0] == 250.0


def test_cleaning_up_after_start_removes_only_networks_of_other_shapes(store):
    road_network_store.save(_network(revision=2))
    _place(store, _other_shape(1), size=10)
    _place(store, _other_shape(2), size=5)
    (store / "not-a-network").mkdir()
    (store / _other_shape(3)).write_text("ディレクトリではない")

    freed = road_network_store.prune_other_shapes()

    assert freed == 15
    assert sorted(path.name for path in store.iterdir()) == sorted(
        [road_network_store.directory_name(2), "not-a-network", _other_shape(3)])
    assert road_network_store.current().revision == 2


# --- DBから組む ---------------------------------------------------------------------

_BASE_LON, _BASE_LAT, _STEP = 139.70, 35.68, 0.001

#: ノード → (経度, 緯度)。ノード9は道が参照するのに取り込まれていない。
_NODES = {n: (_BASE_LON + _STEP * n, _BASE_LAT + _STEP * (n % 2)) for n in (1, 2, 3, 4, 5, 6, 9)}
_INGESTED_NODES = (1, 2, 3, 4, 5, 6)
_SIGNAL_NODE = 3

#: (道, 参照ノード列, タグ)。道500が道100とノード2で交わり、道100は2区間に切れる。
_WAYS = (
    (100, [1, 2, 3], {"highway": "residential"}),
    (200, [3, 4], {"highway": "primary", "oneway": "yes"}),
    (300, [4, 5], {"highway": "residential", "oneway": "-1"}),
    (400, [5, 9], {"highway": "residential"}),
    (500, [2, 6], {"highway": "tertiary"}),
)


async def _derive(ways=_WAYS, nodes=_INGESTED_NODES) -> None:
    """取込の入口から道とノードを入れ、派生の作り直しで区間と材料まで作る。作り直しが置いた道路網は消す。"""
    await ingest_records("osm_node", [
        point_record(n, *_NODES[n], {"highway": "traffic_signals"} if n == _SIGNAL_NODE else None) for n in nodes])
    await ingest_records("osm_way", [
        way_record(way_id, [_NODES[n] for n in node_ids], node_ids, tags) for way_id, node_ids, tags in ways])
    assert await derive_cli.run(postgis_database_url(), None) == 0
    shutil.rmtree(road_network_store.ROOT)


@_on_test_db
async def test_the_network_is_built_from_the_derived_tables_with_one_row_per_drivable_direction(
        road_graph_engine, caplog):
    await _derive()
    session_factory = async_sessionmaker(road_graph_engine)

    with caplog.at_level(logging.INFO, logger="ridecompass.road_network"):
        placed = await road_network_store.ensure_current(session_factory)
    network = road_network_store.current()

    async with session_factory() as session:
        repository = RoadGraphRepository(session)
        revision = (await repository.get_data_revisions()).derived
        assert placed.name == road_network_store.directory_name(revision)
        assert network.revision == revision

        # ノードは取り込まれた座標を持つものだけ、番号の昇順。
        assert network.node_osm_id.tolist() == list(_INGESTED_NODES)
        assert network.node_lon.tolist() == pytest.approx([_NODES[n][0] for n in _INGESTED_NODES])
        assert network.node_lat.tolist() == pytest.approx([_NODES[n][1] for n in _INGESTED_NODES])
        assert network.node_has_signals.tolist() == [n == _SIGNAL_NODE for n in _INGESTED_NODES]

        # 区間ごとに走れる向きだけ、道・区間の番号順に順方向が先。端点のノードが無い道400の区間は落ちる。
        osm = network.node_osm_id
        directed = [
            (int(w), int(s), bool(f), int(osm[a]), int(osm[b]))
            for w, s, f, a, b in zip(network.edge_way_id, network.edge_segment, network.edge_forward,
                                     network.edge_from, network.edge_to)
        ]
        assert directed == [
            (100, 0, True, 1, 2), (100, 0, False, 2, 1),
            (100, 1, True, 2, 3), (100, 1, False, 3, 2),
            (200, 0, True, 3, 4),
            (300, 0, False, 5, 4),
            (500, 0, True, 2, 6), (500, 0, False, 6, 2),
        ]
        assert "端点のノードが無く落とした有向の区間=2" in caplog.text

        # 道路の種別は語彙への番号で、番号0は値なし。
        assert network.highway_vocab[0] is None
        assert [network.highway_vocab[code] for code in network.edge_highway] == [
            "residential"] * 4 + ["primary", "residential", "tertiary", "tertiary"]

        # 区間の外接矩形は区間の両端を囲む。
        for row, (_, _, _, a, b) in enumerate(directed):
            lons, lats = (_NODES[a][0], _NODES[b][0]), (_NODES[a][1], _NODES[b][1])
            assert network.edge_min_lon[row] == pytest.approx(min(lons))
            assert network.edge_max_lon[row] == pytest.approx(max(lons))
            assert network.edge_min_lat[row] == pytest.approx(min(lats))
            assert network.edge_max_lat[row] == pytest.approx(max(lats))

        # 材料は、同じ有向の区間をリポジトリから引いた値と行ごとに揃う。
        materials = await repository.get_edge_material_arrays(
            network.edge_way_id.tolist(), network.edge_segment.tolist(), network.edge_forward.tolist(),
            await repository.get_accident_years_covered())
    assert network.categorical_ids == materials.categorical_ids
    assert materials.categorical_columns
    for column, (expected, vocab) in enumerate(zip(materials.categorical_columns, network.categorical_vocab)):
        assert vocab[0] is None
        assert [vocab[code] for code in network.categorical_codes[:, column]] == [
            expected.vocab[code] for code in expected.codes]
    # 分類の材料は語彙ごとの番号なので上で読み比べ、ほかの列は値をそのまま比べる。
    copied = [f.name for f in fields(materials) if f.name != "categorical_columns"]
    assert copied
    for name in copied:
        np.testing.assert_array_equal(getattr(network, name), getattr(materials, name), err_msg=name)


@_on_test_db
async def test_a_network_already_placed_for_the_current_revision_is_not_built_again(road_graph_engine):
    await _derive()
    session_factory = async_sessionmaker(road_graph_engine)
    placed = await road_network_store.ensure_current(session_factory)
    manifest = json.loads((placed / "manifest.json").read_text(encoding="utf-8"))
    (placed / "manifest.json").write_text(json.dumps({**manifest, "highway_vocab": [None, "置いたまま"]}),
                                          encoding="utf-8")

    assert await road_network_store.ensure_current(session_factory) == placed
    assert road_network_store.current().highway_vocab == (None, "置いたまま")


@_on_test_db
async def test_a_network_without_any_edge_is_refused_rather_than_placed(road_graph_engine, store):
    with pytest.raises(ValueError, match="区間が1本もありません"):
        await road_network_store.ensure_current(async_sessionmaker(road_graph_engine))
    assert not store.exists() or not any(store.iterdir())


@_on_test_db
async def test_edges_whose_ends_were_not_ingested_leave_no_network_to_place(store):
    """道だけがありノードを1つも取り込んでいなければ、区間は全部落ちて組み立てが断る（作り直しも止まる）。"""
    with pytest.raises(ValueError, match="区間が1本もありません"):
        await _derive(nodes=())
    assert not store.exists() or not any(store.iterdir())
