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

  // モック応答の2候補（北・南方向）が候補タブに表示されることを確認する。候補は
  // 「ルート結果」のタブ（Radix Tabs.Trigger、role=tab）で、ラベルは順位番号付きの
  // 「1. 北方向 20.3 km」形式（page.tsx参照）。
  await expect(page.getByRole("tab", { name: /1\. 北方向 20\.3 km/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /2\. 南方向 19\.8 km/ })).toBeVisible();
});

test("地図レイヤーのON/OFF切替", async ({ page }) => {
  await page.goto("/");

  // 地図上のレイヤーチップ（MapOverlayControls）。「道路情報」は改善計画T165で
  // 「道路種別」「路面」の2チップへ論理分割され、当初はT166で「観測」グループの
  // 折りたたみ配下へ格納されたが、T406/T418のグループ再編で「観測/推定/動的」の
  // 3グループは「道路/環境/スポット」の3グループへ置き換わった（`MapOverlayGroup`型、
  // frontend/src/components/Map/mapLayers.ts参照）。「道路種別」は「道路」グループ配下
  // のため、まず「道路」グループ見出しを展開してから、道路種別チップを1回押して
  // 押下状態（aria-pressed）が反転することを確認する。サイドバー（MapLayersPanel）側にも
  // 同名のチップ（aria-label="道路の種類レイヤーを表示"）があるため、完全一致で
  // 地図上のチップだけに絞り込む。
  await page.getByRole("button", { name: "道路", exact: true }).click();

  const roadTypeChip = page.getByRole("button", { name: "道路種別", exact: true });
  await expect(roadTypeChip).toBeVisible();

  const initiallyOn = (await roadTypeChip.getAttribute("aria-pressed")) === "true";
  await roadTypeChip.click();
  await expect(roadTypeChip).toHaveAttribute("aria-pressed", String(!initiallyOn));
});
