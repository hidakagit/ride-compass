// 二次軸（推定指標）のカタログ。
//
// 実行時の`GET /api/axis-catalog`が配る軸のうち表示情報を持つもの（display!==null）を
// 要約として並べる（軸スタジオが作る新規軸も、材料がタイル焼き込み済みならここへ自動で
// 入る）。読むのは軸→一次属性の解決（page.tsx: 材料の観測データレイヤーとの連動判定）と、
// 軸の材料内訳（lib/evaluationAxes.ts）。
//
// 正式名・略名・アイコンは軸自身のデータ（正本は本番DBの軸定義）をそのまま使う。
// 合成軸もkind="ramp"で、他のkind="ramp"軸と同じくaxisMapLayerId経由で専用レイヤーを持つ。

import { axisMapLayerId, type AxisMapLayerId, type CatalogAxis } from "@/lib/mapDisplay/axisLayers";

// CatalogAxis型はaxisLayers.tsと共有する（同じ形の入力を両ファイルの変換関数が
// 受け取るため、別々に定義しない）。

export interface SecondaryAxisSummary {
  axisId: string;
  /** 正式名（サイドバー・研究タブで使う） */
  label: string;
  /** 軸自身の説明文（1〜2文の要約）。ルート設定パネルの重み一覧が出す。
   * 軸を1本足したときにfrontend側へ説明文を書き足さずに済むよう、軸自身のデータを引く。 */
  description: string;
  /** 地図チップの略名（4文字以下、確定命名表どおり） */
  chipLabel: string;
  /** 対応する表示レイヤー。無ければ専用レイヤーを持たない軸(薄字表示) */
  layerId?: AxisMapLayerId;
  /** この軸が参照する材料の一次属性id一覧（生成物`primaryAttributes.ts`のattr_idと
   * 同じ名前空間）。実行時APIのprimary_attribute_idsをそのまま反映する。 */
  primaryAttributeIds: readonly string[];
  /** 地図チップのアイコン（axisIconPalette.tsxのicon_id）。軸自身のデータ
   * （AXIS_DEFINITIONS.icon_id）をそのまま反映する。未設定は汎用フォールバック
   * （AxisRampIcon）を使う——axisIconFor()側の責務。 */
  iconId?: string;
  /** 「表示する項目を選ぶ」設定パネル（MapOverlayControls.tsx:
   * renderVisibilitySettings）で、この軸の行に個別の情報アイコンを出し、押すと表示する
   * 説明文。軸自身のデータ（AXIS_DEFINITIONS.panel_hint）をそのまま反映する。未設定なら
   * 情報アイコン自体を出さない。 */
  panelHint?: string;
  /** 軸自身のデータ（AXIS_DEFINITIONS.dedicated_way_value_layer）をそのまま反映する。
   * display.kindからは導けない——gradientのように「kind='none'（材料がタイル非依存）
   * かつdedicated_way_value_layer=true」の軸がある。 */
  dedicatedWayValueLayer?: boolean;
  /** 折れ点を通す前の生値の単位（GET /api/axis-catalogのraw_value_unit）。単位が定まる
   * 軸だけが持ち、それ以外はnull。 */
  rawValueUnit?: string | null;
  /** 生値へ走行距離を掛けた総量の単位（CatalogAxis.raw_value_total_unit）。総量を出しても
   * 判断が変わらない軸はnull。 */
  rawValueTotalUnit?: string | null;
  /** 生値の単位が定まらない軸の内訳（CatalogAxis.material_breakdown）。材料まで分解した
   * 絶対量の並びで、正規化重みの降順。単位が定まる軸は空配列。 */
  materialBreakdown?: readonly AxisMaterialBreakdown[];
}

/** カタログの`material_breakdown`をフロントの命名（camelCase）へ移す。
 *
 * 軸のビューモデルを組み立てる箇所が複数ある（`secondaryAxesFromCatalogAxes`・
 * `evaluationAxes.ts: preferenceAxisFromCatalog`）ため、この変換だけを共有する
 * ——フィールドを1つ足したときに片方だけ取り残されるのを防ぐ。 */
export function materialBreakdownFromCatalog(entries: CatalogAxis["material_breakdown"]): AxisMaterialBreakdown[] {
  return (entries ?? []).map((entry) => ({
    materialId: entry.material_id,
    label: entry.label,
    dtype: entry.dtype,
    unit: entry.unit,
    share: entry.share,
    // 生成json由来のため値ごとに別のリテラル型になる。対訳表としての形は同じ。
    valueLabels: (entry.value_labels ?? {}) as Record<string, string>,
  }));
}

/** 内訳1件（材料と、それが軸の生値に占める割合）。 */
export interface AxisMaterialBreakdown {
  materialId: string;
  label: string;
  /** `numeric`＝距離加重平均＋単位、`boolean`＝該当区間の延長割合。 */
  dtype: string;
  /** numeric材料の単位。真偽値材料は空文字。 */
  unit: string;
  share: number;
  /** categorical材料の「タグ生値→論理名」対訳（他の型では空）。フロントは対応表を持たない。 */
  valueLabels?: Readonly<Record<string, string>>;
}

// kind==="ramp"の軸の専用レイヤーidはaxisMapLayerId(axis_id)で機械的に求まる（軸が
// 増えてもここへ追記しない）。kind==="none"（例: gradient、材料がタイル非依存）は
// undefined（専用レイヤー無し）のまま。
function layerIdFor(axis: CatalogAxis): AxisMapLayerId | undefined {
  if (axis.display!.kind === "ramp") return axisMapLayerId(axis.axis_id);
  return undefined;
}

/** 二次軸(推定指標)一覧を、カタログの並び順のまま変換する。
 *
 * 軸を地図向けの一覧から外す唯一のスイッチは`show_map_icon`（軸スタジオから設定する、
 * 既定true）。専用の動的気象UIを別に持つwindのように「公開軸だがこの一覧には出したくない」
 * 軸も、コード側の軸id・categoryの名指しではなくこのフラグで外す——軸の属性は
 * 軸スタジオから変えられるため、コード側で特定の値を名指しすると、値が変わった時点で
 * 黙って効かなくなる。 */
export function secondaryAxesFromCatalogAxes(axes: readonly CatalogAxis[]): SecondaryAxisSummary[] {
  return (
    axes
      // display===nullは非公開軸（カタログに載るが表示情報を持たない）。
      .filter((axis) => axis.display !== null && axis.show_map_icon !== false)
      .map((axis) => ({
        axisId: axis.axis_id,
        label: axis.display!.label,
        description: axis.description ?? "",
        chipLabel: axis.chip_label ?? axis.display!.label,
        layerId: layerIdFor(axis),
        primaryAttributeIds: axis.primary_attribute_ids ?? [],
        iconId: axis.icon_id ?? undefined,
        panelHint: axis.panel_hint ?? undefined,
        dedicatedWayValueLayer: axis.dedicated_way_value_layer ?? false,
        rawValueUnit: axis.raw_value_unit ?? null,
        rawValueTotalUnit: axis.raw_value_total_unit ?? null,
        materialBreakdown: materialBreakdownFromCatalog(axis.material_breakdown),
      }))
  );
}
