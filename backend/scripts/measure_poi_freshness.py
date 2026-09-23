"""補給・休憩ポイントのPOIが実店舗とどれだけ合っているかを、OSMデータ自体の鮮度から
推定する。

コンビニ・自販機等は閉店・移転が頻繁なジャンルのため、タグの正誤そのものはPBFから
直接検証できない（外部の実店舗リストが要る）。代わりにOSM側の「いつ最後に確認・
編集されたか」を鮮度の代理指標として使う: `check_date`/`survey:date`が付与されている
ノードは実地確認済みである可能性が高く、無い場合も要素の最終編集日時が古いほど
「作成後だれも確認していない＝閉店等に気づかれず放置されている」リスクが高い。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\measure_poi_freshness.py --pbf data/pbf/kanto-latest.osm.pbf
"""

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: 対象とするPOIのタグ。(key, value)のいずれかに一致すれば対象。
CANDIDATE_POI_TAGS: frozenset[tuple[str, str]] = frozenset(
    {
        ("shop", "convenience"),
        ("amenity", "vending_machine"),
        ("amenity", "toilets"),
        ("amenity", "drinking_water"),
        ("amenity", "bicycle_parking"),
    }
)

#: 編集日時の鮮度バケットの境界（年）。表示するラベルはここから導く。
_AGE_BUCKET_BOUNDS_YEARS = (1, 2, 3, 5)
_AGE_BUCKET_LABELS: tuple[str, ...] = tuple(
    f"{previous}-{bound}年" if previous else f"{bound}年未満"
    for previous, bound in zip((0, *_AGE_BUCKET_BOUNDS_YEARS), _AGE_BUCKET_BOUNDS_YEARS)
) + (f"{_AGE_BUCKET_BOUNDS_YEARS[-1]}年以上",)


def node_matches(tags: dict[str, str]) -> tuple[str, str] | None:
    """対象タグのいずれかに一致すればその(key, value)を返す。

    複数のタグを併せ持つノードは、最初に見つかったもの1件だけを代表として数える
    （frozensetの走査順は決まっていないため、どれが代表になるかは指定できない）。
    """
    for key, value in CANDIDATE_POI_TAGS:
        if tags.get(key) == value:
            return key, value
    return None


def age_bucket(years: float) -> str:
    """経過年数を鮮度バケットのラベルへ変換する。"""
    for label, bound in zip(_AGE_BUCKET_LABELS, _AGE_BUCKET_BOUNDS_YEARS):
        if years < bound:
            return label
    return _AGE_BUCKET_LABELS[-1]


class FreshnessCounter:
    """タグ別の件数・check_date/survey:date付与率・編集日時の鮮度バケット分布。"""

    def __init__(self):
        self.total_by_tag: Counter[tuple[str, str]] = Counter()
        self.checked_by_tag: Counter[tuple[str, str]] = Counter()
        self.age_bucket_by_tag: Counter[tuple[tuple[str, str], str]] = Counter()

    def add(self, tag: tuple[str, str], tags: dict[str, str], edited_at: datetime, now: datetime) -> None:
        self.total_by_tag[tag] += 1
        if tags.get("check_date") or tags.get("survey:date"):
            self.checked_by_tag[tag] += 1
        years = (now - edited_at).days / 365.25
        self.age_bucket_by_tag[(tag, age_bucket(years))] += 1

    @staticmethod
    def _pct(count: int, total: int) -> float:
        return (count / total * 100) if total else 0.0

    def report_lines(self) -> list[str]:
        lines = []
        for tag in sorted(self.total_by_tag, key=lambda t: -self.total_by_tag[t]):
            total = self.total_by_tag[tag]
            checked = self.checked_by_tag[tag]
            lines.append(f"{tag[0]}={tag[1]}: {total}件（check_date/survey:date付与率 {self._pct(checked, total):.1f}%）")
            for bucket in _AGE_BUCKET_LABELS:
                count = self.age_bucket_by_tag[(tag, bucket)]
                lines.append(f"    最終編集{bucket}: {count}件（{self._pct(count, total):.1f}%）")
        if not self.total_by_tag:
            lines.append("（対象タグを持つnodeが見つかりませんでした）")
        return lines


def measure(pbf_path: Path, now: datetime | None = None) -> FreshnessCounter:
    # 遅延import: pyosmium（requirements-batch.txt）はこのスクリプト実行時にのみ必要。
    from app.batch import pbf_source

    now = now or datetime.now(timezone.utc)
    counter = FreshnessCounter()

    def node_tag_filter(tags: dict[str, str]) -> bool:
        return node_matches(tags) is not None

    def node_sink(raw_node: dict[str, Any]) -> None:
        tag = node_matches(raw_node["tags"])
        if tag is not None:
            counter.add(tag, raw_node["tags"], raw_node["timestamp"], now)

    def way_sink(_raw_way: dict, _coords: dict[int, tuple[float, float]]) -> None:
        return None

    pbf_source.stream_ways(pbf_path, lambda _tags: False, way_sink, node_tag_filter, node_sink)
    return counter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", default="data/pbf/kanto-latest.osm.pbf", help="計測対象のPBFファイル")
    args = parser.parse_args(argv)

    pbf_path = Path(args.pbf)
    if not pbf_path.is_file():
        print(f"PBFファイルが見つかりません: {pbf_path}", file=sys.stderr)
        return 1

    counter = measure(pbf_path)
    for line in counter.report_lines():
        print(line)
    return 0


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    sys.exit(main())
