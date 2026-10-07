import { expect, test } from "@playwright/test";
import { USAGE_PART_SELECTOR } from "@/components/UsageGuide/usageTarget";
import { installApiMocks, seedStoredState } from "./fixtures";
import { WIDTHS, installPageHelpers, openApp, type WidthName } from "./states";

// 使い方の説明の面が、ほかの部品に重ならないこと（パターン4 観点1）。面の位置は実寸と位置取りで決まり、
// 単体テストの環境は実寸を返さない。生成前の基本の画面で説明を見る状態に入り、押せる部品（押す点＝中心点の
// ヒットテストが部品自身か子孫を返すもの）を全部集めて1つずつ押し、出た面の箱がほかの部品の箱と重ならないかを見る。
// 面に重なった部品は、押すつもりで面（✕）に当たる。

interface Part {
  label: string;
  box: { left: number; top: number; right: number; bottom: number };
}

for (const width of Object.keys(WIDTHS) as WidthName[]) {
  test(`使い方の説明: ${width} で、説明の面がほかの部品に重ならない`, async ({ browser }) => {
    test.setTimeout(120_000);
    const touch = width === "mobile";
    const context = await browser.newContext({ viewport: WIDTHS[width], isMobile: touch, hasTouch: touch });
    const page = await context.newPage();
    await page.addInitScript(installPageHelpers);
    await installApiMocks(page);
    await seedStoredState(page, { "ridecompass:first-visit-intro-closed": "true" });
    await openApp(page);

    await page.getByRole("button", { name: "メニュー" }).click();
    await page.getByRole("button", { name: "使い方を見る" }).click();
    await expect(page.getByText("説明を見たい部品を押してください")).toBeVisible();

    const parts: Part[] = await page.evaluate((selector) => {
      const found: Part[] = [];
      for (const el of document.querySelectorAll(selector)) {
        // 案内（「やめる」）は説明を見る状態の部品で、押しても説明を出さない。
        if (el.closest("[data-usage-guide]")) continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        if (hit === null || !el.contains(hit)) continue;
        // 入れ子の部品（囲む要素と中のボタン等）は、押す点が同じなら1つに数える。
        const sameSpot = found.some(
          ({ box }) => box.left + box.right === r.left + r.right && box.top + box.bottom === r.top + r.bottom,
        );
        if (sameSpot) continue;
        const label = el.getAttribute("aria-label") || el.textContent?.trim() || el.tagName;
        found.push({ label, box: { left: r.left, top: r.top, right: r.right, bottom: r.bottom } });
      }
      return found;
    }, USAGE_PART_SELECTOR);
    // 部品の集め方が空振りすると、何も見ずに通る。
    expect(parts.length, "説明を見る状態で押せる部品が見つからない").toBeGreaterThan(10);

    const panel = page.getByRole("dialog", { name: "使い方の説明" });
    const problems: string[] = [];
    for (const part of parts) {
      await page.mouse.click((part.box.left + part.box.right) / 2, (part.box.top + part.box.bottom) / 2);
      await expect(panel).toBeVisible();
      // 位置取りが落ち着くまで待つ（面は描いてから測って置き直す）。
      let box = await panel.boundingBox();
      await expect(async () => {
        const previous = box;
        await page.waitForTimeout(100);
        box = await panel.boundingBox();
        expect(box).toEqual(previous);
      }).toPass();
      const shown = box!;
      const overlapped = parts
        .filter((other) => other !== part)
        .filter(
          ({ box: b }) =>
            b.left < shown.x + shown.width && shown.x < b.right && b.top < shown.y + shown.height && shown.y < b.bottom,
        )
        .map((other) => other.label);
      if (overlapped.length > 0) problems.push(`${part.label} の説明が ${overlapped.join("・")} に重なる`);
      // 説明だけを閉じ、次の部品を面の無い画面で押す。
      await panel.getByRole("button", { name: "説明を閉じる" }).click();
      await expect(panel).toBeHidden();
      await expect(page.getByText("説明を見たい部品を押してください")).toBeVisible();
    }
    console.log(`使い方の説明 ${width}: 部品 ${parts.length}件、重なった ${problems.length}件`);
    expect(problems).toEqual([]);
    await context.close();
  });
}
