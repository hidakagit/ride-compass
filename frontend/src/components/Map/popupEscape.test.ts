// @vitest-environment node
import { describe, expect, it } from "vitest";

import { escapeHtml, labelOrEscapedRaw } from "./popupEscape";

const LABELS = { residential: "住宅街の道" };

describe("labelOrEscapedRaw", () => {
  it("対訳表に載る値はその文言をそのまま返す", () => {
    expect(labelOrEscapedRaw(LABELS, "residential")).toBe("住宅街の道");
  });

  it("対訳表に無い値（＝OSMタグの生値）はタグとして解釈されない形にする", () => {
    // 第三者が編集できるOSMタグへ仕込まれうる形。setHTML()へ渡る前にここで潰す。
    const attack = '<img src=x onerror="alert(1)">';

    const out = labelOrEscapedRaw(LABELS, attack);

    expect(out).not.toContain("<img");
    expect(out).not.toContain('onerror="');
    expect(out).toBe("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
  });

  it("閉じタグ・属性の切断に使える文字をすべて潰す", () => {
    expect(labelOrEscapedRaw(LABELS, `</div><script>a</script>`)).toBe(
      "&lt;/div&gt;&lt;script&gt;a&lt;/script&gt;",
    );
    expect(labelOrEscapedRaw(LABELS, `" onclick='x'`)).toBe("&quot; onclick=&#39;x&#39;");
  });

  it("無害な生値は読める形のまま残る（過剰にエスケープしない）", () => {
    expect(labelOrEscapedRaw(LABELS, "sett")).toBe("sett");
    expect(labelOrEscapedRaw(LABELS, "国道246号")).toBe("国道246号");
  });
});

describe("escapeHtml", () => {
  it("&を最初に置換する（後続の置換が生んだ実体参照を二重にしない）", () => {
    // `<`→`&lt;`のあとに`&`を置換すると`&amp;lt;`になり、画面に`&lt;`と出てしまう。
    expect(escapeHtml("a & b < c")).toBe("a &amp; b &lt; c");
    expect(escapeHtml("&lt;")).toBe("&amp;lt;");
  });

  it("同じ文字が複数あってもすべて置換する", () => {
    expect(escapeHtml("<<>>")).toBe("&lt;&lt;&gt;&gt;");
  });
});
