import { expect, test } from "@playwright/test";
import { installApiMocks } from "./fixtures";

// カスケードの勝ち負け（パターン4 観点3）。vitest（happy-dom）はCSSのカスケードを解かないため、
// 計算後の値は実ブラウザでしか読めない。

/** Tailwindの余白ユーティリティ（`p-2`・`px-[0.9rem]`・`-mt-1`等）。変種（`sm:`・`hover:`）付きは対象外。 */
const SPACING_UTILITY = /^(-?)([pm])([xytrblse]?)-(\d+(?:\.\d+)?|\[[^\]]+\])$/;

const SIDES: Record<string, readonly string[]> = {
  "": ["top", "right", "bottom", "left"],
  x: ["right", "left"],
  y: ["top", "bottom"],
  t: ["top"],
  r: ["right"],
  b: ["bottom"],
  l: ["left"],
  s: ["left"],
  e: ["right"],
};

// globals.cssのリセット（`* { padding: 0; margin: 0 }`・`button`の既定の余白）は`@layer base`に
// 置かれ、Tailwindの`@layer utilities`に負ける。リセットが層の外へ出ると、詳細度に関係なく
// ユーティリティを潰す（層の外のルールは、どの層のルールより強い）。
// 母集団は画面に在る余白ユーティリティ全部。各要素の計算後の余白が、そのユーティリティ自身の
// 値と一致することを見る（期待値は同じ場所に置いた試し要素で、ブラウザに計算させる）。
test("Tailwindの余白ユーティリティは、globals.cssのリセットに潰されない", async ({ page }) => {
  await installApiMocks(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "ルート生成" })).toBeVisible();

  const result = await page.evaluate(
    ({ pattern, sides }) => {
      const utility = new RegExp(pattern);
      const checked: string[] = [];
      const mismatches: Array<{ element: string; utility: string; side: string; expected: string; actual: string }> =
        [];
      for (const element of document.querySelectorAll<HTMLElement>("body *")) {
        for (const token of element.classList) {
          const match = utility.exec(token);
          if (!match) continue;
          const [, negative, kind, axis, amount] = match;
          const property = kind === "p" ? "padding" : "margin";
          const length = amount.startsWith("[")
            ? amount.slice(1, -1).replaceAll("_", " ")
            : `calc(var(--spacing) * ${amount})`;
          const probe = document.createElement("div");
          probe.style.position = "absolute";
          probe.style.visibility = "hidden";
          probe.style.setProperty(`${property}-left`, negative ? `calc(${length} * -1)` : length, "important");
          element.parentElement?.appendChild(probe);
          const expected = getComputedStyle(probe).getPropertyValue(`${property}-left`);
          probe.remove();
          const computed = getComputedStyle(element);
          for (const side of sides[axis]) {
            const actual = computed.getPropertyValue(`${property}-${side}`);
            if (actual !== expected) {
              mismatches.push({
                element: `${element.tagName.toLowerCase()} "${(element.textContent ?? "").trim().slice(0, 20)}"`,
                utility: token,
                side,
                expected,
                actual,
              });
            }
          }
          checked.push(token);
        }
      }
      return { checked, mismatches };
    },
    { pattern: SPACING_UTILITY.source, sides: SIDES },
  );

  expect(result.checked.length).toBeGreaterThan(0);
  expect(result.mismatches).toEqual([]);
});
