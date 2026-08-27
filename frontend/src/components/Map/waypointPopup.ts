// 改善計画T364: 地図クリック時に「この地点を経由地に追加」を選べるようにする拡張。
// axisInspectorPopup.tsと同じ「ボタン押下でイベントハンドラをDOMへ直接差し込む」方式
// （MapLibre PopupはReactツリー外のためaddTo後にquerySelectorで配線する）。
// 経由地追加はデータ取得を伴わない同期処理のため、axisInspectorPopup.tsのような
// fetch→結果差し込みではなく、コールバック呼び出し→ボタンを無効化するだけの単純な配線。

export const WAYPOINT_ADD_BUTTON_ATTR = "data-waypoint-add-button";

export function buildWaypointAddAffordanceHtml(): string {
  return `<div style="margin-top:var(--space-1);">
    <button type="button" ${WAYPOINT_ADD_BUTTON_ATTR} style="font:inherit; font-size:var(--font-size-sm); padding:2px 8px; cursor:pointer;">この地点を経由地に追加</button>
  </div>`;
}

export function attachWaypointAddHandler(popupElement: HTMLElement, onAdd: () => void) {
  const button = popupElement.querySelector<HTMLButtonElement>(`[${WAYPOINT_ADD_BUTTON_ATTR}]`);
  if (!button) return;
  button.addEventListener("click", () => {
    onAdd();
    button.disabled = true;
    button.textContent = "追加しました";
  });
}
