import { expect, test } from "@playwright/test";
import { installApiMocks, installMapFinder } from "./fixtures";
import { scanLayout, scanOverflowingContent, scanPinch, scanSpacingUtilities, scanTruncatedText } from "./scans";
import {
  PHASES,
  WIDTHS,
  assertWidthsStraddleBreakpoint,
  generate,
  installPageHelpers,
  installScanMocks,
  openApp,
  resetPhase,
  splice,
  traverse,
  type WidthName,
} from "./states";

// 観点1〜3（パターン4）の走査を、画面の全状態へ当てる。状態は states.ts が画面から辿る
// （幅 × 段階を土台に、最前面で押せる開閉の部品を押せる限り）。配置の検査は状態ごと、部品の検査は
// 段階ごとに各部品1回。観点2（ピンチ）はタッチの文脈（モバイル幅）だけで見る。
// 幅 × 段階ごとに1本にしてあり、CIでは幅ごとのジョブの中で段階を別のジョブへ分けて（--shard）走らせる。
// 各段階は開き直したページで、前の段階と同じ段取り（生成・乗り換え）を踏んでから辿る。

for (const width of Object.keys(WIDTHS) as WidthName[]) {
  for (const phase of PHASES) {
    test(`全状態の走査: ${width} / ${phase}`, async ({ browser }) => {
      test.setTimeout(120_000);
      const started = Date.now();
      const touch = width === "mobile";
      const context = await browser.newContext({ viewport: WIDTHS[width], isMobile: touch, hasTouch: touch });
      const page = await context.newPage();
      await page.addInitScript(installPageHelpers);
      await page.addInitScript(installMapFinder);
      await installApiMocks(page);
      await installScanMocks(page);
      const client = await context.newCDPSession(page);
      await client.send("Accessibility.enable");
      await client.send("DOM.enable");
      const resolved = new Map<number, string>();

      // 違反 → 最初に見つかった状態の道筋。
      const problems = new Map<string, string>();
      const counts = { widgets: 0, viaContainer: 0, truncatable: 0, overflowable: 0, spacing: 0, pinches: 0 };

      await openApp(page);
      await assertWidthsStraddleBreakpoint(page);
      if (phase !== "生成前") await generate(page, width);
      if (phase === "乗り換え後") await splice(page, width);
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
        const truncated = await scanTruncatedText(page);
        counts.truncatable += truncated.checked;
        truncated.problems.forEach(record);
        const overflowing = await scanOverflowingContent(page);
        counts.overflowable += overflowing.checked;
        overflowing.problems.forEach(record);
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
      console.log(
        `全状態の走査 ${width} / ${phase}: ${result.states}状態（${Math.round((Date.now() - phaseStarted) / 1000)}秒）、` +
          `横幅の検査 ${counts.widgets}件（うち横スクロールする容器で判定 ${counts.viaContainer}件）・省略の検査 ` +
          `${counts.truncatable}件・はみ出しの検査 ${counts.overflowable}件・余白ユーティリティ ${counts.spacing}件・ピンチ ` +
          `${counts.pinches}件、計${Math.round((Date.now() - started) / 1000)}秒`,
      );
      const report = [...problems.entries()].map(([problem, path]) => `${problem} ← ${path}`);
      expect(report, `${width} / ${phase} の違反`).toEqual([]);
      await context.close();
    });
  }
}
