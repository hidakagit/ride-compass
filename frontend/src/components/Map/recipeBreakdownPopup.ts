// 交通ストレス・安全度の区間別判定内訳ポップアップ（改善計画T90・安全度レシピ）の
// HTML組み立て＋ボタン配線。MapView.tsxに双子（ほぼ同一の構造で約158行）として存在して
// いたものを、軸固有部分（ボタン/結果表示のdata属性・段階数・補正フィールド→ラベル対訳・
// fetch関数）だけを設定オブジェクトとして渡す1実装へ畳んだ（改善計画T123。
// backend/app/domain/recipe.py・backend/app/services/region_service.py: _get_breakdownと
// 同じ「軸固有部分だけ引数化する」方針のTS側ミラー）。
//
// 補正の内訳行は`adjustmentLabels`のキー（Breakdownのフィールド名）を順番に読んで組み立てる
// （backend/scripts/measure_axis_stats.pyのadjustment_field_namesと同じ「フィールド名を
// 動的に拾う」考え方。新しい補正フィールドが増えても本モジュール自体の変更は不要で、
// 各軸のconfigへラベルを1行足すだけで済む）。
import type { SafetyBreakdown, TrafficStressBreakdown } from "@/types/traffic";
import type {
  MotorVehicleDensityRecipeOverride,
  RoadSuitabilityRecipeOverride,
  SafetyRecipeOverride,
  TrafficStressRecipeOverride,
} from "@/types/route";
import { fetchSafetyBreakdown, fetchTrafficStressBreakdown } from "@/services/regionApi";

// ポップアップ内のボタン・結果表示先を識別するdata属性（HTML文字列としてMapLibreの
// Popup#setHTMLへ渡すため、Reactのイベントハンドラは使えず、addTo後にDOMを直接
// querySelectorして配線する）。buildRoadSurfacePopupHtml（MapView.tsx）がボタンHTML自体を
// 組み立てる際にも参照するためexportする。
export const TRAFFIC_STRESS_BREAKDOWN_BUTTON_ATTR = "data-traffic-stress-breakdown-button";
export const TRAFFIC_STRESS_BREAKDOWN_RESULT_ATTR = "data-traffic-stress-breakdown-result";
export const SAFETY_BREAKDOWN_BUTTON_ATTR = "data-safety-breakdown-button";
export const SAFETY_BREAKDOWN_RESULT_ATTR = "data-safety-breakdown-result";

interface RecipeBreakdownLike {
  base: number | null;
  level: number | null;
  motor_vehicle_no_override: boolean;
}

interface RecipeBreakdownAxisConfig<TBreakdown extends RecipeBreakdownLike, TRecipe> {
  buttonAttr: string;
  resultAttr: string;
  /** 「この道路種別は◯◯の判定基準に登録されていません」の◯◯部分。 */
  registeredLabel: string;
  scaleIntro: string;
  minLevel: number;
  maxLevel: number;
  /** 補正フィールド名（Breakdownのキー）→表示ラベル。オブジェクトの記述順がそのまま
   * 内訳の表示順になる。 */
  adjustmentLabels: Record<string, string>;
  fetchBreakdown: (
    osmWayId: number,
    recipe: TRecipe | undefined,
    roadSuitabilityRecipe: RoadSuitabilityRecipeOverride | undefined,
    motorVehicleDensityRecipe: MotorVehicleDensityRecipeOverride | undefined,
  ) => Promise<TBreakdown | null>;
}

function formatSignedTerm(value: number): string {
  return value >= 0 ? `+${value}` : `${value}`;
}

const UNAVAILABLE_HTML = `<div style="font-size:var(--font-size-sm); margin-top:var(--space-1);">内訳を取得できませんでした。</div>`;

function buildBreakdownHtml<TBreakdown extends RecipeBreakdownLike>(
  breakdown: TBreakdown,
  config: Pick<RecipeBreakdownAxisConfig<TBreakdown, unknown>, "registeredLabel" | "scaleIntro" | "minLevel" | "maxLevel" | "adjustmentLabels">,
): string {
  if (breakdown.level == null) {
    return `<div style="font-size:var(--font-size-sm); margin-top:var(--space-1);">この道路種別は${config.registeredLabel}の判定基準に登録されていません。</div>`;
  }
  const base = breakdown.base ?? 0;
  const rows = [`基準値[道路種別]: ${base}`];
  if (breakdown.motor_vehicle_no_override) {
    rows.push("車両通行不可[自転車専用]のため、上記に関わらず1に固定");
  } else {
    const fields = breakdown as unknown as Record<string, number>;
    const adjustments: Array<{ label: string; value: number }> = [];
    for (const [field, label] of Object.entries(config.adjustmentLabels)) {
      if (fields[field] !== 0) adjustments.push({ label, value: fields[field] });
    }
    for (const adjustment of adjustments) {
      rows.push(`${adjustment.label}: ${formatSignedTerm(adjustment.value)}`);
    }
    if (adjustments.length > 0) {
      const rawTotal = base + adjustments.reduce((sum, adjustment) => sum + adjustment.value, 0);
      const formula = [`${base}`, ...adjustments.map((adjustment) => formatSignedTerm(adjustment.value))].join(" ");
      if (rawTotal !== breakdown.level) {
        const boundLabel = rawTotal > config.maxLevel ? `上限の${config.maxLevel}` : `下限の${config.minLevel}`;
        rows.push(`合計 ${formula} = ${rawTotal} → ${boundLabel}に丸め`);
      } else {
        rows.push(`合計 ${formula} = ${rawTotal}`);
      }
    }
  }
  rows.push(`<strong>最終値: ${breakdown.level}/${config.maxLevel}</strong>`);
  return `<div style="font-size:var(--font-size-sm); line-height:1.4; margin-top:var(--space-1); border-top:1px solid var(--color-border); padding-top:var(--space-1);">${config.scaleIntro}<br/><br/>${rows.join("<br/>")}</div>`;
}

