// 路面クリックのポップアップ本文（`buildRoadSurfacePopupHtml`）。
//
// 出力は`Popup.setHTML()`へ渡るHTML文字列で、OSMタグ由来の生値（道路名・路線番号）を
// 含む。第三者が編集できるデータで対訳表を持たないため、タグとして解釈されないことを
// DOMで確かめる（popupEscape.ts参照）。
import { describe, expect, it } from "vitest";

import { buildRoadSurfacePopupHtml, type RoadSurfacePopupProperties } from "@/components/Map/MapView";

function render(properties: RoadSurfacePopupProperties): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = buildRoadSurfacePopupHtml(properties);
  return el;
}

describe("buildRoadSurfacePopupHtml の道路名", () => {
  it("nameとrefの両方があれば1行へ畳む", () => {
    expect(render({ name: "明治通り", ref: "R305" }).textContent).toContain("明治通り[R305]");
  });

  it("片方だけ持つwayでも出す（名前だけの市道・番号だけの国道）", () => {
    expect(render({ name: "明治通り" }).textContent).toContain("明治通り");
    expect(render({ ref: "R305" }).textContent).toContain("R305");
  });

  it("どちらも無ければ道路名の行自体を出さない（空の見出しを残さない）", () => {
    const el = render({ surface_good: true });
    expect(el.querySelector("b")).toBeNull();
    expect(el.textContent).toContain("路面: ");
  });

  it("道路名は路面より先に出す（どの道かを決める情報のため）", () => {
    const text = render({ name: "明治通り", surface_good: true }).textContent ?? "";
    expect(text.indexOf("明治通り")).toBeLessThan(text.indexOf("路面: "));
  });

  // 判定はDOMで行う（innerHTMLを読み返すと、テキストノード中の&quot;は"へ戻って
  // 再直列化されるため、エスケープされていても文字列比較では見分けられない）。
  it("OSMの道路名・路線番号の生値がタグとして解釈されない", () => {
    const attack = '<img src=x onerror="alert(1)">';

    for (const properties of [{ name: attack }, { ref: attack }]) {
      const el = render(properties);
      expect(el.querySelector("img")).toBeNull();
      // 生値はテキストとして残る（エスケープであって削除ではない）。
      expect(el.textContent).toContain(attack);
    }
  });
});
