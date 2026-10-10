"""材料の表の結び方。

材料の式は、区間に付く値を別名`em`、道1本に付く値を別名`wm`の列として読む（`domain/material_sql.py`）。
その2つの別名を与えるFROM句は`material_from_clause`だけが組み立てる。どの列がどの表にあるかは宣言から
導き、式が読む列を持つ表だけを主キーで結ぶ。区間の表か道の表かは主キーの列で決まる。
"""

import re
from collections.abc import Iterable

from sqlalchemy import Column
from sqlalchemy.dialects import postgresql

from app.infrastructure.derived_models import RoadEdgeRow
from app.infrastructure.orm_base import DERIVED_KEY, declared_metadata

_EDGE_KEY = ("osm_way_id", "segment_index")
_WAY_KEY = ("osm_way_id",)


def _material_columns(key: tuple[str, ...]) -> dict[str, Column]:
    """主キーの列が`key`の派生の表（区間の形の`road_edges`を除く）の、鍵でない列。名前→列。

    同じ名前の列を2つの表が持つと、別名の列がどちらの表から来るかが決まらないので送出する。
    """
    columns: dict[str, Column] = {}
    for table in declared_metadata().sorted_tables:
        if (not table.info.get(DERIVED_KEY) or table is RoadEdgeRow.__table__
                or tuple(column.name for column in table.primary_key.columns) != key):
            continue
        for column in table.columns:
            if column.primary_key:
                continue
            if column.name in columns:
                raise RuntimeError(
                    f"材料の表 {columns[column.name].table.name} と {table.name} が同じ列 {column.name} を持つ")
            columns[column.name] = column
    return columns


_EDGE_MATERIAL_COLUMNS = _material_columns(_EDGE_KEY)
_WAY_MATERIAL_COLUMNS = _material_columns(_WAY_KEY)

#: 逆向きで入れ替わる語の対。列名がこの規則に従う限り、対応表を手で並べる必要がない。
_REVERSING_TOKEN_PAIRS = (("start_", "end_"), ("_gain_", "_loss_"))


def reversed_material_expression(name: str) -> str | None:
    """逆向きの枝でこの列へ入る式（入れ替える相手の列を別名`m`で読む）。向きで変わらない列はNone。

    対になる語を入れ替え、`_grade`で終わる量は符号を返す。標高は地形の物理量で進行方向に依存しないため、
    この変換は厳密に正しい（形状点列を逆順に辿ると各区間の差分の符号がすべて反転する）。
    """
    swapped = name
    for first, second in _REVERSING_TOKEN_PAIRS:
        if first in swapped:
            swapped = swapped.replace(first, second, 1)
            break
        if second in swapped:
            swapped = swapped.replace(second, first, 1)
            break
    negated = name.endswith("_grade")
    if swapped == name and not negated:
        return None
    return ("-" if negated else "") + "m." + swapped


#: 区間の列→逆向きで読む相手の列と、符号を返すか。
_REVERSED_EDGE_COLUMNS: dict[str, tuple[str, bool]] = {
    name: (expression.lstrip("-").removeprefix("m."), expression.startswith("-"))
    for name in _EDGE_MATERIAL_COLUMNS
    if (expression := reversed_material_expression(name)) is not None
}

#: 入れ替え先の列が無ければSQLは実行時に落ちる。import時に気づけるようにする。
_missing_partners = sorted(partner for partner, _ in _REVERSED_EDGE_COLUMNS.values()
                           if partner not in _EDGE_MATERIAL_COLUMNS)
if _missing_partners:
    raise RuntimeError(f"逆向きの列が存在しない: {_missing_partners}")

_MATERIAL_REFERENCE = re.compile(r"(?<![\w.])(em|wm)\.(\w+)")


