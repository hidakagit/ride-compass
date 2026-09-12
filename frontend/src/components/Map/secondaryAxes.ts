// 二次軸（推定指標）のカタログ（改善計画T166「地図チップ最上位を次数へ反転」）。
//
// 地図チップの「推定指標（合成）」グループは、axis-catalog.json（display!==null）の
// 全軸を列挙する（軸スタジオが作る新規軸も、材料がタイル焼き込み済みならここへ
// 自動で追加される）。専用の表示レイヤー
// （MapLayerId）を持つ軸（kind="ramp"の軸=axisMapLayerId経由）はON/OFFトグル付きの行として、
// 専用レイヤーの無い軸（勾配のみ、材料がタイル非依存）は薄字＋代役へのポインタだけの
// 行として表示する（MapOverlayControls.tsx参照）。
//
// 正式名はaxis-catalog.json（display.label、backendのregistry_defaults.pyが単一ソース）を
// そのまま使う。このファイルが独自に持つのは、UI固有の対応（略名・対応する表示レイヤーID・
// レイヤー無し軸の代役案内文）だけ（片側import、primaryAttributes.tsと同じ設計）。
// 改善計画T292: 車の圧迫感（car_stress）もkind="ramp"へ移行し、他のkind="ramp"軸と
// 同じくaxisMapLayerId経由で専用レイヤーを持つようになった。

import type { MapLayerId } from "./mapLayers";
import type { MapValueKind } from "./valueScale";
import { axisMapLayerId, type CatalogAxis } from "./axisLayers";
import axisCatalog from "@/types/generated/axis-catalog.json";

// 改善計画T308: 実行時API（GET /api/axis-catalog）から取得したエントリからも同じ形へ
// 変換できるよう、静的jsonの走査ロジックを共通関数として切り出す（axisLayers.tsの
// rampAxesFromCatalogAxes等と同じ理由、片側import）。hooks/useAxisCatalog.tsが
// フェッチ結果から呼ぶ。CatalogAxis型自体はaxisLayers.tsと共有する（同じ形の入力を
// 両ファイルの変換関数が受け取るため、別々に定義しない）。

export interface SecondaryAxisSummary {
  axisId: string;
  /** 正式名（サイドバー・研究タブで使う）。axis-catalog.json由来 */
  label: string;
  /** 軸自身の説明文（1〜2文の要約）。ルート設定パネルの重み一覧が出す。
   * 軸を1本足したときにfrontend側へ説明文を書き足さずに済むよう、軸自身のデータを引く。 */
  description: string;
  /** 地図チップの略名（4文字以下、確定命名表どおり） */
  chipLabel: string;
  /** 対応する表示レイヤー。無ければ専用レイヤーを持たない軸(薄字表示) */
  layerId?: MapLayerId;
  /** 改善計画T308: この軸が参照する材料の一次属性id一覧（primaryAttributes.ts:
   * PRIMARY_ATTRIBUTE_LAYER_IDSのキーと同じ名前空間）。
   * 実行時APIのprimary_attribute_idsをそのまま反映する。ビルド時静的フォールバックは
   * この情報を持たないため空配列（取得完了までの一時的な機能低下、致命的ではない）。 */
  primaryAttributeIds: readonly string[];
  /** 改善計画T310: 地図チップのアイコン（axisIconPalette.tsxのicon_id）。軸自身のデータ
   * （AXIS_DEFINITIONS.icon_id）をそのまま反映する。未設定は汎用フォールバック
   * （AxisRampIcon）を使う——axisIconFor()側の責務。 */
  iconId?: string;
  /** 改善計画T334: 「表示する項目を選ぶ」設定パネル（MapOverlayControls.tsx:
   * renderVisibilitySettings）で、この軸の行に個別の情報アイコンを出し、押すと表示する
   * 説明文。軸自身のデータ（AXIS_DEFINITIONS.panel_hint）をそのまま反映する。未設定なら
   * 情報アイコン自体を出さない。 */
  panelHint?: string;
  /** 改善計画T443: プレルート表示（評価軸ライン・環境グループ塗り）の色分けしきい値。
   * 軸自身のデータ（AXIS_DEFINITIONS.display_thresholds_override）をそのまま反映する。
   * 現状はgradient（Map/dedicatedWayValueLayer.ts・gradientGridFill.tsの表示宣言）が
   * 唯一の消費者。未設定はkind="none"軸の各実装が持つビルド時既定値（例:
   * valueScale.tsのSIGNED_MATERIAL_BOUNDARIES）へのフォールバックに委ねる。 */
  displayThresholdsOverride?: readonly number[] | null;
  /** 改善計画T513: displayThresholdsOverrideと対になる、段階ごとの体感ラベルの軽量な
   * 上書き（AXIS_DEFINITIONS.display_band_labels_overrideをそのまま反映）。 */
  displayBandLabelsOverride?: readonly string[] | null;
  /** 改善計画T473: 軸自身のデータ（AXIS_DEFINITIONS.dedicated_way_value_layer）をそのまま
   * 反映する。以前はこのフィールド自体を持たず、evaluationAxes.ts側がSECONDARY_AXES由来の
   * 軸を一律falseとして扱っていたが、gradientのように「kind='none'（材料がタイル非依存）
   * かつdedicated_way_value_layer=true」という組み合わせが実在するため誤りだった
   * （evaluationAxes.ts参照）。 */
  dedicatedWayValueLayer?: boolean;
  /** 地図がこの軸について塗る値の種類・単位（CatalogAxis.map_value_kind/map_value_unit）。 */
  mapValueKind?: MapValueKind;
  mapValueUnit?: string;
  /** 折れ点を通す前の生値の単位（GET /api/axis-catalogのraw_value_unit）。単位が定まる
   * 軸だけが持ち、それ以外はnull。 */
  rawValueUnit?: string | null;
  /** 生値の単位が定まらない軸の内訳（CatalogAxis.material_breakdown）。材料まで分解した
   * 絶対量の並びで、正規化重みの降順。単位が定まる軸は空配列。 */
  materialBreakdown?: readonly AxisMaterialBreakdown[];
}

