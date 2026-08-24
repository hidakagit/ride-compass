"""評価軸が参照する材料（material）の正式カタログ（改善計画T277）。

`domain/axis_definitions.py: AXIS_DEFINITIONS`の各軸（`MaterialTerm.material`・
`CategoricalShape.material`・`FlagSumShape.flags`）が参照する材料idは、これまで
`AXIS_DEFINITIONS`のコメントに散文で説明されるだけで、正式な一覧として宣言されていな
かった（軸スタジオ実装時、フロント側`axisMaterialsCatalog.ts`が独自にハードコードして
いた）。本モジュールがその単一ソースになる。

**設計方針（ユーザー指示、2026-08-24）**: 材料は今後システムメンテナンス（コード変更＋
デプロイ）によって増減されうるものとして設計するが、材料自体をGUIから追加・編集・削除
できるようにはしない。軸スタジオ（`/admin`）が材料を選ぶ際は、本カタログを
`GET /api/material-catalog`経由で動的に取得する（`api/routers/material_catalog.py`）。
新しい材料を増やすときはこのファイルへ1件追加するだけで、フロントのコード変更・
再デプロイなしに軸コンポーザーの選択肢へ現れる。

`tile_property`/`tile_property_inverted`はMVTタイル（`road_graph_repository.py:
_ROAD_SURFACE_TILE_MVT_SQL`）に既に焼き込まれているプロパティ名（無ければ材料が
タイル非依存＝地図レイヤーのramp自動生成が不可能なことを表す）。`GET /api/material-catalog`
の公開レスポンスには含めない（フロントの軸コンポーザーが必要とするのは`material_id`/
`label`/`dtype`のみで、tileの内部実装詳細を露出させる理由が無いため）——地図表示ルール
自動生成タスク（T278、未起票）がbackend内部でのみこの2フィールドを使う想定。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

MaterialDType = Literal["numeric", "boolean"]


class MaterialSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    material_id: str
    label: str
    dtype: MaterialDType
    # MVTタイルへ既に焼き込み済みのプロパティ名。Noneは「タイル非依存」（GSI標高の都度取得、
    # 気象の動的取得、レシピ合成値等）で、地図レイヤーのramp自動生成対象になりえない。
    tile_property: str | None = None
    # tile_propertyの符号反転が必要か（例: no_lit材料はタイルのlitプロパティの否定）。
    tile_property_inverted: bool = False
    # 改善計画T278: tile_propertyの生値と材料の値がスケール不一致（実行時に変動する係数での
    # 変換が必要）な場合True。例: accident_count_per_km_yearは収録年数（実行時にDBから
    # 取得、増え続ける）で正規化済みだが、tile_propertyのaccident_per_kmは年正規化前の生値。
    # domain/axis_display.py: derive_ramp_inputsはこれがTrueの材料を含む軸のramp自動導出を
    # 拒否する（静的な変換係数を持てないため、閾値を安全に流用できない）。
    tile_property_needs_runtime_scale: bool = False


# 現行7軸が参照する9材料（AXIS_DEFINITIONSのコメントと1:1対応）。
MATERIAL_CATALOG: dict[str, MaterialSpec] = {
    "gradient_percent": MaterialSpec(
        material_id="gradient_percent",
        label="勾配%（符号付き）",
        dtype="numeric",
        # 標高は国土地理院APIから都度取得しDBへ恒久保存しない設計のため、タイルへ
        # 焼き込める事実データが無い（docs/architecture.md「標高計算」節参照）。
        tile_property=None,
    ),
    "wind_penalty": MaterialSpec(
        material_id="wind_penalty",
        label="向かい風ペナルティ(m/s、正=向かい風)",
        dtype="numeric",
        # 気象は動的データ（出発時刻依存）のためタイルに焼き込めない。
        tile_property=None,
    ),
    "surface_good": MaterialSpec(
        material_id="surface_good",
        label="舗装良否",
        dtype="boolean",
        tile_property="surface_good",
    ),
    "stop_count_per_km": MaterialSpec(
        material_id="stop_count_per_km",
        label="停止密度(回/km)",
        dtype="numeric",
        tile_property="stop_per_km",
    ),
    "intersection_count_per_km": MaterialSpec(
        material_id="intersection_count_per_km",
        label="交差点密度(回/km)",
        dtype="numeric",
        tile_property="intersection_per_km",
    ),
    "accident_count_per_km_year": MaterialSpec(
        material_id="accident_count_per_km_year",
        label="事故密度(件/(km・年))",
        dtype="numeric",
        # タイル側は年正規化前の"accident_per_km"（収録全年分の重み付き件数/km）。
        # 年正規化はAXIS_DEFINITIONS側の評価ロジックが行うため、ramp化する場合は
        # 閾値をタイル側のスケールへ再換算する必要がある。収録年数は実行時にDBから
        # 取得し増え続けるため、静的な変換係数を持てない（改善計画T278で判明、
        # registry_defaults.pyの既存accident表示は手書きのまま維持する）。
        tile_property="accident_per_km",
        tile_property_needs_runtime_scale=True,
    ),
    "car_stress_level": MaterialSpec(
        material_id="car_stress_level",
        label="車ストレスレベル(1-5、レシピ判定済み)",
        dtype="numeric",
        # highway×cycleway×maxspeed×lanes×指定路線のレシピ合成値で、単一のタイル
        # プロパティに対応しない（個々の入力タグはタイルにあるが、合成はフロントの
        # 手書きexpression[carStressExpression.ts]が担う。domain/recipe.py参照）。
        tile_property=None,
    ),
    "no_lit": MaterialSpec(
        material_id="no_lit",
        label="街灯なし",
        dtype="boolean",
        # タイルのlitはタグ有無の真偽（yesのみtrue、それ以外はNULL）。no_lit材料は
        # その否定（litタグ不在は街灯なしとみなす安全側の判断、domain/night.py参照）。
        tile_property="lit",
        tile_property_inverted=True,
    ),
    "has_tunnel": MaterialSpec(
        material_id="has_tunnel",
        label="トンネル",
        dtype="boolean",
        tile_property="tunnel",
    ),
}


def all_materials() -> list[MaterialSpec]:
    return list(MATERIAL_CATALOG.values())


def is_known_material(material_id: str) -> bool:
    return material_id in MATERIAL_CATALOG


def material_dtype(material_id: str) -> MaterialDType | None:
    """材料idのdtype（numeric/boolean）。未知の材料idにはNoneを返す
    （呼び出し側は`is_known_material`で存在確認済みの前提だが、念のため例外にはしない）。"""
    spec = MATERIAL_CATALOG.get(material_id)
    return spec.dtype if spec is not None else None
