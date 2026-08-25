// 二次軸（推定指標）のカタログ（改善計画T166「地図チップ最上位を次数へ反転」）。
//
// 地図チップの「推定指標（合成）」グループは、axis-catalog.json（display!==null）の
// 全軸を列挙する（確定命名表T166時点は6軸、改善計画T278でsurface_q・night、T292で
// car_stressがそれぞれkind="ramp"へ変わり専用レイヤーを持つようになった。将来軸スタジオが
// 作る新規軸も材料がタイル焼き込み済みならここへ自動で追加される）。専用の表示レイヤー
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
  /** 地図チップの略名（4文字以下、確定命名表どおり） */
  chipLabel: string;
  /** 対応する表示レイヤー。無ければ専用レイヤーを持たない軸(薄字表示) */
  layerId?: MapLayerId;
  /** layerId未定義の軸向け、代役レイヤーへの案内文 */
  proxyHint?: string;
  /** 改善計画T308: この軸が参照する材料の一次属性id一覧（primaryAttributes.ts:
   * PRIMARY_ATTRIBUTE_LAYER_IDS/PRIMARY_ATTRIBUTE_CHIP_LABELSのキーと同じ名前空間）。
   * 実行時APIのprimary_attribute_idsをそのまま反映する。ビルド時静的フォールバックは
   * この情報を持たないため空配列（取得完了までの一時的な機能低下、致命的ではない）。 */
  primaryAttributeIds: readonly string[];
  /** 改善計画T310: 地図チップのアイコン（axisIconPalette.tsxのicon_id）。軸自身のデータ
   * （AXIS_DEFINITIONS.icon_id）をそのまま反映する。未設定は汎用フォールバック
   * （AxisRampIcon）を使う——axisIconFor()側の責務。 */
  iconId?: string;
}

// 略名・代役案内文（改善計画T166確定命名表）は、以前は軸id→値の手書き辞書
// （SECONDARY_AXIS_CHIP_LABELS/SECONDARY_AXIS_PROXY_HINTS）だったが、改善計画T310で
// 軸自身のデータ（AXIS_DEFINITIONS.chip_label/proxy_hint、軸スタジオから登録可能）へ
// 移設し、既存軸限定の特別扱いを解消した（下記secondaryAxesFromCatalogAxes参照）。
// 専用レイヤーを持たない軸(display.kind==="none")のproxy_hintは、タイル自体は他の軸と
// 見た目を統一するため個別の注記テキストを常設できない（4文字以下のチップラベル・
// 小さいタイルという制約、改善計画T166）という理由から、「押せない行がなぜあるのか」を
// 展開せずに伝える最小限の手当て（（地図表示なし）を先頭に付けタイトル属性で見える
// ツールチップ、改善計画T202）として使う。

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

/** 二次軸(推定指標)一覧を、カタログの並び順のまま変換する。 */
export function secondaryAxesFromCatalogAxes(axes: readonly CatalogAxis[]): SecondaryAxisSummary[] {
  return axes
    .filter((axis) => axis.display !== null)
    .map((axis) => ({
      axisId: axis.axis_id,
      label: axis.display!.label,
      chipLabel: axis.chip_label ?? axis.display!.label,
      layerId: layerIdFor(axis),
      proxyHint: axis.proxy_hint ?? undefined,
      primaryAttributeIds: axis.primary_attribute_ids ?? [],
      iconId: axis.icon_id ?? undefined,
    }));
}

// ビルド時静的json由来のフォールバック専用値（モジュール先頭の注記参照）。
/** 二次軸(推定指標)を、axis-catalog.jsonの並び順(確定命名表と同じ順)で返す。 */
export const SECONDARY_AXES: readonly SecondaryAxisSummary[] = secondaryAxesFromCatalogAxes(
  axisCatalog.axes as CatalogAxis[]
);
