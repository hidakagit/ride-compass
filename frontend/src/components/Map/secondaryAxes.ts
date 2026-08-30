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
  /** 改善計画T308: この軸が参照する材料の一次属性id一覧（primaryAttributes.ts:
   * PRIMARY_ATTRIBUTE_LAYER_IDS/PRIMARY_ATTRIBUTE_CHIP_LABELSのキーと同じ名前空間）。
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
   * 現状はgradient（Map/gradientAxisLayer.ts・gradientGridFill.tsのboundaries引数）が
   * 唯一の消費者。未設定はkind="none"軸の各実装が持つビルド時既定値（例:
   * GRADIENT_BOUNDARIES）へのフォールバックに委ねる。 */
  displayThresholdsOverride?: readonly number[] | null;
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
 * コードレビュー指摘の修正: 改善計画T308でaxis_display_for()が全公開軸に対して常に
 * 非null（kind="none"含む）を返すようになったため、`display !== null`だけのフィルタでは
 * windのような専用の動的気象UIを別に持つ軸（推定指標チップグループには元々出す意図が無い）
 * を除外できなくなっていた（以前は静的axis-catalog.jsonの生成元registry.pyにwindが
 * 登録されておらず、display自体がundefinedだったため結果的に除外されていた）。
 * `category !== "動的"`は当時この目的で追加した条件。**2026-08-31訂正（改善計画T447）**:
 * 「windの`category`は"推定"へ変わっておりこの条件は死んだフィルタ、実際の除外は
 * `show_map_icon`のみ」という2026-08-30時点の旧コメント（下記の直前の版）は誤りだった。
 * `backend/fixtures/axis_definitions_snapshot.json`を実際に確認すると、windの
 * `category`は`"動的"`のまま（`show_map_icon`は`true`）——つまり**逆**で、windを
 * 推定指標チップグループから除外しているのは`category !== "動的"`の方であり、
 * `show_map_icon !== false`はwindを除外する側には寄与していない。`category !== "動的"`は
 * 生きた現役のフィルタのため削除しないこと（このコメントの正確性に依存せず済むよう、
 * 除外挙動そのものはsecondaryAxes.test.tsの回帰テストで直接検証している）。 */
export function secondaryAxesFromCatalogAxes(axes: readonly CatalogAxis[]): SecondaryAxisSummary[] {
  return axes
    // 改善計画T318: show_map_icon===falseの軸は地図上チップ・地図の見え方パネルの
    // 両方から丸ごと除外する（専用レイヤーの有無=display.kindに関わらず一律に効く、
    // 軸スタジオ側のON/OFF1つで両画面が揃って更新される）。windは現状category条件
    // （上記コメント参照）で除外されており、この条件は寄与していない。
    .filter((axis) => axis.display !== null && axis.category !== "動的" && axis.show_map_icon !== false)
    .map((axis) => ({
      axisId: axis.axis_id,
      label: axis.display!.label,
      chipLabel: axis.chip_label ?? axis.display!.label,
      layerId: layerIdFor(axis),
      primaryAttributeIds: axis.primary_attribute_ids ?? [],
      iconId: axis.icon_id ?? undefined,
      panelHint: axis.panel_hint ?? undefined,
      displayThresholdsOverride: axis.display_thresholds_override ?? undefined,
    }));
}

// ビルド時静的json由来のフォールバック専用値（モジュール先頭の注記参照）。
/** 二次軸(推定指標)を、axis-catalog.jsonの並び順(確定命名表と同じ順)で返す。 */
export const SECONDARY_AXES: readonly SecondaryAxisSummary[] = secondaryAxesFromCatalogAxes(
  axisCatalog.axes as CatalogAxis[]
);
