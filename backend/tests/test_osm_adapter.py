from app.domain.osm_adapter import (
    osm_node_to_poi_spec,
    osm_nodes_to_poi_specs,
    osm_way_to_way_spec,
    osm_ways_to_way_specs,
)


def test_way_without_oneway_tag_becomes_both_directions():
    spec = osm_way_to_way_spec({"id": 100, "tags": {"highway": "residential"}, "nodes": [1, 2]})

    assert spec is not None
    assert spec.direction == "both"
    assert spec.osm_way_id == 100
    assert spec.node_ids == [1, 2]
    assert spec.highway == "residential"


def test_surface_tag_is_passed_through():
    spec = osm_way_to_way_spec({"id": 100, "tags": {"surface": "asphalt"}, "nodes": [1, 2]})

    assert spec is not None
    assert spec.surface == "asphalt"


def test_missing_surface_tag_is_none():
    spec = osm_way_to_way_spec({"id": 100, "tags": {}, "nodes": [1, 2]})

    assert spec is not None
    assert spec.surface is None


def test_oneway_yes_becomes_forward_only():
    spec = osm_way_to_way_spec({"id": 100, "tags": {"oneway": "yes"}, "nodes": [1, 2]})

    assert spec.direction == "forward"


def test_oneway_reverse_value_becomes_backward_only():
    spec = osm_way_to_way_spec({"id": 100, "tags": {"oneway": "-1"}, "nodes": [1, 2]})

    assert spec.direction == "backward"


def test_oneway_tag_is_case_and_whitespace_insensitive():
    spec = osm_way_to_way_spec({"id": 100, "tags": {"oneway": " YES "}, "nodes": [1, 2]})

    assert spec.direction == "forward"


def test_unknown_oneway_value_falls_back_to_both():
    spec = osm_way_to_way_spec({"id": 100, "tags": {"oneway": "alternating"}, "nodes": [1, 2]})

    assert spec.direction == "both"


def test_way_with_fewer_than_two_nodes_returns_none():
    assert osm_way_to_way_spec({"id": 100, "tags": {}, "nodes": [1]}) is None
    assert osm_way_to_way_spec({"id": 100, "tags": {}, "nodes": []}) is None


def test_way_without_tags_key_defaults_to_both_direction():
    spec = osm_way_to_way_spec({"id": 100, "nodes": [1, 2]})

    assert spec is not None
    assert spec.direction == "both"
    assert spec.highway is None


def test_allowed_tags_are_kept_in_spec_tags():
    spec = osm_way_to_way_spec(
        {
            "id": 100,
            "tags": {"highway": "residential", "smoothness": "good", "lanes": "2", "maxspeed": "40"},
            "nodes": [1, 2],
        }
    )

    assert spec is not None
    assert spec.tags == {"smoothness": "good", "lanes": "2", "maxspeed": "40"}


def test_disallowed_tags_are_dropped_from_spec_tags():
    spec = osm_way_to_way_spec(
        {"id": 100, "tags": {"highway": "residential", "not_in_allowlist": "x"}, "nodes": [1, 2]}
    )

    assert spec is not None
    assert spec.tags == {}


def test_highway_surface_oneway_are_not_duplicated_into_tags():
    # highway/surface/onewayは専用フィールドで扱うため、tagsには含めない
    spec = osm_way_to_way_spec(
        {"id": 100, "tags": {"highway": "residential", "surface": "asphalt", "oneway": "yes"}, "nodes": [1, 2]}
    )

    assert spec is not None
    assert spec.tags == {}


def test_missing_tags_key_yields_empty_spec_tags():
    spec = osm_way_to_way_spec({"id": 100, "nodes": [1, 2]})

    assert spec is not None
    assert spec.tags == {}


def test_osm_ways_to_way_specs_filters_out_invalid_ways():
    raw_ways = [
        {"id": 100, "tags": {"highway": "residential"}, "nodes": [1, 2]},
        {"id": 101, "tags": {}, "nodes": [1]},  # ノード1未満は除外される
    ]

    specs = osm_ways_to_way_specs(raw_ways)

    assert len(specs) == 1
    assert specs[0].osm_way_id == 100


def test_osm_node_to_poi_spec_classifies_traffic_signals():
    spec = osm_node_to_poi_spec({"id": 200, "tags": {"highway": "traffic_signals"}, "lat": 35.7, "lon": 139.7})

    assert spec is not None
    assert spec.osm_node_id == 200
    assert spec.kind == "traffic_signals"
    assert spec.latitude == 35.7
    assert spec.longitude == 139.7


def test_osm_node_to_poi_spec_unrelated_node_returns_none():
    # 大多数の形状点（対象タグを持たないnode）はNone、取込対象外
    assert osm_node_to_poi_spec({"id": 200, "tags": {}, "lat": 35.7, "lon": 139.7}) is None


def test_osm_node_to_poi_spec_keeps_only_allowed_tags():
    spec = osm_node_to_poi_spec(
        {"id": 200, "tags": {"highway": "crossing", "crossing": "zebra", "name": "unrelated"}, "lat": 0.0, "lon": 0.0}
    )

    assert spec is not None
    assert spec.tags == {"highway": "crossing", "crossing": "zebra"}


def test_osm_nodes_to_poi_specs_filters_out_unrelated_nodes():
    raw_nodes = [
        {"id": 200, "tags": {"highway": "traffic_signals"}, "lat": 0.0, "lon": 0.0},
        {"id": 201, "tags": {}, "lat": 0.0, "lon": 0.0},
    ]

    specs = osm_nodes_to_poi_specs(raw_nodes)

    assert len(specs) == 1
    assert specs[0].osm_node_id == 200
