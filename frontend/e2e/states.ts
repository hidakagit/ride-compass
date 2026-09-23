import { expect, type Page } from "@playwright/test";
import { MOBILE_VIEWPORT, openMobileSheet } from "./fixtures";

// 画面の状態（幅 × モード × 段階 × 開いているシート・パネル）を、手で並べずに画面から導く。
// 状態を切り替える部品は、画面がARIAで宣言している:
// - 開閉するもの: `aria-expanded`を持つ部品（折りたたみ・ポップオーバー・チップのグループ等）
// - 表示を切り替えるもの: `role="tab"`
// - モバイルの下部シート: 「パネル切り替え」のナビゲーションの中の`aria-pressed`の部品
// モードは、ヘッダーのメニューに並ぶチェックボックス（研究モード等）から導く。

export const WIDTHS = {
  mobile: MOBILE_VIEWPORT,
  desktop: { width: 1280, height: 800 },
} as const;
export type WidthName = keyof typeof WIDTHS;

/** アプリの段階。ルートを生成する前と後で、画面に出る部品の集合が入れ替わる。 */
export type Phase = "生成前" | "生成後";

const SWITCH_SELECTOR = [
  '[aria-expanded="false"]',
  '[role="tab"][aria-selected="false"]',
  'nav[aria-label="パネル切り替え"] [aria-pressed="false"]',
].join(", ");

export interface Switch {
  /** 部品の見分け（種類・名前・同じ見分けの中での順番）。再読み込みしても同じ部品を指す。 */
  key: string;
}

/** 幅の分岐はCSSのブレークポイント1つだけで、WIDTHSはその両側に1つずつ置く。 */
export async function assertWidthsStraddleBreakpoint(page: Page): Promise<void> {
  const breakpoint = await page.evaluate(() =>
    Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--breakpoint-mobile")),
  );
  expect(breakpoint, "--breakpoint-mobile が読めない").toBeGreaterThan(0);
  expect(WIDTHS.mobile.width).toBeLessThanOrEqual(breakpoint);
  expect(WIDTHS.desktop.width).toBeGreaterThan(breakpoint);
}

async function waitReady(page: Page): Promise<void> {
  await expect(page.getByRole("button", { name: "メニュー" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 15_000 });
}

/** 切り替え部品の並びが落ち着くまで待つ（カタログ・世代の到着で部品が後から増える）。 */
async function waitSwitchesSettled(page: Page): Promise<void> {
  let previous = "";
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const current = JSON.stringify(await listSwitches(page));
    if (current === previous) return;
    previous = current;
    await page.waitForTimeout(300);
  }
}

/** ヘッダーのメニューにあるモード（チェックボックス）の名前。 */
export async function listModes(page: Page): Promise<string[]> {
  await page.getByRole("button", { name: "メニュー" }).click();
  const names = await page
    .getByRole("dialog")
    .getByRole("checkbox")
    .evaluateAll((elements) =>
      elements.map((element) => element.getAttribute("aria-label") ?? element.textContent?.trim() ?? ""),
    );
  await page.keyboard.press("Escape");
  return names;
}

/** 画面を開き直して、指定の幅・モード・段階の基本の状態（シート・パネルを開いていない）にする。 */
export async function openBase(page: Page, width: WidthName, phase: Phase, mode: string | null): Promise<void> {
  await page.goto("/");
  await waitReady(page);
  if (mode) {
    await page.getByRole("button", { name: "メニュー" }).click();
    const checkbox = page.getByRole("dialog").getByRole("checkbox", { name: mode });
    if ((await checkbox.getAttribute("aria-checked")) !== "true") await checkbox.click();
    await page.keyboard.press("Escape");
  }
  if (phase === "生成後") {
    if (width === "mobile") {
      const sheet = await openMobileSheet(page, "ルート設定");
      await sheet.getByRole("button", { name: "ルート生成" }).click();
      await expect(sheet.getByRole("button", { name: "ルート生成" })).toBeEnabled({ timeout: 60_000 });
      await page.getByRole("button", { name: "ルート設定", exact: true }).click();
      await expect(sheet).toBeHidden();
    } else {
      await page.getByRole("button", { name: "ルート生成" }).click();
      await expect(page.getByRole("button", { name: "ルート生成" })).toBeEnabled({ timeout: 60_000 });
    }
  }
  await waitSwitchesSettled(page);
}

/** いま画面に見えている、状態を切り替える部品。 */
export async function listSwitches(page: Page): Promise<Switch[]> {
  return page.evaluate((selector) => {
    const seen = new Map<string, number>();
    const result: { key: string }[] = [];
    for (const element of document.querySelectorAll<HTMLElement>(selector)) {
      const box = element.getBoundingClientRect();
      if (box.width === 0 || box.height === 0 || !element.checkVisibility({ visibilityProperty: true })) continue;
      const kind = element.getAttribute("role") ?? element.tagName.toLowerCase();
      const name = (element.getAttribute("aria-label") ?? element.textContent ?? "")
        .trim()
        .replace(/\d+/g, "#")
        .slice(0, 40);
      const base = `${kind} "${name}"`;
      const index = seen.get(base) ?? 0;
      seen.set(base, index + 1);
      result.push({ key: index === 0 ? base : `${base} #${index + 1}` });
    }
    return result;
  }, SWITCH_SELECTOR);
}

/** 切り替え部品を1つ押す。見つからない・押せないときは理由を返す（押せたら null）。 */
export async function pressSwitch(page: Page, target: Switch): Promise<string | null> {
  // 部品は後から現れることがある（カタログの到着等）。しばらく探し直す。
  for (let attempt = 0; attempt < 10; attempt += 1) {
    if (await markSwitch(page, target)) break;
    if (attempt === 9) return "見つからない";
    await page.waitForTimeout(500);
  }
  try {
    await page.locator("[data-e2e-switch]").click({ timeout: 3000 });
  } catch (error) {
    return `押せない（${String(error).split("\n")[0].slice(0, 120)}）`;
  }
  await page.waitForTimeout(300);
  return null;
}

async function markSwitch(page: Page, target: Switch): Promise<boolean> {
  return page.evaluate(
    ({ selector, key }) => {
      document.querySelectorAll("[data-e2e-switch]").forEach((element) => element.removeAttribute("data-e2e-switch"));
      const seen = new Map<string, number>();
      for (const element of document.querySelectorAll<HTMLElement>(selector)) {
        const box = element.getBoundingClientRect();
        if (box.width === 0 || box.height === 0 || !element.checkVisibility({ visibilityProperty: true })) continue;
        const kind = element.getAttribute("role") ?? element.tagName.toLowerCase();
        const name = (element.getAttribute("aria-label") ?? element.textContent ?? "")
          .trim()
          .replace(/\d+/g, "#")
          .slice(0, 40);
        const base = `${kind} "${name}"`;
        const index = seen.get(base) ?? 0;
        seen.set(base, index + 1);
        if ((index === 0 ? base : `${base} #${index + 1}`) === key) {
          element.setAttribute("data-e2e-switch", "");
          return true;
        }
      }
      return false;
    },
    { selector: SWITCH_SELECTOR, key: target.key },
  );
}
