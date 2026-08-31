"""動的＋向きあり材料の「way_id→値」配信（改善計画T411、T423で実施）が対象とする材料の
宣言。docs/tasks/T400.md「2. 動的要素…は状態（ルートの有無）に応じてパラメータの出所と
塗る対象が変わる」節の状態機械へ乗る各材料が、実際に何のパラメータ（時刻・向き）を必要と
するかをここで宣言する——これが「材料ごとに違う」唯一の部分で、状態機械そのもの
（ルート未確定=ユーザー指定パラメータを全道路へ一律適用／ルート確定後=ルート自身の実値を
ルート線のみへ適用）は材料非依存のまま`docs/tasks/T400.md`・各サービス実装が共通で守る。

`infrastructure/dynamic_way_value_cache.py`（キャッシュキーのbucket化要否）・
`api/routers/region.py`（`GET /api/region/dynamic-way-values/{material_id}/{z}/{x}/{y}`の
クエリパラメータ必須/省略判定）の両方が`dynamic_way_value_materials()`を読む。

改善計画T458: 以前はこのモジュールが軸スタジオ（`AxisDefinition.dedicated_way_value_layer`）
とは独立したPython辞書（`DYNAMIC_WAY_VALUE_MATERIALS`）へneeds_time/needs_bearingを
ハードコード宣言しており、3件目の動的材料を追加するには軸スタジオでの登録に加えて
コード変更・再デプロイが必要だった（設計原則8違反）。`AXIS_DEFINITIONS`
（`dedicated_way_value_layer=True`の軸）から動的に導出する関数へ置き換え、軸スタジオでの
登録だけで完結するようにした。material_id→サービス実装本体（`WindWayService`/
`GradientWayService`）の組み立ては別軸（`api/dependencies.py:
_DYNAMIC_WAY_VALUE_SERVICE_FACTORIES`、T460）で、各材料の計算ロジック自体は宣言的に
導出できないPythonコードのまま残る。
"""

from dataclasses import dataclass

from app.domain.axis_definitions import AXIS_DEFINITIONS


@dataclass(frozen=True)
class DynamicWayValueMaterial:
    material_id: str
    label: str
    # 時刻（`at`クエリパラメータ）に依存するか。風=Yes（気象予報が時々刻々変わる）、
    # 勾配=No（標高・道路の向きは時刻で変わらない、T400.md「2.」節で3例目にして初めて
    # 気づいた軸）。
    needs_time: bool
    # 向き（`bearing_deg`クエリパラメータ）に依存するか。風・勾配どちらもYes——向きの
    # *出所*（外部データ/道路自身に内在）が異なるだけで、パラメータとしては両方とも
    # ユーザー指定の走行方位を必要とする（T400.md「2.」節の3軸目）。
    needs_bearing: bool


def dynamic_way_value_materials() -> dict[str, DynamicWayValueMaterial]:
    """`AXIS_DEFINITIONS`から`dedicated_way_value_layer=True`の軸を抽出して導出する
    （改善計画T458）。`AXIS_DEFINITIONS`はプロセス起動時・管理API書き込み直後にin-place
    更新される（`services/axis_registry_service.py`参照）ため、モジュール読み込み時の
    定数ではなく呼び出しの都度導出する関数にする（`axis_catalog.py: get_axis_catalog`と
    同じ「プロセス内メモリへの都度アクセス」方式）。新しい動的＋向きあり材料を追加する
    ときは、軸スタジオで`dedicated_way_value_layer=true`・
    `dynamic_way_value_needs_time`/`dynamic_way_value_needs_bearing`を設定するだけで
    ここへ自動的に反映される。
    """
    return {
        axis_id: DynamicWayValueMaterial(
            material_id=axis_id,
            label=definition.label,
            needs_time=definition.dynamic_way_value_needs_time,
            needs_bearing=definition.dynamic_way_value_needs_bearing,
        )
        for axis_id, definition in AXIS_DEFINITIONS.items()
        if definition.dedicated_way_value_layer
    }
