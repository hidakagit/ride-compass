"""`amenity=vending_machine`が何を売る機械なのかを、PBFから数える。

派生側（`domain/traffic.py: tag_kind_sql`）が飲料と分かるもの・分からないもの・
口に入らないものへ分けるときの判定を、取り込む前のPBF全体に対して当ててみる器。
「この判定で何件が残り、何件が落ちるか」を再取込の前に知るために使う。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\measure_vending_types.py --pbf data/pbf/kanto-latest.osm.pbf
    .venv\\Scripts\\python.exe scripts\\measure_vending_types.py --top 40
"""

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.traffic import SUPPLY_VENDING_VALUES  # noqa: E402


#: 分類の呼び名。`classify`が返すものと、内訳に並べるものを1つにする。
_SUPPLY, _NOT_SUPPLY, _UNKNOWN = "補給に使える", "補給に使えない", "不明（vendingタグ無し）"


def classify(vending: str | None) -> str:
    """`vending`の値を分類する。

    判定に使う値の集合は派生側（`domain/traffic.py: SUPPLY_VENDING_VALUES`）と共有する
    ——別々に持つと、計測が「これだけ残る」と言った件数と実際に取り込まれる件数がずれる。
    """
    parts = {part.strip().lower() for part in (vending or "").split(";") if part.strip()}
    if not parts:
        return _UNKNOWN
    if parts & SUPPLY_VENDING_VALUES:
        return _SUPPLY
    return _NOT_SUPPLY


class VendingCounter:
    """`vending`の値の分布と分類の内訳を集計する。"""

    def __init__(self) -> None:
        self.by_value: Counter[str] = Counter()
        self.by_class: Counter[str] = Counter()

    def add(self, tags: dict[str, str]) -> None:
        vending = tags.get("vending")
        self.by_value[vending or "(タグ無し)"] += 1
        self.by_class[classify(vending)] += 1

    @property
    def total(self) -> int:
        return sum(self.by_value.values())

    def _pct(self, count: int) -> float:
        return (count / self.total * 100) if self.total else 0.0

    def report_lines(self, top: int) -> list[str]:
        if not self.total:
            return ["（amenity=vending_machineのnodeが見つかりませんでした）"]
        lines = [f"amenity=vending_machine: {self.total}件", "", "## 補給に使えるか"]
        for name in (_SUPPLY, _NOT_SUPPLY, _UNKNOWN):
            count = self.by_class[name]
            lines.append(f"  {name}: {count}件（{self._pct(count):.1f}%）")
        lines.extend(["", f"## vendingの値（上位{top}）"])
        for value, count in self.by_value.most_common(top):
            lines.append(f"  {value}: {count}件（{self._pct(count):.1f}%）")
        remaining = len(self.by_value) - top
        if remaining > 0:
            lines.append(f"  （残り{remaining}種類は省略）")
        return lines


def measure(pbf_path: Path) -> VendingCounter:
    # 遅延import: pyosmium（requirements-batch.txt）はこのスクリプト実行時にのみ必要。
    from app.batch import pbf_source

    counter = VendingCounter()

    def node_tag_filter(tags: dict[str, str]) -> bool:
        return tags.get("amenity") == "vending_machine"

    def node_sink(raw_node: dict[str, Any]) -> None:
        counter.add(raw_node["tags"])

    def way_sink(_raw_way: dict, _coords: dict[int, tuple[float, float]]) -> None:
        return None

    pbf_source.stream_ways(pbf_path, lambda _tags: False, way_sink, node_tag_filter, node_sink)
    return counter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", default="data/pbf/kanto-latest.osm.pbf", help="計測対象のPBFファイル")
    parser.add_argument("--top", type=int, default=25, help="vendingの値の表示件数")
    args = parser.parse_args(argv)

    pbf_path = Path(args.pbf)
    if not pbf_path.is_file():
        print(f"PBFファイルが見つかりません: {pbf_path}", file=sys.stderr)
        return 1

    for line in measure(pbf_path).report_lines(args.top):
        print(line)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
