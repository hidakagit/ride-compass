// 区間インスペクタ（改善計画T146）。クリックした区間の一次属性→二次軸スコア→
// 三次合成コスト（取得可能な軸だけの参考値）を表示するポップアップ拡張。
// recipeBreakdownPopup.ts（車ストレス・安全度個別の内訳、改善計画T90・T123）と同じ
// 「ボタン押下でオンデマンド取得しDOMへ直接差し込む」方式（MapLibre PopupはReactツリー外
// のためイベントハンドラをaddTo後にquerySelectorで配線する）。
//
// レジストリ駆動: 軸ラベルは呼び出し側（MapView.tsx）がuseAxisCatalog経由で取得した
// 実行時のaxisLabels（axis_id→表示名の辞書）を引数で受け取る。改善計画T320: 以前は
// axisLayers.ts: AXIS_LABELS（ビルド時静的axis-catalog.json由来）を直接importしており、
// 軸スタジオで新規公開したGUI作成軸のラベルが表示されず生のaxis_idがそのまま出ていた
// （動的なaxisLabelsが既に用意されていたのに消費者が無かった配線漏れ）。
import type { AxisInspectorResult } from "@/types/traffic";
import { fetchAxisInspector } from "@/services/regionApi";
import { PRIMARY_ATTRIBUTE_LABELS } from "./primaryAttributes";

export const AXIS_INSPECTOR_BUTTON_ATTR = "data-axis-inspector-button";
export const AXIS_INSPECTOR_RESULT_ATTR = "data-axis-inspector-result";

const UNAVAILABLE_HTML = `<div style="font-size:var(--font-size-sm); margin-top:var(--space-1);">内訳を取得できませんでした。</div>`;

function formatDifficulty(value: number | null): string {
  return value == null ? "算出不可" : `${value.toFixed(1)}/100`;
}

// 改善計画T168: result.tagsは生のOSMタグ（way単位、レジストリ外のキーも含みうる）だが、
// キーがレジストリ登録済みの一次属性（PRIMARY_ATTRIBUTE_LABELS、T163のカタログ正式名）と
// 一致する場合はその正式名を表示する（1次→2次の逆導出と対で「同じ属性は同じ名前で呼ぶ」
// 統一ルールT30に揃える）。一致しないキー（name/ref等、登録外の生タグ）は従来どおりraw keyのまま。
function buildAxisInspectorHtml(result: AxisInspectorResult, axisLabels: Record<string, string>): string {
  const primaryRows = Object.entries(result.tags)
    .map(([key, value]) => `${PRIMARY_ATTRIBUTE_LABELS[key] ?? key}=${value}`)
    .join(", ");
  const axisRows = result.axes
    .map((axis) => {
      const label = axisLabels[axis.axis_id] ?? axis.axis_id;
      const suffix = axis.available ? "" : "（この区間では算出不可）";
      return `${label}: ${formatDifficulty(axis.difficulty)}${suffix}`;
    })
    .join("<br/>");

  const compositeRow =
    result.composite_difficulty != null
      ? `<strong>合成コスト（参考値）: ${result.composite_difficulty.toFixed(1)}/100</strong>` +
        (result.covered_weight_fraction != null && result.covered_weight_fraction < 0.999
          ? `<br/><span style="color:var(--color-muted);">重みの約${Math.round(result.covered_weight_fraction * 100)}%に相当する軸のみで算出（勾配・風はこの区間単体では算出できないため未算入。実際のルート探索コストとは一致しません）</span>`
          : "")
      : `<span style="color:var(--color-muted);">合成コストを算出できる軸がありません。</span>`;

  return `<div style="font-size:var(--font-size-sm); line-height:1.4; margin-top:var(--space-1); border-top:1px solid var(--color-border); padding-top:var(--space-1);">
    <strong>一次属性</strong><br/>
    ${PRIMARY_ATTRIBUTE_LABELS.highway}: ${result.highway ?? "不明"}${result.is_designated ? "（指定路線）" : ""}<br/>
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
  axisLabels: Record<string, string>,
) {
  const button = popupElement.querySelector<HTMLButtonElement>(`[${AXIS_INSPECTOR_BUTTON_ATTR}]`);
  const resultEl = popupElement.querySelector<HTMLElement>(`[${AXIS_INSPECTOR_RESULT_ATTR}]`);
  if (!button || !resultEl) return;
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "取得中…";
    try {
      const result = await fetchAxisInspector(osmWayId);
      resultEl.innerHTML = result ? buildAxisInspectorHtml(result, axisLabels) : UNAVAILABLE_HTML;
    } catch {
      resultEl.innerHTML = UNAVAILABLE_HTML;
    } finally {
      button.remove();
    }
  });
}
