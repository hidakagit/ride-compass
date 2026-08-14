"""PBF取込プロファイル（app/batch/profile.py）の読み込み・マッチングの検証。"""

import pytest

from app.batch.profile import ElementRule, ProfileError, load_profile, matching_rule, rule_matches

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
            VALID_PROFILE.replace("element_type: way", "element_type: node"),
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
