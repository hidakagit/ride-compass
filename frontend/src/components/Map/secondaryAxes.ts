// 二次軸（推定指標）のカタログ（改善計画T166「地図チップ最上位を次数へ反転」）。
//
// 地図チップの「推定指標（合成）」グループは、確定命名表の6軸（勾配・舗装質・停止密度・
// 車の圧迫感・夜間・事故密度）を常にすべて列挙する。専用の表示レイヤー（MapLayerId）を
// 持つ軸（車の圧迫感=carStress、停止密度・事故密度=axisMapLayerId経由のrampレイヤー）は
// ON/OFFトグル付きの行として、専用レイヤーの無い軸（勾配・舗装質・夜間）は薄字＋代役への
// ポインタだけの行として表示する（MapOverlayControls.tsx参照）。
//
// 正式名はaxis-catalog.json（display.label、backendのregistry_defaults.pyが単一ソース）を
// そのまま使う。このファイルが独自に持つのは、UI固有の対応（略名・対応する表示レイヤーID・
// レイヤー無し軸の代役案内文）だけ（片側import、primaryAttributes.tsと同じ設計）。

import type { MapLayerId } from "./mapLayers";
import { axisMapLayerId } from "./axisLayers";
import axisCatalog from "@/types/generated/axis-catalog.json";

interface CatalogAxis {
  axis_id: string;
  display: { kind: string; label: string } | null;
}

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
}

// 略名（改善計画T166確定命名表）。全軸とも正式名が4文字以下のため実質そのままだが、
// 表記をカタログ（label）に追従させず明示的に固定する（primaryAttributes.tsの
// PRIMARY_ATTRIBUTE_CHIP_LABELSと同じ理由: カタログのlabel変更に略名が無警告で
// 引きずられない）。
const SECONDARY_AXIS_CHIP_LABELS: Record<string, string> = {
  gradient: "勾配",
  surface_q: "舗装",
  stop_density: "停止密度",
  car_stress: "圧迫感",
  night: "夜間",
  accident: "事故密度",
};

// 専用レイヤーを持たない3軸(display.kind==="none")の代役案内。
const SECONDARY_AXIS_PROXY_HINTS: Record<string, string> = {
  gradient: "標高レイヤーで確認できます",
  surface_q: "路面の種類レイヤーで確認できます",
  night: "専用レイヤーは今後追加予定です",
};

// display.kind==="bespoke"のcar_stressは専用MapLayerIdを個別に持つ。kind==="ramp"の
// stop_density/accidentはaxisMapLayerId経由(axisLayers.ts: RAMP_AXES/axisMapLayerId参照)。
// kind==="none"の3軸(gradient/surface_q/night)はレイヤーを持たない。
const SECONDARY_AXIS_LAYER_IDS: Partial<Record<string, MapLayerId>> = {
  car_stress: "carStress",
  stop_density: axisMapLayerId("stop_density"),
  accident: axisMapLayerId("accident"),
};

/** 二次軸(推定指標)6件を、axis-catalog.jsonの並び順(確定命名表と同じ順)で返す。 */
export const SECONDARY_AXES: readonly SecondaryAxisSummary[] = (axisCatalog.axes as CatalogAxis[])
  .filter((axis) => axis.display !== null)
  .map((axis) => ({
    axisId: axis.axis_id,
    label: axis.display!.label,
    chipLabel: SECONDARY_AXIS_CHIP_LABELS[axis.axis_id] ?? axis.display!.label,
    layerId: SECONDARY_AXIS_LAYER_IDS[axis.axis_id],
    proxyHint: SECONDARY_AXIS_PROXY_HINTS[axis.axis_id],
  }));