/** カタログの`material_breakdown`をフロントの命名（camelCase）へ移す。
 *
 * 軸のビューモデルを組み立てる箇所が複数ある（`secondaryAxesFromCatalogAxes`・
 * `evaluationAxes.ts: preferenceAxisFromCatalog`）ため、この変換だけを共有する
 * ——フィールドを1つ足したときに片方だけ取り残されるのを防ぐ。 */
export function materialBreakdownFromCatalog(
  entries: CatalogAxis["material_breakdown"],
): AxisMaterialBreakdown[] {
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

// 略名（改善計画T166確定命名表）は、以前は軸id→値の手書き辞書
// （SECONDARY_AXIS_CHIP_LABELS）だったが、改善計画T310で軸自身のデータ
// （AXIS_DEFINITIONS.chip_label、軸スタジオから登録可能）へ移設し、既存軸限定の
// 特別扱いを解消した（下記secondaryAxesFromCatalogAxes参照）。
// 改善計画T318（ユーザー判断: 「軸スタジオで、地図マップ上にアイコン表示するかどうか
// ON/OFFできるようにして」）: 以前は専用レイヤーを持たない軸(display.kind==="none")を
// 常に無効化されたチップとして表示し、代役案内文（旧proxy_hint）でその理由を説明する
// 仕組みだったが、show_map_icon（AXIS_DEFINITIONS.show_map_icon、既定true）で軸自身が
// 「そもそも地図上に表示するかどうか」を選べるようになったため、その案内文は不要になり
// 撤去した。

// kind==="ramp"の軸はaxisMapLayerId(axis_id)で機械的に求まる（改善計画T278、以前は
// stop_density/accidentの2件をここへ手書き列挙していたが、ramp軸が増えるたびに追記
// する手間を無くした）。改善計画T292: car_stressもkind="bespoke"（専用MapLayerIdを
// 手書きで持つ扱い）からkind="ramp"へ移行したため、専用の対応表（旧
// SECONDARY_AXIS_BESPOKE_LAYER_IDS）は不要になった。kind==="none"（例: gradient、
// 材料がタイル非依存）はundefined（専用レイヤー無し）のまま。
function layerIdFor(axis: CatalogAxis): MapLayerId | undefined {
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
  return axes
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
      displayThresholdsOverride: axis.display_thresholds_override ?? undefined,
      displayBandLabelsOverride: axis.display_band_labels_override ?? undefined,
      dedicatedWayValueLayer: axis.dedicated_way_value_layer ?? false,
      mapValueKind: axis.map_value_kind,
      mapValueUnit: axis.map_value_unit,
      rawValueUnit: axis.raw_value_unit ?? null,
      materialBreakdown: materialBreakdownFromCatalog(axis.material_breakdown),
    }));
}

// ビルド時静的json由来のフォールバック専用値（モジュール先頭の注記参照）。
/** 二次軸(推定指標)を、axis-catalog.jsonの並び順(確定命名表と同じ順)で返す。 */
export const SECONDARY_AXES: readonly SecondaryAxisSummary[] = secondaryAxesFromCatalogAxes(
  axisCatalog.axes as CatalogAxis[]
);
