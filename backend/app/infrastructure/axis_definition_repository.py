"""評価軸定義（axis_definitions）のPostGIS永続化層。

書き込みメソッドは一切commitしない（road_graph_repository.pyと同じ規約。呼び出し側
[services/axis_registry_service.py]が操作のまとまりごとに`commit()`を呼んで確定する）。

JSONB列との(逆)シリアライズはPydanticへそのまま委ねる。`CategoricalShape.mapping`の
`dict[bool | str, float]`キーは`mode="json"`でJSON文字列("true"/"false"、または通常の
文字列キー)へ変換され、読み戻しでは`CategoricalShape`が"true"/"false"だけを真偽へ戻す。
"""

from datetime import datetime, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.axis_definitions import AxisDefinition
from app.infrastructure.axis_definition_models import AxisDefinitionRow

# 書き込み系操作（`AxisRegistryAdminService`）は「読み取り→Python側で検証→書き込み」の
# 手順を踏むため、直列化しないとTOCTOUレースになる（2つのcreate()が互いのsort_orderや
# 材料の排他帰属の判定を古いスナップショットの上で行い、衝突した状態が残る）。
# DBレベルのadvisory lockを使うのは、プロセスをまたいでも効くようにするため
# （asyncio.Lockは同一プロセス内でしか効かない）。
# キー値自体に意味は無く、他のadvisory lock用途と衝突しない固定値であればよい。
_WRITE_LOCK_KEY = 0x4158495344454653


#: 軸定義の欄のうち、行の列の名前が違うもの（ほかの欄は同じ名前の列に入る）。
_COLUMN_OF_FIELD = {"shape": "shape_params"}


def _row_to_definition(row: AxisDefinitionRow) -> AxisDefinition:
    return AxisDefinition.model_validate(
        {name: getattr(row, _COLUMN_OF_FIELD.get(name, name)) for name in AxisDefinition.model_fields})


def _row_values(definition: AxisDefinition) -> dict[str, object]:
    """書く列の値。読み書きする欄は軸定義の欄（`model_fields`）から導く——欄を1つずつ書くと、軸定義に足した欄を
    書き落としても、読み戻しで既定へ黙って戻るだけで気づけない（列を足し忘れれば、書くときに断られる）。"""
    dumped = definition.model_dump(mode="json")
    return {_COLUMN_OF_FIELD.get(name, name): dumped[name] for name in AxisDefinition.model_fields}


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

    async def upsert(self, definition: AxisDefinition, sort_order: int) -> None:
        values = {**_row_values(definition), "sort_order": sort_order, "updated_at": datetime.now(timezone.utc)}
        stmt = pg_insert(AxisDefinitionRow).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[AxisDefinitionRow.axis_id],
            set_={name: stmt.excluded[name] for name in values if name != "axis_id"},
        )
        await self._session.execute(stmt)

    async def delete(self, axis_id: str) -> bool:
        result = await self._session.execute(
            delete(AxisDefinitionRow).where(AxisDefinitionRow.axis_id == axis_id).returning(AxisDefinitionRow.axis_id))
        return result.first() is not None

    async def commit(self) -> None:
        await self._session.commit()
