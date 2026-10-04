r"""派生の表の値の列ごとに、値の分布を1行で出す。

落ちた絞り込み・二重に数えた値はエラーにもテストの失敗にもならず、値の偏りとしてだけ現れる。
本番の派生を作り直すたびに、全部の列のこの行を前と後で並べる（docs/conventions/deployment-sync.md「派生データの作り直し」）。

対象は宣言から導く（`app/infrastructure/derived_data_freshness.py: derived_tables`・`value_columns`）
——表・列を足しても、ここは変わらない。

1列につき1行で出すもの:
- 行数と、値のある（NULLでない）割合
- 数の列: 0でない割合・合計・分位（p10・p50・p90）・最大
- 真偽の列: 真の割合
- 文字の列: 値の種類の数

`--column`を付けなければ全部の派生の表の全部の値の列を測る。見たい表・列だけなら`--column`で絞る。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\run_probe.py scripts\derived_distribution.py   # 本番の全部の列（作り直しの前と後）
    .venv\Scripts\python.exe scripts\derived_distribution.py --column node_materials                  # 開発DBの表の全列
    .venv\Scripts\python.exe scripts\derived_distribution.py --column edge_materials.accident_count   # 開発DBの1列
"""

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import Boolean, Float, Integer, Numeric, String, text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.infrastructure.derived_data_freshness import derived_tables, value_columns  # noqa: E402

Kind = Literal["number", "boolean", "text", "other"]

_QUANTILES = (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))


@dataclass(frozen=True)
class Target:
    table: str
    column: str
    kind: Kind


def _kind(column_type: object) -> Kind:
    if isinstance(column_type, Boolean):
        return "boolean"
    if isinstance(column_type, (Integer, Float, Numeric)):
        return "number"
    if isinstance(column_type, String):
        return "text"
    return "other"


def select_targets(names: list[str]) -> list[Target]:
    """`names`（`表`か`表.列`）に当たる値の列。空なら全派生表の全値列。"""
    declared = [
        Target(table.name, column, _kind(table.c[column].type))
        for table in derived_tables() for column in value_columns(table)
    ]
    if not names:
        return declared
    picked = [target for target in declared
              if target.table in names or f"{target.table}.{target.column}" in names]
    known = {target.table for target in declared} | {f"{t.table}.{t.column}" for t in declared}
    unknown = [name for name in names if name not in known]
    if unknown:
        raise SystemExit(f"派生の表の値の列として宣言されていない: {', '.join(unknown)}")
    return picked


def distribution_sql(table: str, targets: list[Target]) -> str:
    """1つの表の`targets`を1回の走査で集計するSQL。名前は宣言からのみ組み立てる。"""
    items = ["count(*) AS total"]
    for index, target in enumerate(targets):
        column = target.column
        items.append(f"count({column}) AS c{index}_present")
        if target.kind == "number":
            quantiles = ", ".join(str(q) for _, q in _QUANTILES)
            items += [
                f"count(*) FILTER (WHERE {column} <> 0) AS c{index}_nonzero",
                f"sum({column})::float8 AS c{index}_sum",
                f"percentile_cont(ARRAY[{quantiles}]) WITHIN GROUP (ORDER BY {column}) AS c{index}_q",
                f"max({column})::float8 AS c{index}_max",
            ]
        elif target.kind == "boolean":
            items.append(f"count(*) FILTER (WHERE {column}) AS c{index}_true")
        elif target.kind == "text":
            items.append(f"count(DISTINCT {column}) AS c{index}_kinds")
    return f"SELECT {', '.join(items)} FROM {table}"


def _share(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "-"


def _number(value: float | None) -> str:
    if value is None:
        return "-"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:.3g}"


def format_line(target: Target, index: int, row: dict) -> str:
    total = row["total"]
    present = row[f"c{index}_present"]
    parts = [f"行 {total:,}", f"値あり {_share(present, total)}"]
    if target.kind == "number":
        quantiles = row[f"c{index}_q"] or [None] * len(_QUANTILES)
        parts += [
            f"0でない {_share(row[f'c{index}_nonzero'], total)}",
            f"合計 {_number(row[f'c{index}_sum'])}",
            *(f"{name} {_number(value)}" for (name, _), value in zip(_QUANTILES, quantiles)),
            f"最大 {_number(row[f'c{index}_max'])}",
        ]
    elif target.kind == "boolean":
        parts.append(f"真 {_share(row[f'c{index}_true'], total)}")
    elif target.kind == "text":
        parts.append(f"種類 {row[f'c{index}_kinds']:,}")
    return f"{target.table}.{target.column}: " + " / ".join(parts)


async def collect(url: str, targets: list[Target]) -> list[str]:
    by_table: dict[str, list[Target]] = {}
    for target in targets:
        by_table.setdefault(target.table, []).append(target)
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            lines = []
            for table, columns in by_table.items():
                row = (await conn.execute(text(distribution_sql(table, columns)))).mappings().one()
                lines += [format_line(target, index, dict(row)) for index, target in enumerate(columns)]
            return lines
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="派生の表の値の列ごとの分布を出す")
    parser.add_argument("--column", action="append", default=[],
                        help="測る`表`か`表.列`（繰り返せる。既定: 全派生表の全値列）")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args(argv)
    url = args.database_url or os.environ.get("PROBE_DATABASE_URL")
    if url is None:
        from app.config import settings

        url = settings.database_url
    for line in asyncio.run(collect(url, select_targets(args.column))):
        print(line)
    return 0


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
