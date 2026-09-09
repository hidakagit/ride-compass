"""PBF取込プロファイル（app/batch/profile.py）の読み込み・マッチングの検証。"""

from pathlib import Path

import pytest

from app.batch.profile import ElementRule, ProfileError, load_profile, matching_rule, rule_matches

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[1] / "app" / "batch" / "import_profile.yaml"

VALID_PROFILE = """
version: 1
elements:
  - name: roads
    element_type: way
    match:
      highway: "*"
    target: osm_raw_ways
"""


def _write_profile(tmp_path, content: str):
    path = tmp_path / "profile.yaml"
    path.write_text(content, encoding="utf-8")
    return path


class TestLoadProfile:
    def test_valid_profile(self, tmp_path):
        profile = load_profile(_write_profile(tmp_path, VALID_PROFILE))
        assert profile.version == 1
        assert len(profile.rules) == 1
        rule = profile.rules[0]
        assert rule.name == "roads"
        assert rule.element_type == "way"
        assert rule.match == {"highway": "*"}
        assert rule.target == "osm_raw_ways"

    def test_profile_hash_tracks_file_content(self, tmp_path):
        first = load_profile(_write_profile(tmp_path, VALID_PROFILE))
        second = load_profile(_write_profile(tmp_path, VALID_PROFILE + "\n# comment"))
        assert first.profile_hash != second.profile_hash
        assert len(first.profile_hash) == 64  # SHA-256 hex

    def test_string_match_value_is_normalized_to_list(self, tmp_path):
        content = VALID_PROFILE.replace('highway: "*"', "highway: residential")
        profile = load_profile(_write_profile(tmp_path, content))
        assert profile.rules[0].match == {"highway": ["residential"]}

    @pytest.mark.parametrize(
        "content",
        [
            VALID_PROFILE.replace("version: 1", "version: 2"),
            VALID_PROFILE.replace("element_type: way", "element_type: relation"),
            VALID_PROFILE.replace("target: osm_raw_ways", "target: unknown_table"),
            "version: 1\nelements: []\n",
            VALID_PROFILE.replace('highway: "*"', "highway: 123"),
        ],
        ids=["bad-version", "unsupported-element-type", "unsupported-target", "empty-elements", "bad-match-value"],
    )
    def test_invalid_profiles_raise(self, tmp_path, content):
        with pytest.raises(ProfileError):
            load_profile(_write_profile(tmp_path, content))


class TestRuleMatches:
    def _rule(self, match) -> ElementRule:
        return ElementRule(name="r", element_type="way", match=match, target="osm_raw_ways")

    def test_wildcard_requires_tag_presence_only(self):
        rule = self._rule({"highway": "*"})
        assert rule_matches(rule, {"highway": "residential"})
        assert rule_matches(rule, {"highway": "motorway", "surface": "asphalt"})
        assert not rule_matches(rule, {"surface": "asphalt"})

    def test_value_list_restricts_allowed_values(self):
        rule = self._rule({"amenity": ["drinking_water", "toilets"]})
        assert rule_matches(rule, {"amenity": "drinking_water"})
        assert not rule_matches(rule, {"amenity": "cafe"})

    def test_multiple_keys_are_and_matched(self):
        rule = self._rule({"highway": "*", "surface": ["asphalt"]})
        assert rule_matches(rule, {"highway": "residential", "surface": "asphalt"})
        assert not rule_matches(rule, {"highway": "residential"})
        assert not rule_matches(rule, {"highway": "residential", "surface": "gravel"})


class TestMatchingRule:
    def test_returns_first_matching_rule_for_element_type(self, tmp_path):
        profile = load_profile(_write_profile(tmp_path, VALID_PROFILE))
        assert matching_rule(profile, "way", {"highway": "residential"}) is profile.rules[0]
        assert matching_rule(profile, "way", {"building": "yes"}) is None
        # element_typeが違えばタグがマッチしても対象外
        assert matching_rule(profile, "node", {"highway": "residential"}) is None


