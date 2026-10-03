import { test } from "@playwright/test";
import { pathToFileURL } from "node:url";
import { screenContext, type ScreenScript } from "./screen";

// 脚本で進めた画面を撮る段。入口は scripts/capture-screen.mjs で、引数はそこが CAPTURE_OPTIONS に詰めて渡す。

interface CaptureOptions {
  script: string;
  out: string;
  viewport: { width: number; height: number };
  theme: "light" | "dark" | null;
}

const options = JSON.parse(process.env.CAPTURE_OPTIONS ?? "null") as CaptureOptions;

test("画面を撮る", async ({ page }) => {
  test.skip(!options, "CAPTURE_OPTIONS が無い（scripts/capture-screen.mjs から起こす）");
  await page.setViewportSize(options.viewport);
  if (options.theme) await page.emulateMedia({ colorScheme: options.theme });
  // package.json に "type": "module" が無いので、Playwright は .ts の脚本を CommonJS へ変えて読み、import() の default は
  // module.exports（その default が脚本の関数）になる。.mjs の脚本は default がそのまま関数。
  const loaded = (await import(pathToFileURL(options.script).href)).default as ScreenScript | { default: ScreenScript };
  const script = typeof loaded === "function" ? loaded : loaded.default;
  await script(screenContext(page, options.out));
});
