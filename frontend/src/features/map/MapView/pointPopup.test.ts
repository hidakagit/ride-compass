/**
 * `pointPopup.ts`——点を押したときの説明が、点の名前と区分の名前（凡例と同じ宣言）を並べ、引けない値を「不明」にし、
 * 事故の点の発生年を添え、第三者が編集できる値をタグとして解釈しないこと。
 *
 * 点の宣言は架空のもので与える（実在の区分の名前をテストへ書き写さない）。
 */
import { afterEach, describe, expect, it } from "vitest";

import type { PointAxis } from "@/features/map/scene/groups/points";

import { buildPointPopupContent } from "./pointPopup";

function axis(property: string, categories: [string, (string | boolean)[]][]): PointAxis {
  return {
    key: property,
    label: "",
    property,
    categories: categories.map(([label, values]) => ({ key: label, label, values, color: "#000" })),
  } as unknown as PointAxis;
}

const KIND = axis("kind", [["区分A", ["a1", "a2"]]]);
const FLAG = axis("flag", [
  ["当てはまる", [true]],
  ["当てはまらない", [false]],
]);

afterEach(() => {
  document.body.replaceChildren();
});

describe("buildPointPopupContent", () => {
  it("点の名前と、値が属する区分の名前を出し、区分に無い値・値が無いときは「不明」にする", () => {
    const layer = { label: "点", display_axes: [KIND] };
    expect(buildPointPopupContent(layer, { kind: "a2" }).textContent).toBe("点: 区分A");
    expect(buildPointPopupContent(layer, { kind: "unregistered" }).textContent).toBe("点: 不明");
    expect(buildPointPopupContent(layer, { kind: null }).textContent).toBe("点: 不明");
  });

  it("区分の軸が複数なら並べ、発生年があれば改行して添える", () => {
    const content = buildPointPopupContent(
      { label: "事故", display_axes: [KIND, FLAG] },
      { kind: "a1", flag: false, occurred_year: 2023 },
    );
    expect(content.querySelectorAll("br")).toHaveLength(1);
    expect(content.textContent).toBe("事故: 区分A ・ 当てはまらない発生年: 2023");
  });

  it("名前へ仕込んだタグ・属性は、要素として描かれず文字のまま出る", () => {
    const attack = '<img src=x onerror="alert(1)"><script>alert(2)</script><details open ontoggle="alert(3)">';
    const content = buildPointPopupContent({ label: attack, display_axes: [KIND] }, { kind: "a1" });
    document.body.appendChild(content);

    expect(content.querySelector("img, script, details")).toBeNull();
    expect(content.querySelectorAll("[onerror], [ontoggle]")).toHaveLength(0);
    expect(content.textContent).toBe(`${attack}: 区分A`);
  });
});
