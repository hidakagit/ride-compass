"""`infrastructure/road_network_store.py`——道路網全体の配列を組み、ディスクへ置き、読み戻す。

ここで見ないもの:
- 読み出しのSQLそのもの（区間・ノード・材料の式） → PostGISが要る。材料の式は`test_material_values.py`
- 範囲を切り出して探索に使う側 → `RoadGraphEngine`のテスト

リポジトリは代役で、各メソッドを`RoadGraphRepository`の同名メソッドの署名へ当ててから呼ぶ（`bound`）。
代役が返す行は、道のid・区間番号・向きから決まる値を持つ——行の並びがずれれば値がずれて見える。
"""

from types import SimpleNamespace

import numpy as np
import pytest

from app.domain.attributes import EdgeMaterialArrays
from app.domain.road_network import RoadNetwork
from app.infrastructure import road_network_store
from app.infrastructure.road_graph_repository import RoadGraphRepository
from tests.bound_fake import bound

#: (osm_node_id, 緯度, 経度)。昇順で返すのはSQLの`ORDER BY`の約束。
NODES = [(1, 35.0, 139.0), (2, 35.1, 139.1), (3, 35.2, 139.2), (4, 35.3, 139.3)]
#: (道, 区間, 始点, 終点, 一方通行の向き, highway)。道30の終点99はノードに無い。
EDGES = [
    (10, 0, 1, 2, None, "primary"),
    (10, 1, 2, 3, "forward", "primary"),
    (20, 0, 3, 4, "backward", None),
    (30, 0, 4, 99, None, "residential"),
]
#: 道ごとの分類の材料の値（Noneは値なし）。
CATEGORY = {10: "asphalt", 20: None}


def _numeric(way: int, segment: int, forward: bool) -> float:
    return way * 10 + segment + (0.0 if forward else 0.5)


def _repository_method(fake):
    return bound(getattr(RoadGraphRepository, fake.__name__), fake)


class FakeRepository:
    def __init__(self, revision: int | None = 7):
        self.revision = revision
        self.material_calls = 0

    @_repository_method
    async def get_derived_data_revision(self):
        return self.revision

    @_repository_method
    async def get_accident_years_covered(self):
        return 5

    @_repository_method
    async def stream_network_nodes(self, chunk_size):
        rows = [SimpleNamespace(osm_node_id=i, latitude=lat, longitude=lon,
                                has_traffic_signals=i == 2, max_highway_rank=i) for i, lat, lon in NODES]
        for start in range(0, len(rows), chunk_size):
            yield rows[start:start + chunk_size]

    @_repository_method
    async def stream_network_edges(self, chunk_size):
        rows = [SimpleNamespace(osm_way_id=w, segment_index=s, from_node_id=a, to_node_id=b, direction=d,
                                highway=h, min_lon=float(a), min_lat=float(s), max_lon=float(b), max_lat=float(w))
                for w, s, a, b, d, h in EDGES]
        for start in range(0, len(rows), chunk_size):
            yield rows[start:start + chunk_size]

    @_repository_method
    async def get_edge_material_arrays(self, edges, accident_years_covered):
        self.material_calls += 1
        n = len(edges)
        numeric = np.array([[_numeric(e.osm_way_id, e.segment_index, e.forward)] for e in edges])
        column = np.array([e.osm_way_id * 1.0 for e in edges])
        categorical = np.empty((n, 1), dtype=object)
        categorical[:, 0] = [CATEGORY[e.osm_way_id] for e in edges]
        return EdgeMaterialArrays(
            numeric_ids=("m_num",), numeric_values=numeric,
            boolean_ids=("m_bool",), boolean_values=np.array([[e.forward] for e in edges]),
            categorical_ids=("m_cat",), categorical_values=categorical,
            hard_filter_ids=("hf",), hard_filter_flags=np.array([[e.segment_index == 0] for e in edges]),
            distance_m=column, bearing_deg=column, mid_lat=column, mid_lon=column,
            elevation_present=np.array([e.forward for e in edges]),
            elevation_start_m=column, elevation_end_m=column, elevation_gain_m=column,
            elevation_loss_m=column, elevation_max_grade=column, elevation_min_grade=column,
        )


@pytest.fixture(autouse=True)
def _small_batches_and_tmp_root(monkeypatch, tmp_path):
    """束の境目をまたぐよう、流す単位と材料の束を小さくする。置き場はテストごとの一時ディレクトリ。"""
    monkeypatch.setattr(road_network_store, "_STREAM_CHUNK", 3)
    monkeypatch.setattr(road_network_store, "_MATERIAL_BATCH", 2)
    monkeypatch.setattr(road_network_store, "ROOT", tmp_path / "road_network")


