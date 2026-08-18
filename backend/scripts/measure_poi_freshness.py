"""T101（補給・休憩ポイントPOIレイヤー）候補タグの実店舗との乖離リスクを、
OSMデータ自体の鮮度（`check_date`/`survey:date`タグの有無、要素の最終編集日時）から
推定する（改善計画T101、ユーザー懸念「実店舗とどれだけ合っているか」への回答材料）。

コンビニ・自販機等は閉店・移転が頻繁なジャンルのため、タグの正誤そのものはPBFから
直接検証できない（外部の実店舗リストが要る）。代わりにOSM側の「いつ最後に確認・
編集されたか」を鮮度の代理指標として使う: `check_date`/`survey:date`が付与されている
ノードは実地確認済みである可能性が高く、無い場合も要素の最終編集日時（`n.timestamp`、
pbf_source.py参照）が古いほど「作成後だれも確認していない＝閉店等に気づかれず
放置されている」リスクが高いと推定できる。measure_tag_coverage.py（T102の前例）と
同じ「PBF1パス読み・単発実行・結果を標準出力」の形式。

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

# T101本文（improvement-plan.md）が挙げる候補タグ。(key, value)のいずれかに一致すれば対象。
CANDIDATE_POI_TAGS: frozenset[tuple[str, str]] = frozenset(
    {
        ("shop", "convenience"),
        ("amenity", "vending_machine"),
        ("amenity", "toilets"),
        ("amenity", "drinking_water"),
        ("amenity", "bicycle_parking"),
    }
)

# 編集日時の鮮度バケット境界（年）。1年未満／1-2年／2-3年／3-5年／5年以上。
_AGE_BUCKET_BOUNDS_YEARS = (1, 2, 3, 5)


def node_matches(tags: dict[str, str]) -> tuple[str, str] | None:
    """T101候補タグのいずれかに一致すればその(key, value)を返す。複数一致時は
    CANDIDATE_POI_TAGSの定義順（frozensetのため不定）ではなく、最初に見つかった
    ものを代表として1件のみ返す（ノードが複数タグを併せ持つケースは稀なため、
    重複計上より単純な代表選出を優先）。"""
    for key, value in CANDIDATE_POI_TAGS:
        if tags.get(key) == value:
            return key, value
    return None


def age_bucket(years: float) -> str:
    """経過年数を鮮度バケットのラベルへ変換する（純粋関数、単体テスト対象）。"""
    for bound in _AGE_BUCKET_BOUNDS_YEARS:
        if years < bound:
            prev = _AGE_BUCKET_BOUNDS_YEARS[_AGE_BUCKET_BOUNDS_YEARS.index(bound) - 1] if bound != 1 else 0
            return f"{prev}-{bound}年" if prev else f"{bound}年未満"
    return f"{_AGE_BUCKET_BOUNDS_YEARS[-1]}年以上"


class FreshnessCounter:
    """タグ別の件数・check_date/survey:date付与率・編集日時の鮮度バケット分布を集計する
    （PBF I/Oから独立、単体テスト対象）。"""

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
        buckets = ["1年未満", "1-2年", "2-3年", "3-5年", "5年以上"]
        for tag in sorted(self.total_by_tag, key=lambda t: -self.total_by_tag[t]):
            total = self.total_by_tag[tag]
            checked = self.checked_by_tag[tag]
            lines.append(f"{tag[0]}={tag[1]}: {total}件（check_date/survey:date付与率 {self._pct(checked, total):.1f}%）")
            for bucket in buckets:
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
    sys.exit(main())