def material_from_clause(
    expressions: Iterable[str], way_id: str, segment_index: str | None = None, *,
    forward: str | None = None, way_when_no_segment: bool = False,
) -> str:
    """`expressions`が読む`em`・`wm`の列を与えるJOINの並び。読む列を持つ表だけを、主キーで`way_id`
    （と`segment_index`）の式へ外部結合する。呼び出し側はFROM句の行の後ろへそのまま続ける。

    `em`は、`segment_index`を渡せば区間の値、Noneなら道1本の値（区間の表と同じ名前の道の列。道に無い列はNULL）。
    `way_when_no_segment`は、`segment_index`の式がNULLの行を道1本の値で読む（区間と道丸ごとが混ざるタイル）。区間の行か
    道丸ごとの行のどちらかでしか読まない表は、その行のときだけ引く。
    `forward`（真なら順方向）を渡すと、`em`の向きで変わる列を逆向きの行で入れ替え・符号反転する。

    式が宣言に無い列を読めば送出する——SQLの実行まで気づかないと、その経路の読み出しが材料ぶん丸ごと落ちる。
    """
    names: dict[str, set[str]] = {"em": set(), "wm": set()}
    for expression in expressions:
        for alias, name in _MATERIAL_REFERENCE.findall(expression):
            if name not in (_EDGE_MATERIAL_COLUMNS if alias == "em" else _WAY_MATERIAL_COLUMNS):
                raise ValueError(f"材料の式が宣言に無い列を読む: {alias}.{name}")
            names[alias].add(name)

    # 表ごとの、読む行の種類（区間の行だけ・道丸ごとの行だけ・どちらも=None）。
    tables: dict = {}

    def read(column: Column, rows: str | None = None) -> str:
        table = column.table
        tables[table] = rows if tables.get(table, rows) == rows else None
        return f"t_{table.name}.{column.name}"

    edge_rows = "segment" if way_when_no_segment else None

    def edge_value(name: str) -> str:
        value = read(_EDGE_MATERIAL_COLUMNS[name], edge_rows)
        if forward is None or name not in _REVERSED_EDGE_COLUMNS:
            return value
        partner, negated = _REVERSED_EDGE_COLUMNS[name]
        reverse = ("-" if negated else "") + read(_EDGE_MATERIAL_COLUMNS[partner], edge_rows)
        return f"CASE WHEN {forward} THEN {value} ELSE {reverse} END"

    def way_value(name: str, rows: str | None = None) -> str | None:
        column = _WAY_MATERIAL_COLUMNS.get(name)
        return None if column is None else read(column, rows)

    selects: dict[str, list[str]] = {"em": [], "wm": []}
    for name in sorted(names["em"]):
        if segment_index is None:
            value = way_value(name) or (
                f"CAST(NULL AS {_EDGE_MATERIAL_COLUMNS[name].type.compile(dialect=postgresql.dialect())})")
        elif way_when_no_segment:
            way = way_value(name, "way")
            value = (f"CASE WHEN {segment_index} IS NOT NULL THEN {edge_value(name)}"
                     + (f" ELSE {way}" if way is not None else "") + " END")
        else:
            value = edge_value(name)
        selects["em"].append(f"{value} AS {name}")
    for name in sorted(names["wm"]):
        selects["wm"].append(f"{read(_WAY_MATERIAL_COLUMNS[name])} AS {name}")

    lines = []
    for table, rows in sorted(tables.items(), key=lambda item: item[0].name):
        on = f"t_{table.name}.osm_way_id = {way_id}"
        if tuple(column.name for column in table.primary_key.columns) == _EDGE_KEY:
            on += f" AND t_{table.name}.segment_index = {segment_index}"
        if rows is None:
            lines.append(f"LEFT JOIN {table.name} t_{table.name} ON {on}")
            continue
        # 片方の種類の行でしか読まない表は、その行のときだけ引く。結合の条件に足すだけでは、もう片方の行でも
        # 主キーを引きにいく。`OFFSET 0`は副問い合わせを外へ畳ませないためのもの——畳まれると同じことになる。
        on = on.replace(f"t_{table.name}.", "x.")
        when = f"{segment_index} IS {'NOT ' if rows == 'segment' else ''}NULL"
        lines.append(f"LEFT JOIN LATERAL (SELECT * FROM {table.name} x WHERE {on} AND {when} OFFSET 0)"
                     f" t_{table.name} ON true")
    lines += [f"CROSS JOIN LATERAL (SELECT {', '.join(select)}) {alias}"
              for alias, select in selects.items() if select]
    return "".join(f"\n{line}" for line in lines) + "\n"


def edge_material_table(expression: str) -> str:
    """`expression`が読む区間の値（`em`）の列を持つ表の名前。区間1本にその表の行は0か1なので、表を別名`em`で
    直に走査すれば、区間へ結ばずに値のある区間を数えられる。

    `em`の列を1つの表からだけ読む式でなければ送出する（`wm`を読む・2つの表にまたがる・宣言に無い列を読む）。
    """
    tables = set()
    for alias, name in _MATERIAL_REFERENCE.findall(expression):
        if alias != "em" or name not in _EDGE_MATERIAL_COLUMNS:
            raise ValueError(f"区間の値の表1つで読めない式: {alias}.{name}")
        tables.add(_EDGE_MATERIAL_COLUMNS[name].table.name)
    if len(tables) != 1:
        raise ValueError(f"区間の値の表1つで読めない式: {expression}")
    return tables.pop()