def _directed(network: RoadNetwork) -> list[tuple[int, int, bool, int, int]]:
    osm = network.node_osm_id
    return [
        (int(w), int(s), bool(f), int(osm[a]), int(osm[b]))
        for w, s, f, a, b in zip(network.edge_way_id, network.edge_segment, network.edge_forward,
                                 network.edge_from, network.edge_to, strict=True)
    ]


async def test_edges_become_directed_rows_in_way_and_segment_order():
    """区間は順方向・逆方向の行になる。一方通行は走れる向きだけ、端点のノードが無い区間は落ちる。"""
    network = await road_network_store.build(FakeRepository())

    assert _directed(network) == [
        (10, 0, True, 1, 2),
        (10, 0, False, 2, 1),
        (10, 1, True, 2, 3),
        (20, 0, False, 4, 3),
    ]


async def test_materials_follow_the_directed_rows():
    network = await road_network_store.build(FakeRepository())

    expected = [_numeric(w, s, f) for w, s, f, _a, _b in _directed(network)]
    assert network.numeric_values[:, 0].tolist() == expected
    assert network.boolean_values[:, 0].tolist() == network.edge_forward.tolist()
    assert network.hard_filter_flags[:, 0].tolist() == (network.edge_segment == 0).tolist()


async def test_categorical_values_are_codes_into_a_vocabulary_that_starts_with_none():
    network = await road_network_store.build(FakeRepository())

    (vocab,) = network.categorical_vocab
    assert vocab[0] is None
    decoded = [vocab[code] for code in network.categorical_codes[:, 0]]
    assert decoded == [CATEGORY[int(way)] for way in network.edge_way_id]


async def test_highway_is_a_code_into_its_vocabulary():
    network = await road_network_store.build(FakeRepository())

    highway_of_way = {w: h for w, _s, _a, _b, _d, h in EDGES}
    assert [network.highway_vocab[code] for code in network.edge_highway] == [
        highway_of_way[int(way)] for way in network.edge_way_id
    ]


async def test_saved_network_reads_back_the_same():
    network = await road_network_store.build(FakeRepository())

    loaded = road_network_store.load(road_network_store.save(network))

    for name, value in vars(network).items():
        restored = getattr(loaded, name)
        if isinstance(value, np.ndarray):
            assert np.array_equal(np.asarray(restored), value, equal_nan=value.dtype.kind == "f"), name
        else:
            assert restored == value, name


async def test_current_network_is_built_once_and_older_revisions_are_removed(monkeypatch):
    """同じ世代の置き場があれば作らない。作ったら、同じ形で世代の古い置き場を消す。

    形の署名が違う置き場（旧コードのもの）は消さない——入れ替え前の旧コンテナが読んでいる。
    """
    repository = FakeRepository(revision=7)
    monkeypatch.setattr(road_network_store, "RoadGraphRepository", lambda session: repository)
    root = road_network_store.ROOT
    old = root / road_network_store.directory_name(6)
    other_shape = root / "0123456789ab-r9"
    for path in (old, other_shape):
        path.mkdir(parents=True)

    first = await road_network_store.ensure_current(_session_factory)
    calls_after_first = repository.material_calls
    second = await road_network_store.ensure_current(_session_factory)

    assert first == second == root / road_network_store.directory_name(7)
    assert repository.material_calls == calls_after_first
    assert not old.exists()
    assert other_shape.exists()
    assert road_network_store.latest_directory() == first


def _session_factory():
    class _Session:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    return _Session()


async def test_current_reads_the_newest_revision_and_follows_a_newer_one(monkeypatch):
    """バッチが新しい世代の置き場を作ったら、次の読み出しからそちらを使う。"""
    monkeypatch.setattr(road_network_store, "_loaded", None)
    road_network_store.save(await road_network_store.build(FakeRepository(revision=7)))
    assert road_network_store.current().revision == 7

    road_network_store.save(await road_network_store.build(FakeRepository(revision=8)))

    assert road_network_store.current().revision == 8


def test_no_network_for_the_current_code_is_an_error_not_an_empty_network(monkeypatch):
    """空の道路網として振る舞うと、ルート生成が「道路データが未整備」と誤って答える。"""
    monkeypatch.setattr(road_network_store, "_loaded", None)
    (road_network_store.ROOT / "0123456789ab-r9").mkdir(parents=True)

    with pytest.raises(road_network_store.RoadNetworkUnavailableError):
        road_network_store.current()


async def test_directories_of_other_shapes_are_removed_after_startup():
    """材料の式を変えたデプロイで古い形の置き場が残り続けないよう、起動後に消す。今の形は残す。"""
    current = road_network_store.save(await road_network_store.build(FakeRepository(revision=7)))
    other_shape = road_network_store.ROOT / "0123456789ab-r9"
    other_shape.mkdir()
    (other_shape / "manifest.json").write_text("{}", encoding="utf-8")

    freed = road_network_store.prune_other_shapes()

    assert freed > 0
    assert not other_shape.exists()
    assert current.exists()
