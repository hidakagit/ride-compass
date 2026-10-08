/**
 * `pointPopup.ts`——点を押したときの説明が、点の名前と区分の名前（凡例と同じ宣言）を並べ、引けない値を「不明」にし、
 * 宣言が点に添える事実を値のあるものだけ並べ、名前のある点には名前と、名前と位置で外の地図を開く導線を出し、
 * 第三者が編集できる値をタグとして解釈しないこと。
 *
 * 点の宣言は架空のもので与える（実在の区分の名前をテストへ書き写さない）。
 */
import { afterEach, describe, expect, it } from "vitest";

import type { PointAxis } from "@/features/map/scene/groups/points";

import { buildPointPopupContent } from "./pointPopup";

const AT = { lng: 139.6497, lat: 35.7053 };

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

const YEAR = { property: "year", label: "年" };
const NOTE = { property: "note", label: "備考" };

afterEach(() => {
  document.body.replaceChildren();
});

describe("buildPointPopupContent", () => {
  it("点の名前と、値が属する区分の名前を出し、区分に無い値は「不明」にする", () => {
    const layer = { label: "点", display_axes: [KIND], point_facts: [], point_name_property: null };
    expect(buildPointPopupContent(layer, { kind: "a2" }, AT).textContent).toBe("点: 区分A");
    expect(buildPointPopupContent(layer, { kind: "unregistered" }, AT).textContent).toBe("点: 不明");
  });

  it("区分の軸が複数なら並べ、宣言の事実は値のあるものだけを改行して添える", () => {
    const content = buildPointPopupContent(
      { label: "点", display_axes: [KIND, FLAG], point_facts: [YEAR, NOTE], point_name_property: null },
      { kind: "a1", flag: false, year: 2023 },
      AT,
    );
    expect(content.querySelectorAll("br")).toHaveLength(1);
    expect(content.textContent).toBe("点: 区分A ・ 当てはまらない年: 2023");
  });

  it("名前へ仕込んだタグ・属性は、要素として描かれず文字のまま出る", () => {
    const attack = '<img src=x onerror="alert(1)"><script>alert(2)</script><details open ontoggle="alert(3)">';
    const content = buildPointPopupContent(
      { label: attack, display_axes: [KIND], point_facts: [], point_name_property: "name" },
      { kind: "a1", name: attack },
      AT,
    );
    document.body.appendChild(content);

    expect(content.querySelector("img, script, details")).toBeNull();
    expect(content.querySelectorAll("[onerror], [ontoggle]")).toHaveLength(0);
    expect(content.textContent).toBe(`${attack}${attack}: 区分AGoogleマップで営業を確かめる`);
  });

  it("名前のある点は、名前を先頭に出し、名前と位置で外の地図を別の画面で開く導線を添える", () => {
    const layer = { label: "点", display_axes: [KIND], point_facts: [], point_name_property: "name" };
    const content = buildPointPopupContent(layer, { kind: "a1", name: "店 1&2" }, AT);

    const link = content.querySelector("a");
    expect(content.firstChild?.textContent).toBe("店 1&2");
    expect(link?.target).toBe("_blank");
    expect(link?.rel).toBe("noopener noreferrer");
    const url = new URL(link!.href);
    expect(`${url.origin}${url.pathname}`).toBe("https://www.google.com/maps/search/");
    expect(url.searchParams.get("api")).toBe("1");
    expect(url.searchParams.get("query")).toBe("店 1&2 35.705300,139.649700");
  });

  it.each([[{ kind: "a1" }], [{ kind: "a1", name: "" }]])(
    "名前の無い点（%o）は、名前も導線も出さない",
    (properties) => {
      const layer = { label: "点", display_axes: [KIND], point_facts: [], point_name_property: "name" };
      const content = buildPointPopupContent(layer, properties, AT);

      expect(content.querySelector("a")).toBeNull();
      expect(content.textContent).toBe("点: 区分A");
    },
  );
});
