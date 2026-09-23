import { afterEach, describe, expect, it } from "vitest";

import { buildAccidentPopupContent, buildPoiPopupContent } from "./pointPopup";

const LABELS = { traffic_signals: "信号" };

afterEach(() => {
  document.body.replaceChildren();
});

describe("buildPoiPopupContent", () => {
  it("対訳表に載る値はその文言で出す", () => {
    expect(buildPoiPopupContent("停止要因", LABELS, { kind: "traffic_signals" }).textContent).toBe("停止要因: 信号");
  });

  it("対訳表に無いOSMタグの生値へ仕込んだタグ・属性は、要素として描かれず文字のまま出る", () => {
    const attack = '<img src=x onerror="alert(1)"><script>alert(2)</script><details open ontoggle="alert(3)">';

    const content = buildPoiPopupContent("停止要因", LABELS, { kind: attack });
    document.body.appendChild(content);

    expect(content.querySelector("img, script, details")).toBeNull();
    expect(content.querySelectorAll("[onerror], [ontoggle]")).toHaveLength(0);
    expect(content.textContent).toBe(`停止要因: ${attack}`);
  });

  it("kindが無ければ「不明」", () => {
    expect(buildPoiPopupContent("補給", LABELS, { kind: null }).textContent).toBe("補給: 不明");
  });
});

describe("buildAccidentPopupContent", () => {
  it("行を改行で区切って出す", () => {
    const content = buildAccidentPopupContent({ involves_bicycle: true, fatal: true, occurred_year: 2023 });

    expect(content.querySelectorAll("br")).toHaveLength(2);
    expect(content.textContent).toBe("自転車関連事故死亡事故発生年: 2023");
  });
});
