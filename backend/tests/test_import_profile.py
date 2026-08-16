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
