"""評価軸定義（axis_definitions/axis_registry_meta）のPostGIS永続化層（改善計画T221 Stage D）。

書き込みメソッドは一切commitしない（road_graph_repository.pyと同じ規約。呼び出し側
[services/axis_registry_service.py]が操作のまとまりごとに`commit()`を呼んで確定する）。

shape_paramsの(逆)シリアライズは`AxisShape.model_dump(mode="json")` /
`TypeAdapter(AxisShape).validate_python(...)`にそのまま委ねる。`CategoricalShape.mapping`の
`dict[bool | str, float]`キーはmode="json"でJSON文字列("true"/"false"、または通常の
文字列キー)へ変換され、TypeAdapter側は`union_mode="left_to_right"`でbool判定を先に
試すため、bool材料・str多値材料のどちらも正しく往復する（改善計画T292、実データ検証済み。
既定のsmart mode unionだと"true"/"false"がbool化されずstr型のまま残る回帰があったため
明示指定した）。

priority_overrides（改善計画T292、0次条件）も同様に`list[PriorityCondition]`を
`model_dump(mode="json")`したJSON配列としてそのまま往復する。

display_override（改善計画T310、地図ramp表示の手書き上書き。T404で廃止方針が決まり、
car_stress/stop_density/accidentの3軸を移行済みだったことを確認したうえで改善計画T409で
フィールド・DBカラムごと削除した）は、以前は`AxisDisplaySpec.model_dump(mode="json")` /
`TypeAdapter(AxisDisplaySpec).validate_python(...)`で同じ規約の往復をしていたが、現在は
このリポジトリが扱うフィールドではない。

display_thresholds_override（改善計画T404、地図の色分けしきい値だけの軽量な上書き）は
単純な`list[float] | None`のため、JSONB列とPythonの`list`/`None`をそのまま素通しする
（他の2フィールドと異なりPydanticモデルへの往復変換自体が不要）。
"""

from datetime import datetime, timezone

from pydantic import TypeAdapter
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.axis_definitions import AxisDefinition, AxisShape, PriorityCondition
from app.infrastructure.axis_definition_models import AxisDefinitionRow, AxisRegistryMetaRow

_SHAPE_ADAPTER: TypeAdapter[AxisShape] = TypeAdapter(AxisShape)
_PRIORITY_OVERRIDES_ADAPTER: TypeAdapter[list[PriorityCondition]] = TypeAdapter(list[PriorityCondition])


def _row_to_definition(row: AxisDefinitionRow) -> AxisDefinition:
    return AxisDefinition(
        axis_id=row.axis_id,
        shape=_SHAPE_ADAPTER.validate_python(row.shape_params),
        default_weight=row.default_weight,
        label=row.label,
        description=row.description,
        category=row.category,
        is_published=row.is_published,
        priority_overrides=_PRIORITY_OVERRIDES_ADAPTER.validate_python(row.priority_overrides),
        icon_id=row.icon_id,
        chip_label=row.chip_label,
        panel_hint=row.panel_hint,
        show_map_icon=row.show_map_icon,
        time_scope=row.time_scope,
        supports_route_coloring=row.supports_route_coloring,
        display_thresholds_override=row.display_thresholds_override,
    )


class AxisDefinitionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_all(self) -> dict[str, AxisDefinition]:
        """axis_idキーの辞書。sort_order昇順（挿入順=合成の加算順）を保つ。"""
        rows = (
            (await self._session.execute(select(AxisDefinitionRow).order_by(AxisDefinitionRow.sort_order)))
            .scalars()
            .all()
        )
        return {row.axis_id: _row_to_definition(row) for row in rows}

    async def list_all_with_sort_order(self) -> dict[str, tuple[AxisDefinition, int]]:
        """`list_all()`と同じ全件だが、各軸のsort_orderも保持する（改善計画T271の
        レビュー指摘の修正: `AxisRegistryAdminService.create`/`update`が「既存軸の
        列挙」と「更新対象1件のsort_order取得」のために`list_all()`＋`get()`を
        2回に分けてSELECTしていたのを1回へ集約するため新設）。"""
        rows = (
            (await self._session.execute(select(AxisDefinitionRow).order_by(AxisDefinitionRow.sort_order)))
            .scalars()
            .all()
        )
        return {row.axis_id: (_row_to_definition(row), row.sort_order) for row in rows}

    async def get(self, axis_id: str) -> tuple[AxisDefinition, int] | None:
        """定義とsort_orderの組。updateがsort_orderを維持するために使う。"""
        row = (
            await self._session.execute(select(AxisDefinitionRow).where(AxisDefinitionRow.axis_id == axis_id))
        ).scalar_one_or_none()
        if row is None:
            return None
        return _row_to_definition(row), row.sort_order

    async def upsert(self, definition: AxisDefinition, sort_order: int) -> None:
        stmt = pg_insert(AxisDefinitionRow).values(
            axis_id=definition.axis_id,
            sort_order=sort_order,
            shape_params=definition.shape.model_dump(mode="json"),
            default_weight=definition.default_weight,
            label=definition.label,
            description=definition.description,
            category=definition.category,
            is_published=definition.is_published,
            priority_overrides=[cond.model_dump(mode="json") for cond in definition.priority_overrides],
            icon_id=definition.icon_id,
            chip_label=definition.chip_label,
            panel_hint=definition.panel_hint,
            show_map_icon=definition.show_map_icon,
            time_scope=definition.time_scope,
            supports_route_coloring=definition.supports_route_coloring,
            display_thresholds_override=definition.display_thresholds_override,
            updated_at=datetime.now(timezone.utc),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[AxisDefinitionRow.axis_id],
            set_={
                "sort_order": stmt.excluded.sort_order,
                "shape_params": stmt.excluded.shape_params,
                "default_weight": stmt.excluded.default_weight,
                "label": stmt.excluded.label,
                "description": stmt.excluded.description,
                "category": stmt.excluded.category,
                "is_published": stmt.excluded.is_published,
                "priority_overrides": stmt.excluded.priority_overrides,
                "icon_id": stmt.excluded.icon_id,
                "chip_label": stmt.excluded.chip_label,
                "panel_hint": stmt.excluded.panel_hint,
                "show_map_icon": stmt.excluded.show_map_icon,
                "time_scope": stmt.excluded.time_scope,
                "supports_route_coloring": stmt.excluded.supports_route_coloring,
                "display_thresholds_override": stmt.excluded.display_thresholds_override,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await self._session.execute(stmt)
        await self._bump_revision()

    async def delete(self, axis_id: str) -> bool:
        result = await self._session.execute(delete(AxisDefinitionRow).where(AxisDefinitionRow.axis_id == axis_id))
        deleted = bool(result.rowcount)
        if deleted:
            await self._bump_revision()
        return deleted

    async def count(self) -> int:
        """行数のみ（改善計画T361: fresh bootstrap用スナップショット読み込み前の状態確認に使う。
        `infrastructure/axis_definitions_snapshot.py`参照）。"""
        return await self._session.scalar(select(func.count()).select_from(AxisDefinitionRow)) or 0

    async def delete_all(self) -> int:
        """全行を削除する（改善計画T361: fresh bootstrap専用のスナップショット読み込みが、
        投入前にテーブルを丸ごと空にするために使う。`upsert`/`delete`と違い個別revisionの
        +1は行わない——呼び出し側[`load_axis_definitions_snapshot`]がこの後の一括投入の
        締めくくりでスナップショット由来のrevisionへ直接セットするため、ここでの
        中間的なrevision操作は無意味）。"""
        result = await self._session.execute(delete(AxisDefinitionRow))
        return result.rowcount or 0

    async def get_revision(self) -> int | None:
        return await self._session.scalar(select(AxisRegistryMetaRow.revision).where(AxisRegistryMetaRow.id == 1))

    async def set_revision(self, revision: int) -> None:
        """revisionを指定値へ直接セットする（改善計画T361: スナップショット読み込み後、
        ダンプ時点の値を復元するために使う。通常の書き込み[`upsert`/`delete`]が使う
        `_bump_revision`の+1方式とは別の、直接代入の経路）。"""
        await self._session.execute(
            update(AxisRegistryMetaRow).where(AxisRegistryMetaRow.id == 1).values(revision=revision)
        )

    async def _bump_revision(self) -> None:
        await self._session.execute(
            update(AxisRegistryMetaRow)
            .where(AxisRegistryMetaRow.id == 1)
            .values(revision=AxisRegistryMetaRow.revision + 1)
        )

    async def commit(self) -> None:
        await self._session.commit()
