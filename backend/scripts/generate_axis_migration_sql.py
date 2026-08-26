"""`domain/axis_definitions.py: AXIS_DEFINITIONS`（Python正本）の内容から、
`axis_definitions`テーブルへ反映するmigration用SQL文を機械的に生成する（改善計画T348）。

T347で`bicycle_infra_quality`軸のshapeを再設計した際、対応するmigration
（`migrations/0021_bicycle_infra_axis.sql`）のJSON表現を人間が手で書き直し、
`model_dump(mode="json")`の出力と目視で一致確認する作業を複数回繰り返した。この
「Python側の変更を人間がSQLへ手で転記し、食い違いに気付かないまま古いmigrationが
残ってしまう」ドリフト（`tests/test_migrate.py`が実際に検知した、migration 0017の
`shape_params`がT336の再設計に追従せず取り残されていた実例）を防ぐため、転記作業自体を
このスクリプトへ委譲する。

**このスクリプトは「新しいmigrationファイルを自動では作らない」**（改善計画T348の
設計方針: 組み込み軸ごとに1本のmigrationファイルを人間が意図して追加する既存の
連番運用[0014〜0021]は維持し、GUI編集済みの下書き軸を意図せず巻き込む一括再シードは
行わない）。標準出力へ貼り付け可能なSQL文を出すだけで、ファイルへどう配置するかは
呼び出し側が判断する。

実行方法（backendディレクトリから、DB接続不要）:
    .venv\\Scripts\\python.exe scripts\\generate_axis_migration_sql.py car_stress bicycle_infra_quality
    .venv\\Scripts\\python.exe scripts\\generate_axis_migration_sql.py --all
    .venv\\Scripts\\python.exe scripts\\generate_axis_migration_sql.py new_axis_id --insert --sort-order 14

既定はUPDATE文（既存の組み込み軸のshapeやweight等を変更した場合の想定用途）。
`--insert`を付けると新規追加する組み込み軸向けのINSERT文を出す（`--sort-order`必須、
DB接続をしないため既存の最大値は呼び出し側が`axis_definitions`テーブルを見て指定する。
`AxisRegistryAdminService.create()`の「既存最大+1」と同じ原則）。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition  # noqa: E402


def _sql_string_literal(value: str) -> str:
    """SQL文字列リテラル用にシングルクォートをエスケープする（'→''）。"""
    return "'" + value.replace("'", "''") + "'"


def _sql_json_literal(value: object) -> str:
    """JSONBカラム用のリテラル。NoneはNULL、それ以外はJSON文字列化してエスケープする。"""
    if value is None:
        return "NULL"
    return _sql_string_literal(json.dumps(value, ensure_ascii=False))


def _sql_bool_literal(value: bool) -> str:
    return "true" if value else "false"


def _sql_nullable_string_literal(value: str | None) -> str:
    return "NULL" if value is None else _sql_string_literal(value)


def render_update(definition: AxisDefinition) -> str:
    """既存行を更新するUPDATE文を1本返す（このスクリプトの既定モード）。"""
    columns = {
        "shape_params": _sql_json_literal(definition.shape.model_dump(mode="json")) + "::jsonb",
        "default_weight": repr(definition.default_weight),
        "label": _sql_string_literal(definition.label),
        "description": _sql_string_literal(definition.description),
        "category": _sql_string_literal(definition.category),
        "is_published": _sql_bool_literal(definition.is_published),
        "priority_overrides": _sql_json_literal(
            [cond.model_dump(mode="json") for cond in definition.priority_overrides]
        )
        + "::jsonb",
        "icon_id": _sql_nullable_string_literal(definition.icon_id),
        "chip_label": _sql_nullable_string_literal(definition.chip_label),
        "panel_hint": _sql_nullable_string_literal(definition.panel_hint),
        "show_map_icon": _sql_bool_literal(definition.show_map_icon),
        "display_override": (
            "NULL"
            if definition.display_override is None
            else _sql_json_literal(definition.display_override.model_dump(mode="json")) + "::jsonb"
        ),
    }
    assignments = ",\n    ".join(f"{name} = {value}" for name, value in columns.items())
    return (
        f"UPDATE axis_definitions SET\n    {assignments}\n"
        f"WHERE axis_id = {_sql_string_literal(definition.axis_id)};"
    )


def render_insert(definition: AxisDefinition, sort_order: int) -> str:
    """新規行を追加するINSERT文を1本返す（`--insert --sort-order`指定時）。"""
    columns = {
        "axis_id": _sql_string_literal(definition.axis_id),
        "sort_order": str(sort_order),
        "shape_params": _sql_json_literal(definition.shape.model_dump(mode="json")) + "::jsonb",
        "default_weight": repr(definition.default_weight),
        "label": _sql_string_literal(definition.label),
        "description": _sql_string_literal(definition.description),
        "category": _sql_string_literal(definition.category),
        "is_published": _sql_bool_literal(definition.is_published),
        "priority_overrides": _sql_json_literal(
            [cond.model_dump(mode="json") for cond in definition.priority_overrides]
        )
        + "::jsonb",
        "icon_id": _sql_nullable_string_literal(definition.icon_id),
        "chip_label": _sql_nullable_string_literal(definition.chip_label),
        "panel_hint": _sql_nullable_string_literal(definition.panel_hint),
        "show_map_icon": _sql_bool_literal(definition.show_map_icon),
        "display_override": (
            "NULL"
            if definition.display_override is None
            else _sql_json_literal(definition.display_override.model_dump(mode="json")) + "::jsonb"
        ),
    }
    column_names = ", ".join(columns)
    column_values = ", ".join(columns.values())
    return f"INSERT INTO axis_definitions\n    ({column_names})\nVALUES\n    ({column_values});"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("axis_ids", nargs="*", help="対象のaxis_id（複数指定可）")
    parser.add_argument("--all", action="store_true", help="AXIS_DEFINITIONS全件を対象にする")
    parser.add_argument(
        "--insert", action="store_true", help="UPDATEではなくINSERT文を出す（新規axis_id向け）"
    )
    parser.add_argument(
        "--sort-order", type=int, default=None, help="--insert時に必須。axis_definitions.sort_orderの値"
    )
    args = parser.parse_args()

    if args.all:
        axis_ids = list(AXIS_DEFINITIONS)
    else:
        axis_ids = args.axis_ids
    if not axis_ids:
        parser.error("axis_idを1つ以上指定するか --all を付けてください")

    unknown = [axis_id for axis_id in axis_ids if axis_id not in AXIS_DEFINITIONS]
    if unknown:
        parser.error(f"AXIS_DEFINITIONSに存在しないaxis_id: {', '.join(unknown)}")

    if args.insert:
        if args.sort_order is None:
            parser.error("--insert指定時は --sort-order も指定してください")
        if len(axis_ids) != 1:
            parser.error("--insertは1軸ずつ指定してください（sort_orderが1つしか渡せないため）")
        print(render_insert(AXIS_DEFINITIONS[axis_ids[0]], args.sort_order))
        return 0

    for axis_id in axis_ids:
        print(render_update(AXIS_DEFINITIONS[axis_id]))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
