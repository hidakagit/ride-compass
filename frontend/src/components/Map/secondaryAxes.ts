// 二次軸（推定指標）のカタログ（改善計画T166「地図チップ最上位を次数へ反転」）。
//
// 地図チップの「推定指標（合成）」グループは、axis-catalog.json（display!==null）の
// 全軸を列挙する（確定命名表T166時点は6軸、改善計画T278でsurface_q・nightがkind="ramp"
// へ変わり専用レイヤーを持つようになった。将来軸スタジオが作る新規軸も材料がタイル
// 焼き込み済みならここへ自動で追加される）。専用の表示レイヤー（MapLayerId）を持つ軸
// （車の圧迫感=carStress[bespoke]、kind="ramp"の軸=axisMapLayerId経由）はON/OFF
// トグル付きの行として、専用レイヤーの無い軸（勾配のみ、材料がタイル非依存）は薄字＋
// 代役へのポインタだけの行として表示する（MapOverlayControls.tsx参照）。
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

// 専用レイヤーを持たない軸(display.kind==="none")の代役案内。タイル自体は他の軸と
// 見た目を統一するため個別の注記テキストを常設できない（4文字以下のチップラベル・
// 小さいタイルという制約、改善計画T166）。「押せない行がなぜあるのか」を展開せずに
// 伝える最小限の手当てとして、（地図表示なし）を先頭に付けタイトル属性（hover/長押しで
// 見えるツールチップ）だけでも自己説明的にする（改善計画T202、統合レビュー2026-08-22
// 指摘。恒常的な追加ラベル表示はタイルレイアウトへの影響を実機確認してから判断する
// ため今回は見送り、ユーザー判断のDEFERとする）。
// 改善計画T278でsurface_q・nightはkind="none"/"bespoke"からkind="ramp"（自動導出表示）へ
// 変わり専用レイヤーを持つようになったため、この一覧から除外した（gradientのみ残る。
// 材料gradient_percentがタイル非依存[標高はGSI APIから都度取得]のため引き続きramp化不可）。
const SECONDARY_AXIS_PROXY_HINTS: Record<string, string> = {
  gradient: "（地図表示なし）標高レイヤーで確認できます",
};

// display.kind==="bespoke"の軸（現状car_stressのみ）は専用MapLayerIdを手書きで持つ
// （フロントの手書きexpressionが必要なため自動導出できない）。kind==="ramp"の軸は
// axisMapLayerId(axis_id)で機械的に求まる（改善計画T278、以前はstop_density/accidentの
// 2件をこの辞書に手書き列挙していたが、ramp軸が増えるたびに追記する手間を無くした）。
const SECONDARY_AXIS_BESPOKE_LAYER_IDS: Partial<Record<string, MapLayerId>> = {
  car_stress: "carStress",
};

function layerIdFor(axis: CatalogAxis): MapLayerId | undefined {
  if (axis.display!.kind === "ramp") return axisMapLayerId(axis.axis_id);
  return SECONDARY_AXIS_BESPOKE_LAYER_IDS[axis.axis_id];
}

/** 二次軸(推定指標)を、axis-catalog.jsonの並び順(確定命名表と同じ順)で返す。 */
export const SECONDARY_AXES: readonly SecondaryAxisSummary[] = (axisCatalog.axes as CatalogAxis[])
  .filter((axis) => axis.display !== null)
  .map((axis) => ({
    axisId: axis.axis_id,
    label: axis.display!.label,
    chipLabel: SECONDARY_AXIS_CHIP_LABELS[axis.axis_id] ?? axis.display!.label,
    layerId: layerIdFor(axis),
    proxyHint: SECONDARY_AXIS_PROXY_HINTS[axis.axis_id],
  }));