class TestDefaultProfile:
    """実運用のimport_profile.yaml自体が正しくパースでき、静的道路属性P1の
    node系ルール（highway=*系とrailway=level_crossingのOR分割）が意図通り
    マッチすることを確認する（YAML手書き変更に対する回帰検知）。"""

    def test_default_profile_loads(self):
        profile = load_profile(DEFAULT_PROFILE_PATH)
        assert profile.version == 1

    def test_stop_inducing_highway_nodes_match(self):
        profile = load_profile(DEFAULT_PROFILE_PATH)
        assert matching_rule(profile, "node", {"highway": "traffic_signals"}) is not None
        assert matching_rule(profile, "node", {"highway": "crossing"}) is not None
        assert matching_rule(profile, "node", {"highway": "stop"}) is not None
        assert matching_rule(profile, "node", {"highway": "give_way"}) is not None

    def test_shared_pedestrian_ways_match(self):
        # 改善計画T99: 自転車歩行者共用道（highway=footway/path AND bicycle=yes/designated/
        # permissive）が取り込まれ、単独のfootway/path（bicycle未設定）は引き続き除外されること。
        profile = load_profile(DEFAULT_PROFILE_PATH)
        for highway in ("footway", "path"):
            for bicycle in ("yes", "designated", "permissive"):
                rule = matching_rule(profile, "way", {"highway": highway, "bicycle": bicycle})
                assert rule is not None, f"highway={highway} bicycle={bicycle} should match"
                assert rule.target == "osm_raw_ways"
        assert matching_rule(profile, "way", {"highway": "footway"}) is None
        assert matching_rule(profile, "way", {"highway": "path", "bicycle": "no"}) is None
        assert matching_rule(profile, "way", {"highway": "pedestrian", "bicycle": "yes"}) is None

    def test_railway_level_crossing_matches(self):
        profile = load_profile(DEFAULT_PROFILE_PATH)
        rule = matching_rule(profile, "node", {"railway": "level_crossing"})
        assert rule is not None
        assert rule.target == "osm_raw_pois"

    def test_unrelated_node_does_not_match(self):
        profile = load_profile(DEFAULT_PROFILE_PATH)
        assert matching_rule(profile, "node", {"amenity": "bench"}) is None

    def test_convenience_stores_match(self):
        # 改善計画T101（補給・休憩ポイントPOIレイヤー）。
        profile = load_profile(DEFAULT_PROFILE_PATH)
        rule = matching_rule(profile, "node", {"shop": "convenience"})
        assert rule is not None
        assert rule.target == "osm_raw_pois"
        assert matching_rule(profile, "node", {"shop": "supermarket"}) is None

    def test_supply_amenity_nodes_match(self):
        # 改善計画T101: コンビニ以外の4種（自販機・トイレ・給水・駐輪場）。
        profile = load_profile(DEFAULT_PROFILE_PATH)
        for amenity in ("vending_machine", "toilets", "drinking_water", "bicycle_parking"):
            rule = matching_rule(profile, "node", {"amenity": amenity})
            assert rule is not None, f"amenity={amenity} should match"
            assert rule.target == "osm_raw_pois"

    def test_barrier_and_traffic_calming_nodes_match(self):
        profile = load_profile(DEFAULT_PROFILE_PATH)
        for barrier in ("cycle_barrier", "bollard", "gate", "lift_gate", "block", "turnstile"):
            assert matching_rule(profile, "node", {"barrier": barrier}) is not None, barrier
        # 停止要因にならない車止め値は取り込まない（段差・料金所・塀の開口部）。
        for barrier in ("kerb", "toll_booth", "entrance", "fence"):
            assert matching_rule(profile, "node", {"barrier": barrier}) is None, barrier
        for calming in ("hump", "bump", "chicane", "choker"):
            assert matching_rule(profile, "node", {"traffic_calming": calming}) is not None, calming
        assert matching_rule(profile, "node", {"traffic_calming": "island"}) is None

    def test_railway_crossings_match_both_road_and_path(self):
        profile = load_profile(DEFAULT_PROFILE_PATH)
        for railway in ("level_crossing", "crossing", "tram_level_crossing", "tram_crossing"):
            rule = matching_rule(profile, "node", {"railway": railway})
            assert rule is not None, railway
            assert rule.target == "osm_raw_pois"
        assert matching_rule(profile, "node", {"railway": "switch"}) is None


class TestProfileMatchesClassifier:
    """プロファイル（どのnodeをPBFから拾うか）とdomain側の分類器（拾ったnodeをどのkindへ
    分類するか）が食い違わないことを固定する。

    取込は「プロファイルで拾う→分類器がkindを返す→osm_raw_poisへ書く」の順で、**分類器が
    Noneを返したnodeは黙って捨てられる**（osm_adapter.py: osm_node_to_poi_spec）。そのため
    プロファイルにルールを足しただけでは何も取り込まれず、逆に分類器だけ足してもPBFから
    そのnodeが流れてこない。どちらの片側変更もテストが赤くならなければ気づけないため、
    ここで両方向を突き合わせる。
    """

    def _node_tag_combinations(self, rule: ElementRule) -> list[dict[str, str]]:
        """ルールが受理するタグ辞書の代表例（値リストの直積）。"""
        keys = sorted(rule.match)
        value_lists = [rule.match[k] if rule.match[k] != "*" else ["*"] for k in keys]
        combos: list[dict[str, str]] = [{}]
        for key, values in zip(keys, value_lists, strict=True):
            combos = [{**combo, key: value} for combo in combos for value in values]
        return combos

    def test_every_node_the_profile_takes_is_classified(self):
        from app.domain.osm_adapter import osm_node_to_poi_spec

        profile = load_profile(DEFAULT_PROFILE_PATH)
        for rule in profile.rules:
            if rule.element_type != "node":
                continue
            for tags in self._node_tag_combinations(rule):
                spec = osm_node_to_poi_spec({"id": 1, "tags": tags, "lat": 35.0, "lon": 139.0})
                assert spec is not None, f"{rule.name}: {tags} はプロファイルが拾うのに分類できない"

    def test_every_classified_kind_reaches_the_stop_poi_count(self):
        """停止要因として分類したkindが、集計対象の集合（STOP_POI_KINDS）に必ず入る。"""
        from app.domain.osm_adapter import osm_node_to_poi_spec
        from app.domain.traffic import STOP_POI_KINDS, SupplyPoiKind, classify_supply_poi

        supply_kinds = set(SupplyPoiKind.__args__)
        profile = load_profile(DEFAULT_PROFILE_PATH)
        seen: set[str] = set()
        for rule in profile.rules:
            if rule.element_type != "node":
                continue
            for tags in self._node_tag_combinations(rule):
                spec = osm_node_to_poi_spec({"id": 1, "tags": tags, "lat": 35.0, "lon": 139.0})
                assert spec is not None
                seen.add(spec.kind)
                if classify_supply_poi(tags) is None:
                    assert spec.kind in STOP_POI_KINDS, f"{tags} のkind={spec.kind}が集計対象外"
        # 補給POIと停止要因POIの両方を1度は通っていること（片方だけの取り違え検知）。
        assert seen & supply_kinds
        assert seen & set(STOP_POI_KINDS)