// popupElement内のボタンをオンデマンド取得（道路クリックのたびに毎回問い合わせると、
// 色分けを見ながら地図を連続でクリックする通常操作でAPIコール・レート制限を無駄に
// 消費するため）で配線する。osmWayIdはクリックされたフィーチャーのプロパティ由来
// （緯度経度の空間マッチではなく完全一致で引き直す理由はfetchTrafficStressBreakdownの
// コメント参照）。
function attachBreakdownHandler<TBreakdown extends RecipeBreakdownLike, TRecipe>(
  popupElement: HTMLElement,
  osmWayId: number,
  recipe: TRecipe | undefined,
  roadSuitabilityRecipe: RoadSuitabilityRecipeOverride | undefined,
  motorVehicleDensityRecipe: MotorVehicleDensityRecipeOverride | undefined,
  config: RecipeBreakdownAxisConfig<TBreakdown, TRecipe>,
) {
  const button = popupElement.querySelector<HTMLButtonElement>(`[${config.buttonAttr}]`);
  const resultEl = popupElement.querySelector<HTMLElement>(`[${config.resultAttr}]`);
  if (!button || !resultEl) return;
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "取得中…";
    try {
      const breakdown = await config.fetchBreakdown(osmWayId, recipe, roadSuitabilityRecipe, motorVehicleDensityRecipe);
      resultEl.innerHTML = breakdown ? buildBreakdownHtml(breakdown, config) : UNAVAILABLE_HTML;
    } catch {
      resultEl.innerHTML = UNAVAILABLE_HTML;
    } finally {
      button.remove();
    }
  });
}

// 「基準値4＋指定路線+1なのに最終値が5でなく4なのはなぜか」という実機フィードバック
// （改善計画T90への追加対応）を受け、各補正の合計がクランプ範囲を超えたら丸めることを
// 明示する。mapLayers.tsのpanelHint「5段階[1=快適〜5=圧迫大]」と同じ語彙で揃える
// （複雑度平衡の「UI語彙のカタログ集約」原則）。
const TRAFFIC_STRESS_BREAKDOWN_CONFIG: RecipeBreakdownAxisConfig<TrafficStressBreakdown, TrafficStressRecipeOverride> = {
  buttonAttr: TRAFFIC_STRESS_BREAKDOWN_BUTTON_ATTR,
  resultAttr: TRAFFIC_STRESS_BREAKDOWN_RESULT_ATTR,
  registeredLabel: "車の圧迫感",
  scaleIntro: "車の圧迫感は5段階[1=快適〜5=圧迫大]の目安です。",
  minLevel: 1,
  maxLevel: 5,
  adjustmentLabels: {
    cycleway_adjustment: "自転車インフラ",
    maxspeed_adjustment: "制限速度",
    lanes_adjustment: "車線数",
    designation_adjustment: "指定路線[緊急輸送道路等]",
  },
  fetchBreakdown: fetchTrafficStressBreakdown,
};

// 安全度は4段階固定・丸めありという同じ仕様（domain/safety.py: safety_breakdown、
// TRAFFIC_STRESS_BREAKDOWN_CONFIGと同じ理由でここも明示する）。
const SAFETY_BREAKDOWN_CONFIG: RecipeBreakdownAxisConfig<SafetyBreakdown, SafetyRecipeOverride> = {
  buttonAttr: SAFETY_BREAKDOWN_BUTTON_ATTR,
  resultAttr: SAFETY_BREAKDOWN_RESULT_ATTR,
  registeredLabel: "安全度",
  scaleIntro: "安全度は4段階[1=安全〜4=危険]の目安です。",
  minLevel: 1,
  maxLevel: 4,
  adjustmentLabels: {
    cycleway_adjustment: "自転車インフラ",
    maxspeed_adjustment: "制限速度",
    lanes_adjustment: "車線数",
    lit_adjustment: "街灯",
    tunnel_adjustment: "トンネル",
    designation_adjustment: "指定路線[緊急輸送道路等]",
  },
  fetchBreakdown: fetchSafetyBreakdown,
};

export function attachTrafficStressBreakdownHandler(
  popupElement: HTMLElement,
  osmWayId: number,
  recipe: TrafficStressRecipeOverride | undefined,
  roadSuitabilityRecipe: RoadSuitabilityRecipeOverride | undefined,
  motorVehicleDensityRecipe: MotorVehicleDensityRecipeOverride | undefined,
) {
  attachBreakdownHandler(
    popupElement,
    osmWayId,
    recipe,
    roadSuitabilityRecipe,
    motorVehicleDensityRecipe,
    TRAFFIC_STRESS_BREAKDOWN_CONFIG,
  );
}

export function attachSafetyBreakdownHandler(
  popupElement: HTMLElement,
  osmWayId: number,
  recipe: SafetyRecipeOverride | undefined,
  roadSuitabilityRecipe: RoadSuitabilityRecipeOverride | undefined,
  motorVehicleDensityRecipe: MotorVehicleDensityRecipeOverride | undefined,
) {
  attachBreakdownHandler(
    popupElement,
    osmWayId,
    recipe,
    roadSuitabilityRecipe,
    motorVehicleDensityRecipe,
    SAFETY_BREAKDOWN_CONFIG,
  );
}
