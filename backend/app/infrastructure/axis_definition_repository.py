"""評価軸定義（axis_definitions/axis_registry_meta）のPostGIS永続化層。

書き込みメソッドは一切commitしない（road_graph_repository.pyと同じ規約。呼び出し側
[services/axis_registry_service.py]が操作のまとまりごとに`commit()`を呼んで確定する）。

JSONB列との(逆)シリアライズはPydanticへそのまま委ねる。`CategoricalShape.mapping`の
`dict[bool | str, float]`キーは`mode="json"`でJSON文字列("true"/"false"、または通常の
文字列キー)へ変換され、読み戻しでは`CategoricalShape`が"true"/"false"だけを真偽へ戻す。
"""

from datetime import datetime, timezone

from pydantic import TypeAdapter
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.axis_definitions import AxisDefinition, AxisShape, PriorityCondition
from app.infrastructure.axis_definition_models import AxisDefinitionRow, AxisRegistryMetaRow

_SHAPE_ADAPTER: TypeAdapter[AxisShape] = TypeAdapter(AxisShape)
_PRIORITY_OVERRIDES_ADAPTER: TypeAdapter[list[PriorityCondition]] = TypeAdapter(list[PriorityCondition])

# 書き込み系操作（`AxisRegistryAdminService`）は「読み取り→Python側で検証→書き込み」の
# 手順を踏むため、直列化しないとTOCTOUレースになる（2つのcreate()が互いのsort_orderや
# 材料の排他帰属の判定を古いスナップショットの上で行い、衝突した状態が残る）。
# DBレベルのadvisory lockを使うのは、プロセスをまたいでも効くようにするため
# （asyncio.Lockは同一プロセス内でしか効かない）。
# キー値自体に意味は無く、他のadvisory lock用途と衝突しない固定値であればよい。
_WRITE_LOCK_KEY = 0x4158495344454653


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
        display_thresholds_override=row.display_thresholds_override,
        display_band_labels_override=row.display_band_labels_override,
        dedicated_way_value_layer=row.dedicated_way_value_layer,
        dynamic_way_value_needs_time=row.dynamic_way_value_needs_time,
        dynamic_way_value_needs_bearing=row.dynamic_way_value_needs_bearing,
        dynamic_way_value_needs_speed=row.dynamic_way_value_needs_speed,
    )


class AxisDefinitionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def acquire_write_lock(self) -> None:
        """axis_definitionsへの書き込み系操作（create/update/delete/unpublish）の冒頭で
        呼ぶ。トランザクションスコープのadvisory lock（_WRITE_LOCK_KEY参照）を取得し、
        呼び出し側のcommit()/セッション終了時のrollbackで自動的に解放される。"""
        await self._session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _WRITE_LOCK_KEY})

    async def list_all(self) -> dict[str, AxisDefinition]:
        """axis_idキーの辞書。sort_order昇順（挿入順=合成の加算順）を保つ。"""
        return {
            axis_id: definition
            for axis_id, (definition, _sort_order) in (await self.list_all_with_sort_order()).items()
        }

    async def list_all_with_sort_order(self) -> dict[str, tuple[AxisDefinition, int]]:
        """`list_all()`と同じ全件だが、各軸のsort_orderも保持する。
        `AxisRegistryAdminService.create`/`update`が「既存軸の列挙」と「更新対象1件の
        sort_order取得」の両方をこの1回のSELECTから賄う。"""
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
            display_thresholds_override=definition.display_thresholds_override,
            display_band_labels_override=definition.display_band_labels_override,
            dedicated_way_value_layer=definition.dedicated_way_value_layer,
            dynamic_way_value_needs_time=definition.dynamic_way_value_needs_time,
            dynamic_way_value_needs_bearing=definition.dynamic_way_value_needs_bearing,
            dynamic_way_value_needs_speed=definition.dynamic_way_value_needs_speed,
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
                "display_thresholds_override": stmt.excluded.display_thresholds_override,
                "display_band_labels_override": stmt.excluded.display_band_labels_override,
                "dedicated_way_value_layer": stmt.excluded.dedicated_way_value_layer,
                "dynamic_way_value_needs_time": stmt.excluded.dynamic_way_value_needs_time,
                "dynamic_way_value_needs_bearing": stmt.excluded.dynamic_way_value_needs_bearing,
                "dynamic_way_value_needs_speed": stmt.excluded.dynamic_way_value_needs_speed,
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
        """行数のみ（一括投入の前に、テーブルが空かどうかを確認する経路が使う）。"""
        return await self._session.scalar(select(func.count()).select_from(AxisDefinitionRow)) or 0

    async def delete_all(self) -> int:
        """全行を削除する（一括投入の前にテーブルを空にするために使う）。

        `upsert`/`delete`と違いrevisionを進めない——呼び出し側が一括投入の締めくくりで
        `set_revision`するため、途中のrevision操作に意味が無い。
        """
        result = await self._session.execute(delete(AxisDefinitionRow))
        return result.rowcount or 0

    async def get_revision(self) -> int | None:
        return await self._session.scalar(select(AxisRegistryMetaRow.revision).where(AxisRegistryMetaRow.id == 1))

    async def set_revision(self, revision: int) -> None:
        """revisionを指定値へ直接セットする（一括投入がダンプ時点の値を復元するために使う）。"""
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
