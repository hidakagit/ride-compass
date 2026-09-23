import { expect, test } from "@playwright/test";
import { installApiMocks } from "./fixtures";
import { scanLayout, scanPinch, scanSpacingUtilities } from "./scans";
import {
  WIDTHS,
  assertWidthsStraddleBreakpoint,
  generate,
  installPageHelpers,
  openApp,
  resetPhase,
  traverse,
  type Phase,
  type WidthName,
} from "./states";

// 観点1〜3（パターン4）の走査を、画面の全状態へ当てる。状態は states.ts が画面から辿る
// （幅 × 段階を土台に、最前面で押せる開閉の部品を押せる限り）。配置の検査は状態ごと、部品の検査は
// 段階ごとに各部品1回。観点2（ピンチ）はタッチの文脈（モバイル幅）だけで見る。
// 幅ごとに1本にしてあり、CIでは幅ごとに別のジョブで走らせる。

// APIをモックして決定的に動くので、失敗時に再試行しても同じ結果になり、所要だけが倍になる。
test.describe.configure({ retries: 0 });

for (const width of Object.keys(WIDTHS) as WidthName[]) {
  test(`全状態の走査: ${width}`, async ({ browser }) => {
    test.setTimeout(150_000);
    const started = Date.now();
    const touch = width === "mobile";
    const context = await browser.newContext({ viewport: WIDTHS[width], isMobile: touch, hasTouch: touch });
    const page = await context.newPage();
    await page.addInitScript(installPageHelpers);
    await installApiMocks(page);
    const client = await context.newCDPSession(page);
    await client.send("Accessibility.enable");
    await client.send("DOM.enable");
    const resolved = new Map<number, string>();

    // 違反 → 最初に見つかった状態の道筋。
    const problems = new Map<string, string>();
    const counts = { widgets: 0, viaContainer: 0, spacing: 0, pinches: 0 };
    const summary: string[] = [];

    await openApp(page);
    await assertWidthsStraddleBreakpoint(page);
    for (const phase of ["生成前", "生成後"] as Phase[]) {
      if (phase === "生成後") await generate(page, width);
      await resetPhase(page);
      const phaseStarted = Date.now();
      const result = await traverse(page, `${width} / ${phase}`, async (path) => {
        const record = (problem: string) => {
          if (!problems.has(problem)) problems.set(problem, path);
        };
        const layout = await scanLayout(page, client, resolved);
        counts.widgets += layout.checked;
        counts.viaContainer += layout.viaContainer;
        layout.problems.forEach(record);
        const spacing = await scanSpacingUtilities(page);
        counts.spacing += spacing.checked;
        spacing.problems.forEach(record);
        if (touch) {
          const pinch = await scanPinch(page, client);
          counts.pinches += pinch.checked;
          pinch.problems.forEach(record);
        }
      });
      result.problems.forEach((problem) => problems.set(problem, `${width} / ${phase}`));
      // 辿る部品が1つも見つからなければ、土台しか見ていない（列挙が空振りしている）。
      expect(result.states, `${width} / ${phase}: 開いた状態が1件も無い`).toBeGreaterThan(1);
      summary.push(`${phase} ${result.states}状態（${Math.round((Date.now() - phaseStarted) / 1000)}秒）`);
      console.log(
        `全状態の走査 ${width}: ${summary.join("・")}、横幅の検査 ${counts.widgets}件（うち横スクロールする容器で判定 ` +
          `${counts.viaContainer}件）・余白ユーティリティ ${counts.spacing}件・ピンチ ${counts.pinches}件、` +
          `計${Math.round((Date.now() - started) / 1000)}秒`,
      );
      // 段階ごとに確かめる。違反が次の段階の段取り（生成）を壊すと、違反そのものが見えなくなる。
      const report = [...problems.entries()].map(([problem, path]) => `${problem} ← ${path}`);
      expect(report, `${width} / ${phase} の違反`).toEqual([]);
    }
    await context.close();
  });
}
