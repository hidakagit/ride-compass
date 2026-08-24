"""評価軸定義（axis_definitions/axis_registry_meta）のPostGIS永続化層（改善計画T221 Stage D）。

書き込みメソッドは一切commitしない（road_graph_repository.pyと同じ規約。呼び出し側
[services/axis_registry_service.py]が操作のまとまりごとに`commit()`を呼んで確定する）。

shape_paramsの(逆)シリアライズは`AxisShape.model_dump(mode="json")` /
`TypeAdapter(AxisShape).validate_python(...)`にそのまま委ねる。`CategoricalShape.mapping`の
`dict[bool, float]`キーはmode="json"でJSON文字列"true"/"false"へ変換され、TypeAdapter側でも
bool型フィールドとして正しく往復することを確認済み（実装時に実データで検証）。
"""

from datetime import datetime, timezone

from pydantic import TypeAdapter
from sqlalchemy import delete, select, update
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

    async def get_revision(self) -> int | None:
        return await self._session.scalar(select(AxisRegistryMetaRow.revision).where(AxisRegistryMetaRow.id == 1))

    async def _bump_revision(self) -> None:
        await self._session.execute(
            update(AxisRegistryMetaRow)
            .where(AxisRegistryMetaRow.id == 1)
            .values(revision=AxisRegistryMetaRow.revision + 1)
        )

    async def commit(self) -> None:
        await self._session.commit()
