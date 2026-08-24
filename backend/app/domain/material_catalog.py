"""評価軸が参照する材料（material）の正式カタログ（改善計画T277）。

`domain/axis_definitions.py: AXIS_DEFINITIONS`の各軸（`MaterialTerm.material`・
`CategoricalShape.material`・`FlagSumShape.flags`）が参照する材料idは、これまで
`AXIS_DEFINITIONS`のコメントに散文で説明されるだけで、正式な一覧として宣言されていな
かった（軸スタジオ実装時、フロント側`axisMaterialsCatalog.ts`が独自にハードコードして
いた）。本モジュールがその単一ソースになる。

**材料の「登録」と「評価軸での利用」は独立している（改善計画T290）**: MVTタイル
（`road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL`）には、既存7軸が実際に使う
材料以外にも多くの生データ（highway・surface・smoothness・bicycle_infra等）が
既に焼き込まれている。設計の一貫性のため、これらも「評価や地図描画に使えそうな
生データ」として本カタログへ網羅的に登録する（ユーザー方針、2026-08-24）。
`dtype="categorical"`の材料（highway・bicycle_infra等、文字列多値）は改善計画T292で
`domain/axis_definitions.py: CategoricalShape.mapping`が`dict[bool|str, float]`へ拡張され、
実際に評価軸（`car_stress_highway_base`等）から使われている（登録時点[T290]では
真偽値限定のため未対応だったが、そのDEFERはT292のcar_stress軸階層化で解消済み）。

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

MaterialDType = Literal["numeric", "boolean", "categorical"]


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


# 現行7公開軸＋car_stressを支える内部軸6つが参照する材料（AXIS_DEFINITIONSのコメントと
# 1:1対応）＋改善計画T290で追加した生データ（MVTタイルに焼き込み済みだが評価軸には
# 未使用のものを含む。カタログ冒頭のT290注記参照）。改善計画T292でcar_stress_levelを
# 撤去・is_designatedを追加した（旧専用Pythonレシピの廃止に伴う入れ替え）。
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
    # --- 改善計画T290: MVTタイルに焼き込み済みだが評価軸には未使用の生データ ---
    "bridge": MaterialSpec(
        material_id="bridge",
        label="橋・高架",
        dtype="boolean",
        # OSMのbridgeタグ（yesのみtrue、それ以外はキー省略＝unknown/false扱い）。
        tile_property="bridge",
    ),
    "motor_vehicle_no": MaterialSpec(
        material_id="motor_vehicle_no",
        label="自動車通行不可",
        dtype="boolean",
        # OSMのmotor_vehicleタグがnoの区間（car_stress_levelのレシピ内部でも参照される
        # 材料だが、レシピ合成前の生の真偽値自体は独立して材料登録していなかった）。
        tile_property="motor_vehicle_no",
    ),
    "oneway": MaterialSpec(
        material_id="oneway",
        label="一方通行",
        dtype="boolean",
        # osm_raw_ways.direction（forward/backward/both）から算出（改善計画T289で
        # 一次属性・地図レイヤーとして先行追加済み、本材料登録はその生値の網羅登録）。
        tile_property="oneway",
    ),
    "maxspeed_kmh": MaterialSpec(
        material_id="maxspeed_kmh",
        label="制限速度(km/h)",
        dtype="numeric",
        tile_property="maxspeed_kmh",
    ),
    "lanes_count": MaterialSpec(
        material_id="lanes_count",
        label="車線数",
        dtype="numeric",
        tile_property="lanes_count",
    ),
    "highway": MaterialSpec(
        material_id="highway",
        label="道路種別",
        dtype="categorical",
        # OSMのhighwayタグ生値（motorway/trunk/primary/secondary/tertiary/residential/
        # living_street/unclassified/track/cycleway/path/footway等）。取込プロファイル
        # （import_pbf.py: ALLOWED_HIGHWAY_TYPES）で許可された値のみ実際に現れる。
        # 正準の閉じた値集合はこのプロジェクトで管理していない（OSMタグの生値のため）。
        tile_property="highway",
    ),
    "surface": MaterialSpec(
        material_id="surface",
        label="路面種別",
        dtype="categorical",
        # OSMのsurfaceタグ生値（正規化: lower/btrim）。良否の正準分類は
        # domain/road.py: GOOD_OSM_SURFACE_TAGS/BAD_OSM_SURFACE_TAGS参照（本材料は
        # その分類前の生タグ値そのもの。分類後の真偽値は既存材料surface_good）。
        tile_property="surface",
    ),
    "bicycle_infra": MaterialSpec(
        material_id="bicycle_infra",
        label="自転車インフラ種別",
        dtype="categorical",
        # domain/traffic.py: classify_bicycle_infrastructureの分類値
        # （separated/lane/shared_busway/shared_pedestrian/prohibited/roadway。
        # unknownはタイル側でプロパティ省略として表現され現れない）。
        tile_property="bicycle_infra",
    ),
    "cycleway_class": MaterialSpec(
        material_id="cycleway_class",
        label="自転車レーン種別",
        dtype="categorical",
        # 車ストレスのcycleway補正が参照する3値（track/lane/shared）。bicycle_infraより
        # 粗い分類（bicycle_infraのseparated/lane/shared_buswayに相当する部分集合）。
        tile_property="cycleway_class",
    ),
    "designation": MaterialSpec(
        material_id="designation",
        label="指定路線",
        dtype="categorical",
        # 国土数値情報N10/N12該当区分（emergency_transport/critical_logistics/both、
        # 外部静的データソースT51）。未該当はタイル側でプロパティ省略。
        tile_property="designation",
    ),
    "is_designated": MaterialSpec(
        material_id="is_designated",
        label="指定路線該当（真偽）",
        dtype="boolean",
        # 改善計画T292: car_stress軸の内部軸（designation由来の調整軸）が使う簡略化された
        # 真偽値材料。指定路線の種別（emergency_transport/critical_logistics/both、材料
        # "designation"）は評価パイプライン側で種別ごとに区別して保持していない
        # （domain/designation.py: 補正量が種別によらず一律+1のため、種別を評価まで
        # 運ぶ配線を新設する理由が無い）。"designation"材料自体は将来種別を区別する軸が
        # 必要になった時点でそちらを使う（トリガー付きDEFER、設計原則9）。car_stress_level
        # と同じくタイル非依存（評価時にdesignated_edge_idsから都度算出）。
        tile_property=None,
    ),
    "smoothness": MaterialSpec(
        material_id="smoothness",
        label="路面の状態",
        dtype="categorical",
        # OSMのsmoothnessタグ生値（excellent/good/intermediate/bad/very_bad/horrible/
        # very_horrible/impassable、正規化: lower/btrim）。surfaceが路面「種別」なのに
        # 対し、smoothnessは実際の走行感（同じasphaltでも荒れ具合が違う等）。
        tile_property="smoothness",
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
