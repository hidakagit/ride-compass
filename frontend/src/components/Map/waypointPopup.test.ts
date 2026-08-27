import { describe, expect, it, vi } from "vitest";

import { WAYPOINT_ADD_BUTTON_ATTR, attachWaypointAddHandler, buildWaypointAddAffordanceHtml } from "./waypointPopup";

function makePopupElement(): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = buildWaypointAddAffordanceHtml();
  return el;
}

describe("waypointPopup", () => {
  it("buildWaypointAddAffordanceHtmlは経由地追加ボタンを含む", () => {
    const el = makePopupElement();
    expect(el.querySelector(`[${WAYPOINT_ADD_BUTTON_ATTR}]`)).not.toBeNull();
  });

  it("ボタン押下でonAddを呼び、ボタンを無効化してラベルを変える", () => {
    const el = makePopupElement();
    const onAdd = vi.fn();
    attachWaypointAddHandler(el, onAdd);

    const button = el.querySelector<HTMLButtonElement>(`[${WAYPOINT_ADD_BUTTON_ATTR}]`)!;
    button.click();

    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(true);
    expect(button.textContent).toBe("追加しました");
  });

  it("popupElementにボタンが無い場合は何もしない（防御的ガード）", () => {
    const el = document.createElement("div");
    expect(() => attachWaypointAddHandler(el, vi.fn())).not.toThrow();
  });
});
