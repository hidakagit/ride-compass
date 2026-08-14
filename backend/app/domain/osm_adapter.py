"""OSM Adapter / Importer（仕様書2・21・47章）。

OSM（Overpass由来のWay/Nodeデータ）の語彙（`tags`辞書、`oneway`タグの値等）を解釈し、
データソースに依存しない`WaySpec`（domain/graph.py）へ変換する。この変換をここに
閉じ込めることで、`build_road_graph`（domain/graph.py）はOSMのタグ形式を一切知らずに
すむ。将来Overpassのクエリ形式が変わったり、OSM以外のデータソース（PBF一括抽出等）に
切り替えたりしても、影響範囲はこのファイル（と対応するAdapter）に限定される。
"""

from app.domain.graph import WaySpec

# OSMのoneway値のうち「逆方向への通行不可」を意味するもの。bicycle固有の例外
# （oneway:bicycle=no等）はここでは扱わない（Evaluation Engine側の関心事。
# Road Graphは基本的な通行方向のみを保持する、仕様書10章の方針）。
ONEWAY_FORWARD_ONLY = {"yes", "true", "1"}
ONEWAY_BACKWARD_ONLY = {"-1", "reverse"}


def osm_way_to_way_spec(raw_way: dict) -> WaySpec | None:
    """OverpassClient.get_ways_and_nodesが返すway要素
    （`{"id": int, "tags": dict, "nodes": list[int]}`）を`WaySpec`へ変換する。

    ノードが2未満のwayは経路探索上の区間になり得ないためNoneを返す。
    """
    node_ids = raw_way.get("nodes") or []
    if len(node_ids) < 2:
        return None

    tags = raw_way.get("tags", {})
    oneway = str(tags.get("oneway", "")).strip().lower()
    if oneway in ONEWAY_BACKWARD_ONLY:
        direction = "backward"
    elif oneway in ONEWAY_FORWARD_ONLY:
        direction = "forward"
    else:
        direction = "both"

    return WaySpec(
        osm_way_id=raw_way.get("id"),
        node_ids=node_ids,
        highway=tags.get("highway"),
        surface=tags.get("surface"),
        direction=direction,
    )


def osm_ways_to_way_specs(raw_ways: list[dict]) -> list[WaySpec]:
    specs = (osm_way_to_way_spec(way) for way in raw_ways)
    return [spec for spec in specs if spec is not None]
