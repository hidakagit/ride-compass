import { expect, test } from "@playwright/test";
import { installApiMocks } from "./fixtures";

// クリティカルパスのみを対象にしたスモークテスト（改善計画「別の切り口」対応）。
// 目的は「地図UI変更は必ずPlaywrightで実機確認する」（過去のレビューで得た教訓）を
// 都度の手動実行から自動回帰検知へ移すこと。バックエンド・外部APIはモック
// （e2e/fixtures.ts）で置き換え、フロントの画面挙動だけを決定的に検証する。

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test("ルート生成→候補一覧の表示", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel("距離").fill("20");
  await page.getByRole("button", { name: "ルート生成" }).click();

  // モック応答の2候補（北・南方向）が一覧に表示されることを確認する。
  await expect(page.getByRole("button", { name: /北方向 — 20\.3 km/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /南方向 — 19\.8 km/ })).toBeVisible();
});

test("地図レイヤーのON/OFF切替", async ({ page }) => {
  await page.goto("/");

  // 地図上のレイヤーチップ（MapOverlayControls）。「道路情報」レイヤーのチップを
  // 1回押して、押下状態（aria-pressed）が反転することを確認する。サイドバー
  // （MapLayersPanel）側にも同名のチップ（aria-label="道路情報レイヤーを表示"）が
  // あるため、完全一致で地図上のチップだけに絞り込む。
  const roadChip = page.getByRole("button", { name: "道路情報", exact: true });
  await expect(roadChip).toBeVisible();

  const initiallyOn = (await roadChip.getAttribute("aria-pressed")) === "true";
  await roadChip.click();
  await expect(roadChip).toHaveAttribute("aria-pressed", String(!initiallyOn));
});
