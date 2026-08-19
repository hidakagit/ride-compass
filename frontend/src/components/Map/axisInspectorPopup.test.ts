import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AXIS_INSPECTOR_BUTTON_ATTR,
  AXIS_INSPECTOR_RESULT_ATTR,
  attachAxisInspectorHandler,
  buildAxisInspectorAffordanceHtml,
} from "./axisInspectorPopup";
import type { AxisInspectorResult } from "@/types/traffic";

function makePopupElement(): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = buildAxisInspectorAffordanceHtml();
  return el;
}

const SAMPLE_RESULT: AxisInspectorResult = {
  highway: "residential",
  tags: { surface: "asphalt" },
  is_designated: false,
  axes: [
    { axis_id: "car_stress", difficulty: 25.0, weight: 0.2, available: true },
    { axis_id: "surface_q", difficulty: 0.0, weight: 0.19, available: true },
    { axis_id: "stop_density", difficulty: 50.0, weight: 0.2, available: true },
    { axis_id: "accident", difficulty: null, weight: 0.08, available: false },
    { axis_id: "night", difficulty: 0.0, weight: 0.0, available: true },
    { axis_id: "gradient", difficulty: null, weight: 0.15, available: false },
    { axis_id: "wind", difficulty: null, weight: 0.26, available: false },
  ],
  composite_difficulty: 25.0,
  covered_weight_fraction: 0.62,
};

describe("axisInspectorPopup", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("buildAxisInspectorAffordanceHtmlはボタン・結果表示先を含む", () => {
    const el = makePopupElement();
    expect(el.querySelector(`[${AXIS_INSPECTOR_BUTTON_ATTR}]`)).not.toBeNull();
    expect(el.querySelector(`[${AXIS_INSPECTOR_RESULT_ATTR}]`)).not.toBeNull();
  });

  it("ボタン押下でfetchし、軸ラベル・スコア・合成コスト・欠損軸の注記を表示する", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        headers: new Headers(),
        json: async () => SAMPLE_RESULT,
      }),
    );
    const el = makePopupElement();
    attachAxisInspectorHandler(el, 12345, undefined, undefined, undefined);

    const button = el.querySelector<HTMLButtonElement>(`[${AXIS_INSPECTOR_BUTTON_ATTR}]`)!;
    button.click();
    // fetchのPromise解決を待つ（マイクロタスクを1周させる）
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));

    const resultEl = el.querySelector<HTMLElement>(`[${AXIS_INSPECTOR_RESULT_ATTR}]`)!;
    expect(resultEl.innerHTML).toContain("車の圧迫感");
    expect(resultEl.innerHTML).toContain("停止密度");
    expect(resultEl.innerHTML).toContain("風"); // レジストリ未登録軸の補完ラベル
    expect(resultEl.innerHTML).toContain("算出不可");
    expect(resultEl.innerHTML).toContain("合成コスト（参考値）: 25.0/100");
    expect(resultEl.innerHTML).toContain("62%");
    // 改善計画T168: 一次属性のラベルはレジストリのカタログ正式名（PRIMARY_ATTRIBUTE_LABELS）へ
    // 共通化する。highwayは専用行、tagsのキーはレジストリ登録済みのものだけ正式名に変わる
    // （生タグのkeyのまま出さない）。
    expect(resultEl.innerHTML).toContain("道路の種類: residential");
    expect(resultEl.innerHTML).toContain("路面の種類=asphalt");
    expect(resultEl.innerHTML).not.toContain("surface=asphalt");
    // 取得後はボタン自体が消える（他のbreakdown系ポップアップと同じ挙動）
    expect(el.querySelector(`[${AXIS_INSPECTOR_BUTTON_ATTR}]`)).toBeNull();
  });

  it("レジストリ未登録の生タグ（name等）はキーのまま表示する（改善計画T168）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        headers: new Headers(),
        json: async () => ({ ...SAMPLE_RESULT, tags: { name: "テスト通り" } }),
      }),
    );
    const el = makePopupElement();
    attachAxisInspectorHandler(el, 12345, undefined, undefined, undefined);
    el.querySelector<HTMLButtonElement>(`[${AXIS_INSPECTOR_BUTTON_ATTR}]`)!.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));

    const resultEl = el.querySelector<HTMLElement>(`[${AXIS_INSPECTOR_RESULT_ATTR}]`)!;
    expect(resultEl.innerHTML).toContain("name=テスト通り");
  });

  it("fetch失敗時は「取得できませんでした」を表示する", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network error")));
    const el = makePopupElement();
    attachAxisInspectorHandler(el, 12345, undefined, undefined, undefined);

    el.querySelector<HTMLButtonElement>(`[${AXIS_INSPECTOR_BUTTON_ATTR}]`)!.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));

    const resultEl = el.querySelector<HTMLElement>(`[${AXIS_INSPECTOR_RESULT_ATTR}]`)!;
    expect(resultEl.innerHTML).toContain("取得できませんでした");
  });
});
