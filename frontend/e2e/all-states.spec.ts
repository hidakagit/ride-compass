import { expect, test, type Browser, type Page } from "@playwright/test";
import { installApiMocks } from "./fixtures";
import { scanLayout, scanPinch, scanSpacingUtilities } from "./scans";
import {
  WIDTHS,
  assertWidthsStraddleBreakpoint,
  listModes,
  listSwitches,
  openBase,
  pressSwitch,
  type Phase,
  type WidthName,
} from "./states";

// 観点1〜3（パターン4）の走査を、画面の全状態へ当てる。状態の母集団は states.ts が画面から導く
// （幅 × モード × 段階 × 開いているシート・パネル。シート・パネルは基本の状態から2段まで開く）。
// 観点2（ピンチ）はタッチの文脈（モバイル幅）だけで見る。

async function newPage(browser: Browser, width: WidthName): Promise<Page> {
  const touch = width === "mobile";
  const context = await browser.newContext({ viewport: WIDTHS[width], isMobile: touch, hasTouch: touch });
  const page = await context.newPage();
  await installApiMocks(page);
  return page;
}

for (const width of Object.keys(WIDTHS) as WidthName[]) {
  for (const phase of ["生成前", "生成後"] as Phase[]) {
    test(`全状態の走査: ${width} / ${phase}`, async ({ browser }) => {
      test.setTimeout(15 * 60_000);
      const started = Date.now();

      const probe = await newPage(browser, width);
      await openBase(probe, width, phase, null);
      await assertWidthsStraddleBreakpoint(probe);
      const modes = await listModes(probe);
      expect(modes.length, "ヘッダーのメニューからモードが1つも見つからない").toBeGreaterThan(0);
      await probe.context().close();

      // 違反 → 最初に見つかった状態の道筋。
      const problems = new Map<string, string>();
      const visited: string[] = [];
      // 2段目で押せなかった部品（1段目で開いたポップオーバー等が上に重なっている）。
      const covered: string[] = [];
      let checkedUtilities = 0;
      let checkedPinches = 0;

      for (const mode of [null, ...modes]) {
        const page = await newPage(browser, width);
        const client = width === "mobile" ? await page.context().newCDPSession(page) : null;
        const inspect = async (path: string) => {
          visited.push(path);
          const record = (problem: string) => {
            if (!problems.has(problem)) problems.set(problem, path);
          };
          (await scanLayout(page)).forEach(record);
          const spacing = await scanSpacingUtilities(page);
          checkedUtilities += spacing.checked;
          spacing.problems.forEach(record);
          if (client) {
            const pinch = await scanPinch(page, client);
            checkedPinches += pinch.checked;
            pinch.problems.forEach(record);
          }
        };

        const label = `${width} / ${phase} / ${mode ?? "モードなし"}`;
        // 画面の状態の一部（グループの開閉等）はlocalStorageへ保存され、開き直しても残る。
        // 基本の状態を作った時点の保存内容を控え、開き直すたびにそこへ戻す。
        await openBase(page, width, phase, mode);
        const baseStorage = await page.evaluate(() => Object.fromEntries(Object.entries(window.localStorage)));
        const reopen = async () => {
          await page.evaluate((entries) => {
            window.localStorage.clear();
            for (const [key, value] of Object.entries(entries)) window.localStorage.setItem(key, value);
          }, baseStorage);
          await openBase(page, width, phase, mode);
        };
        await reopen();
        await inspect(label);
        const first = await listSwitches(page);
        const firstKeys = new Set(first.map((s) => s.key));

        for (const s1 of first) {
          await reopen();
          // 基本の状態で見えていた部品は、開き直しても同じ見分けで見つかり、押せるはず。
          // そうでなければ列挙の側が壊れている。
          const failed1 = await pressSwitch(page, s1);
          if (failed1) {
            problems.set(`${s1.key} を${failed1}`, label);
            continue;
          }
          await inspect(`${label} > ${s1.key}`);
          const second = (await listSwitches(page)).filter((s) => !firstKeys.has(s.key));
          for (const [index, s2] of second.entries()) {
            if (index > 0) {
              await reopen();
              await pressSwitch(page, s1);
            }
            const failed2 = await pressSwitch(page, s2);
            if (failed2) {
              covered.push(`${label} > ${s1.key} > ${s2.key}: ${failed2}`);
              continue;
            }
            await inspect(`${label} > ${s1.key} > ${s2.key}`);
          }
        }
        await page.context().close();
      }

      console.log(
        `状態 ${visited.length}件・余白ユーティリティ ${checkedUtilities}件・ピンチ ${checkedPinches}件を ` +
          `${Math.round((Date.now() - started) / 1000)}秒で走査、` +
          `2段目で押せなかった部品 ${covered.length}件（${width} / ${phase}）`,
      );
      // 列挙の検算: 他のテストが前提にしている状態へ、この列挙も届いていること。
      if (width === "mobile") expect(visited.some((path) => path.includes('"ルート結果"'))).toBe(true);
      if (phase === "生成後") expect(visited.some((path) => path.includes('tab "比較"'))).toBe(true);

      const report = [...problems.entries()].map(([problem, path]) => `${problem} ← ${path}`);
      expect(report).toEqual([]);
    });
  }
}
