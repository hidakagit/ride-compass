import { test } from "@playwright/test";
import { MOBILE_VIEWPORT, openMobileApp } from "./fixtures";

const OUT = process.env.SHOT_DIR ?? ".";

test("走行条件アイコンのポップオーバーをスマホ幅で見る", async ({ page }) => {
  await openMobileApp(page);

  await page.getByRole("button", { name: /出発時刻:/ }).click();
  const timeline = page.locator('[class*="timelinePopover"]');
  await timeline.waitFor();
  const box = await timeline.boundingBox();
  console.log("TIMELINE_BOX", JSON.stringify(box), "viewport", MOBILE_VIEWPORT.width);
  await page.screenshot({ path: `${OUT}/before-departure.png` });
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: /想定速度:/ }).click();
  const speed = page.locator('[class*="RideConditionBar_popover"]');
  await speed.waitFor();
  console.log("SPEED_BOX", JSON.stringify(await speed.boundingBox()));
  await page.screenshot({ path: `${OUT}/before-speed.png` });
});
