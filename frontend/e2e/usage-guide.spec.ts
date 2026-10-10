import { expect, test, type Page } from "@playwright/test";
import { USAGE_PART_SELECTOR } from "@/components/UsageGuide/usageTarget";
import { installApiMocks, seedStoredState } from "./fixtures";
import { WIDTHS, installPageHelpers, openApp, type WidthName } from "./states";

// 使い方の説明の「中を見る」で開いた浮きパネルの中の部品も説明できること（パターン4 観点1）。浮きパネルは外への押し操作と
// フォーカスで閉じ、その出来事の届き方は実際のブラウザでしか確かめられない。生成前の基本の画面で説明を見る状態に入り、
// 押せる部品（押す点＝中心点のヒットテストが部品自身か子孫を返すもの）のうち浮きパネルの開くボタンを1つずつ「中を見る」で
// 開き、中の部品を1つずつ押して、説明（使い方の文）が出て浮きパネルが開いたままかを見る。
// 折りたたみ・下部シートのタブ・選ばれていないタブ等の「中を見る」は開くだけで、開いた先は今の画面の部品と同じ扱いなので、ここでは開かない
// （出す部品の見分けと開くことは単体テスト）。

interface Part {
  label: string;
  /** 浮きパネルの開くボタンか。 */
  popover: boolean;
  box: { left: number; top: number; right: number; bottom: number };
}

/** いま押せる部品。`insideOpened`なら、開いている浮きパネルの中のものだけ。 */
async function pressableParts(page: Page, insideOpened = false): Promise<Part[]> {
  return page.evaluate(
    ({ selector, insideOpened }) => {
      const opener = document.querySelector('[data-usage-opens][aria-expanded="true"]');
      const opened = opener && document.getElementById(opener.getAttribute("aria-controls") ?? "");
      const found: Part[] = [];
      for (const el of document.querySelectorAll(selector)) {
        // 案内（「やめる」）と説明の面は説明を見る状態の部品で、押しても説明を出さない。
        if (el.closest("[data-usage-guide]")) continue;
        if (insideOpened && !opened?.contains(el)) continue;
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
        found.push({
          label,
          popover: el.hasAttribute("data-usage-opens"),
          box: { left: r.left, top: r.top, right: r.right, bottom: r.bottom },
        });
      }
      return found;
    },
    { selector: USAGE_PART_SELECTOR, insideOpened },
  );
}

async function press(page: Page, part: Part) {
  await page.mouse.click((part.box.left + part.box.right) / 2, (part.box.top + part.box.bottom) / 2);
}

for (const width of Object.keys(WIDTHS) as WidthName[]) {
  test(`使い方の説明: ${width} で、「中を見る」で開いた浮きパネルの中の部品も説明する`, async ({ browser }) => {
    test.setTimeout(240_000);
    const touch = width === "mobile";
    const context = await browser.newContext({ viewport: WIDTHS[width], isMobile: touch, hasTouch: touch });
    const page = await context.newPage();
    await page.addInitScript(installPageHelpers);
    await installApiMocks(page);
    await seedStoredState(page, { "ridecompass:first-visit-intro-closed": "true" });
    await openApp(page);

    const enter = async () => {
      await page.getByRole("button", { name: "メニュー" }).click();
      await page.getByRole("button", { name: "使い方を見る" }).click();
      await expect(page.getByText("説明モード")).toBeVisible();
    };
    await enter();

    const openers = (await pressableParts(page)).filter((part) => part.popover);
    // 部品の集め方が空振りすると、何も見ずに通る。
    expect(openers.length, "浮きパネルの開くボタンが見つからない").toBeGreaterThan(3);

    // 開くボタンごとに「中を見る」で浮きパネルを開き、中の部品を1つずつ押す。浮きパネルは終えたあとも開いたまま残り、
    // 次の開くボタンを覆うことがあるので、開くボタンごとに「やめる」で終えて Esc で閉じ、入り直す。
    const panel = page.getByRole("dialog", { name: "使い方の説明" });
    const opened = page.locator('[data-usage-opens][aria-expanded="true"]');
    const problems: string[] = [];
    let inside = 0;
    for (const opener of openers) {
      await press(page, opener);
      await panel.getByRole("button", { name: "中を見る" }).click();
      await expect(panel).toBeHidden();
      await expect(opened).toHaveCount(1);
      const innerParts = await pressableParts(page, true);
      inside += innerParts.length;
      for (const part of innerParts) {
        await press(page, part);
        await expect(panel).toBeVisible();
        await expect(opened, `${opener.label} の中の ${part.label} を押すと浮きパネルが閉じる`).toHaveCount(1);
        if (await panel.getByText("この部品の説明はまだありません。").isVisible())
          problems.push(`${opener.label} の中の ${part.label} に使い方の文が無い`);
        await panel.getByRole("button", { name: "説明を閉じる" }).click();
        await expect(panel).toBeHidden();
      }
      await page.getByRole("button", { name: "やめる", exact: true }).click();
      await expect(opened).toHaveCount(1);
      await page.keyboard.press("Escape");
      await expect(opened).toHaveCount(0);
      await enter();
    }
    expect(inside, "浮きパネルの中で押せる部品が見つからない").toBeGreaterThan(3);

    console.log(
      `使い方の説明 ${width}: 開くボタン ${openers.length}件・その中の部品 ${inside}件、問題 ${problems.length}件`,
    );
    expect(problems).toEqual([]);
    await context.close();
  });
}
