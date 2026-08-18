// 区間インスペクタ（改善計画T146）。クリックした区間の一次属性→二次軸スコア→
// 三次合成コスト（取得可能な軸だけの参考値）を表示するポップアップ拡張。
// recipeBreakdownPopup.ts（車ストレス・安全度個別の内訳、改善計画T90・T123）と同じ
// 「ボタン押下でオンデマンド取得しDOMへ直接差し込む」方式（MapLibre PopupはReactツリー外
// のためイベントハンドラをaddTo後にquerySelectorで配線する）。
//
// レジストリ駆動: 軸ラベルはaxisLayers.ts: AXIS_LABELS（backendのaxis-catalog.json由来）を
// 参照するため、新しい軸が増えてもこのファイルの変更は不要（表示される軸自体は
// AxisInspectorResult.axesがサーバー側で決める）。
import type { AxisInspectorResult } from "@/types/traffic";
import type {
  MotorVehicleDensityRecipeOverride,
  RoadSuitabilityRecipeOverride,
  CarStressRecipeOverride,
} from "@/types/route";
import { fetchAxisInspector } from "@/services/regionApi";
import { AXIS_LABELS } from "./axisLayers";

export const AXIS_INSPECTOR_BUTTON_ATTR = "data-axis-inspector-button";
export const AXIS_INSPECTOR_RESULT_ATTR = "data-axis-inspector-result";

const UNAVAILABLE_HTML = `<div style="font-size:var(--font-size-sm); margin-top:var(--space-1);">内訳を取得できませんでした。</div>`;

function formatDifficulty(value: number | null): string {
  return value == null ? "算出不可" : `${value.toFixed(1)}/100`;
}

function buildAxisInspectorHtml(result: AxisInspectorResult): string {
  const primaryRows = Object.entries(result.tags)
    .map(([key, value]) => `${key}=${value}`)
    .join(", ");
  const axisRows = result.axes
    .map((axis) => {
      const label = AXIS_LABELS[axis.axis_id] ?? axis.axis_id;
      const suffix = axis.available ? "" : "（この区間では算出不可）";
      return `${label}: ${formatDifficulty(axis.difficulty)}${suffix}`;
    })
    .join("<br/>");

  const compositeRow =
    result.composite_difficulty != null
      ? `<strong>合成コスト（参考値）: ${result.composite_difficulty.toFixed(1)}/100</strong>` +
        (result.covered_weight_fraction != null && result.covered_weight_fraction < 0.999
          ? `<br/><span style="color:var(--color-text-muted);">重みの約${Math.round(result.covered_weight_fraction * 100)}%に相当する軸のみで算出（勾配・風はこの区間単体では算出できないため未算入。実際のルート探索コストとは一致しません）</span>`
          : "")
      : `<span style="color:var(--color-text-muted);">合成コストを算出できる軸がありません。</span>`;

  return `<div style="font-size:var(--font-size-sm); line-height:1.4; margin-top:var(--space-1); border-top:1px solid var(--color-border); padding-top:var(--space-1);">
    <strong>一次属性</strong><br/>
    highway: ${result.highway ?? "不明"}${result.is_designated ? "（指定路線）" : ""}<br/>
    ${primaryRows || "（登録タグなし）"}
    <br/><br/><strong>二次軸スコア（0=易しい〜100=大変）</strong><br/>
    ${axisRows}
    <br/><br/>${compositeRow}
  </div>`;
}

export function buildAxisInspectorAffordanceHtml(): string {
  return `<div style="margin-top:var(--space-1);">
    <button type="button" ${AXIS_INSPECTOR_BUTTON_ATTR} style="font:inherit; font-size:var(--font-size-sm); padding:2px 8px; cursor:pointer;">一次属性・全軸の内訳を見る</button>
    <div ${AXIS_INSPECTOR_RESULT_ATTR}></div>
  </div>`;
}

export function attachAxisInspectorHandler(
  popupElement: HTMLElement,
  osmWayId: number,
  carStressRecipe: CarStressRecipeOverride | undefined,
  roadSuitabilityRecipe: RoadSuitabilityRecipeOverride | undefined,
  motorVehicleDensityRecipe: MotorVehicleDensityRecipeOverride | undefined,
) {
  const button = popupElement.querySelector<HTMLButtonElement>(`[${AXIS_INSPECTOR_BUTTON_ATTR}]`);
  const resultEl = popupElement.querySelector<HTMLElement>(`[${AXIS_INSPECTOR_RESULT_ATTR}]`);
  if (!button || !resultEl) return;
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "取得中…";
    try {
      const result = await fetchAxisInspector(osmWayId, carStressRecipe, roadSuitabilityRecipe, motorVehicleDensityRecipe);
      resultEl.innerHTML = result ? buildAxisInspectorHtml(result) : UNAVAILABLE_HTML;
    } catch {
      resultEl.innerHTML = UNAVAILABLE_HTML;
    } finally {
      button.remove();
    }
  });
}
