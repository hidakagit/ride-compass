"""動的＋向きあり材料の「way_id→値」配信（改善計画T411、T423で実施）が対象とする材料の
宣言。docs/tasks/T400.md「2. 動的要素…は状態（ルートの有無）に応じてパラメータの出所と
塗る対象が変わる」節の状態機械へ乗る各材料が、実際に何のパラメータ（時刻・向き）を必要と
するかをここで宣言する——これが「材料ごとに違う」唯一の部分で、状態機械そのもの
（ルート未確定=ユーザー指定パラメータを全道路へ一律適用／ルート確定後=ルート自身の実値を
ルート線のみへ適用）は材料非依存のまま`docs/tasks/T400.md`・各サービス実装が共通で守る。

`infrastructure/dynamic_way_value_cache.py`（キャッシュキーのbucket化要否）・
`api/routers/region.py`（`GET /api/region/dynamic-way-values/{material_id}/{z}/{x}/{y}`の
クエリパラメータ必須/省略判定）の両方がこの宣言を読む。
"""

from dataclasses import dataclass


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


# 改善計画T423: 勾配（第2の具体例）を追加。新しい動的＋向きあり材料を追加するときは、
# ここへ1エントリ足すだけでエンドポイントのバリデーション（region.py）・キャッシュの
# bucket化（dynamic_way_value_cache.py）へ自動的に反映される。
DYNAMIC_WAY_VALUE_MATERIALS: dict[str, DynamicWayValueMaterial] = {
    "wind": DynamicWayValueMaterial(material_id="wind", label="風", needs_time=True, needs_bearing=True),
    "gradient": DynamicWayValueMaterial(material_id="gradient", label="勾配", needs_time=False, needs_bearing=True),
}
