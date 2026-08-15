"""静的道路属性タグの実カバレッジ計測（docs/static-road-attributes-plan.md §3 P0手順2）。

PBF抽出ファイルを1パス読みし、import_profile.yamlの取込対象wayについて
`osm_adapter.ALLOWED_WAY_TAGS`（P0で保持している属性タグ）の付与率を集計する。
width/shoulder等、計画書でカバレッジ実測待ちとしていたP1/P2判断の根拠にする。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\measure_tag_coverage.py --pbf data/pbf/kanto-latest.osm.pbf
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.profile import load_profile, matching_rule  # noqa: E402
from app.domain.osm_adapter import ALLOWED_WAY_TAGS  # noqa: E402

# highwayをおおまかな3群へ（import_profile.yamlの取込対象種別を分類）。
# 「residentialの大半はlanes/maxspeed無し」（計画書§3）等の仮説をhighway別に検証する。
_HIGHWAY_GROUPS = {
    "trunk": "幹線",
    "trunk_link": "幹線",
    "primary": "幹線",
    "primary_link": "幹線",
    "secondary": "幹線",
    "secondary_link": "幹線",
    "tertiary": "幹線",
    "tertiary_link": "幹線",
    "unclassified": "生活道路",
    "residential": "生活道路",
    "living_street": "生活道路",
    "cycleway": "自転車専用",
    "track": "自転車専用",
}
_GROUP_ORDER = ["幹線", "生活道路", "自転車専用", "その他"]


def highway_group(highway: str | None) -> str:
    return _HIGHWAY_GROUPS.get(highway or "", "その他")


class CoverageCounter:
    """タグ付与率の集計（PBF I/Oから独立、単体テスト可能な純粋ロジック）。"""

    def __init__(self, tags_of_interest: frozenset[str]):
        self._tags = tags_of_interest
        self.total = 0
        self.total_by_group: Counter[str] = Counter()
        self.tag_count: Counter[str] = Counter()
        self.tag_count_by_group: Counter[tuple[str, str]] = Counter()

    def add(self, highway: str | None, tags: dict[str, str]) -> None:
        self.total += 1
        group = highway_group(highway)
        self.total_by_group[group] += 1
        for tag in self._tags:
            value = tags.get(tag)
            if value is not None and str(value).strip() != "":
                self.tag_count[tag] += 1
                self.tag_count_by_group[(tag, group)] += 1

    @staticmethod
    def _pct(count: int, total: int) -> float:
        return (count / total * 100) if total else 0.0

    def report_lines(self) -> list[str]:
        lines = [f"対象way数: {self.total}件（import_profile.yamlの取込対象にマッチしたもの）"]
        for group in _GROUP_ORDER:
            count = self.total_by_group.get(group, 0)
            if count:
                lines.append(f"  {group}: {count}件")
        lines.append("")
        header = f"{'タグ':<16}{'全体':>8}" + "".join(f"{g:>10}" for g in _GROUP_ORDER)
        lines.append(header)
        for tag in sorted(self._tags, key=lambda t: -self.tag_count[t]):
            overall = self._pct(self.tag_count[tag], self.total)
            row = f"{tag:<16}{overall:>7.1f}%"
            for group in _GROUP_ORDER:
                pct = self._pct(self.tag_count_by_group[(tag, group)], self.total_by_group.get(group, 0))
                row += f"{pct:>9.1f}%"
            lines.append(row)
        return lines


def measure(pbf_path: Path, profile_path: Path, tags_of_interest: frozenset[str]) -> CoverageCounter:
    # 遅延import: pyosmium（requirements-batch.txt）はこのスクリプト実行時にのみ必要
    from app.batch import pbf_source

    profile = load_profile(profile_path)
    counter = CoverageCounter(tags_of_interest)

    def tag_filter(tags: dict[str, str]) -> bool:
        return matching_rule(profile, "way", tags) is not None

    def sink(raw_way: dict, _coords: dict[int, tuple[float, float]]) -> None:
        counter.add(raw_way["tags"].get("highway"), raw_way["tags"])

    pbf_source.stream_ways(pbf_path, tag_filter, sink)
    return counter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", default="data/pbf/kanto-latest.osm.pbf", help="計測対象のPBFファイル")
    parser.add_argument(
        "--profile",
        default=str(Path(__file__).resolve().parents[1] / "app" / "batch" / "import_profile.yaml"),
        help="取込プロファイル（YAML）のパス",
    )
    args = parser.parse_args(argv)

    pbf_path = Path(args.pbf)
    if not pbf_path.is_file():
        print(f"PBFファイルが見つかりません: {pbf_path}", file=sys.stderr)
        return 1

    counter = measure(pbf_path, Path(args.profile), ALLOWED_WAY_TAGS)
    for line in counter.report_lines():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
