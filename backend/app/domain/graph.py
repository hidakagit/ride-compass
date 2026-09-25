import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LeanEdge:
    """経路探索の基本単位となる、方向を持つ道路区間。A→BとB→Aは別の枝として扱う。

    確定した経路の区間の分だけ作る（探索は区間の番号で動き、このオブジェクトを作らない）。
    `geometry`は作った時点では空リストで、表示のために`get_edges_with_geometry`が取り直して
    埋める。読む側はどちらが来ても同じ属性名で読めるため、区別しない。

    路面・標高・交通量といった評価の材料はここへ持たせない（道路網そのものの表現に限る）。
    """

    edge_id: str
    from_node_id: str
    to_node_id: str
    geometry: list[list[float]]
    distance_m: float
    osm_way_id: int | None = None
    segment_index: int | None = None
    forward: bool = True
    highway: str | None = None
    bearing_deg: float | None = None


def node_key(osm_node_id: int) -> str:
    """グラフ上のノードの識別子。OSMのノードidから決まるため、同じ交差点は常に同じ鍵。"""
    return f"osm-node-{osm_node_id}"


def edge_key(osm_way_id: int, segment_index: int, forward: bool) -> str:
    """グラフ上の有向な枝の識別子。DBは向きを持たないので、ここだけが向きを名前へ入れる。"""
    return f"way-{osm_way_id}-seg{segment_index}-{'fwd' if forward else 'bwd'}"


_EDGE_KEY_PATTERN = re.compile(r"^way-(?P<way>\d+)-seg(?P<segment>\d+)-(?P<direction>fwd|bwd)$")


def parse_edge_key(key: str) -> tuple[int, int, bool] | None:
    """`edge_key`の逆（`(osm_way_id, segment_index, forward)`）。形が違えばNone。"""
    match = _EDGE_KEY_PATTERN.match(key)
    if match is None:
        return None
    return int(match["way"]), int(match["segment"]), match["direction"] == "fwd"
