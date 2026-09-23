import type { CDPSession, Page } from "@playwright/test";

// 1つの画面状態に当てる走査（パターン4 観点1〜3）。どれも「画面に在るもの全部」を性質で集め、
// 違反を文字列の配列で返す（空なら違反なし）。どの状態に当てるかは states.ts が決める。

/** 観点1: 押せる部品が画面の横幅からはみ出していないか、ページが横にスクロールしないか。 */
export async function scanLayout(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const problems: string[] = [];
    const root = document.scrollingElement ?? document.documentElement;
    if (root.scrollWidth > window.innerWidth + 1) {
      problems.push(`ページが横にスクロールする（幅${root.scrollWidth}px > 画面${window.innerWidth}px）`);
    }
    const interactive =
      'button, a[href], input:not([type="hidden"]), select, textarea, summary, [role="tab"], [role="checkbox"], [role="radio"], [role="switch"], [role="menuitem"], [role="slider"]';
    for (const element of document.querySelectorAll<HTMLElement>(interactive)) {
      const box = element.getBoundingClientRect();
      if (box.width === 0 || box.height === 0 || !element.checkVisibility({ visibilityProperty: true })) continue;
      // 横スクロールする容器の中は、はみ出していてもスクロールで届く。
      let scroller: Element | null = element.parentElement;
      let insideScroller = false;
      while (scroller) {
        const overflowX = getComputedStyle(scroller).overflowX;
        if (overflowX === "auto" || overflowX === "scroll") {
          insideScroller = true;
          break;
        }
        scroller = scroller.parentElement;
      }
      if (insideScroller) continue;
      if (box.left < -1 || box.right > window.innerWidth + 1) {
        const name = element.getAttribute("aria-label") ?? element.textContent?.trim().slice(0, 20) ?? "";
        problems.push(
          `${element.tagName.toLowerCase()} "${name}" が画面の横からはみ出す（${Math.round(box.left)}〜${Math.round(box.right)}px）`,
        );
      }
    }
    return problems;
  });
}

/** Tailwindの余白ユーティリティ（`p-2`・`px-[0.9rem]`・`-mt-1`等）。変種（`sm:`・`hover:`）付きは対象外。 */
const SPACING_UTILITY = /^(-?)([pm])([xytrblse]?)-(\d+(?:\.\d+)?|\[[^\]]+\])$/;

const SIDES: Record<string, readonly string[]> = {
  "": ["top", "right", "bottom", "left"],
  x: ["right", "left"],
  y: ["top", "bottom"],
  t: ["top"],
  r: ["right"],
  b: ["bottom"],
  l: ["left"],
  s: ["left"],
  e: ["right"],
};

/**
 * 観点3: Tailwindの余白ユーティリティが、globals.cssのリセットに潰されていないか。
 * リセット（`* { padding: 0; margin: 0 }`・`button`の既定の余白）は`@layer base`に置かれ、
 * Tailwindの`@layer utilities`に負ける。リセットが層の外へ出ると、詳細度に関係なくユーティリティを
 * 潰す（層の外のルールは、どの層のルールより強い）。期待値は同じ親に置いた試し要素へ
 * そのユーティリティの値を`!important`で与え、ブラウザに計算させる。
 */
export async function scanSpacingUtilities(page: Page): Promise<{ checked: number; problems: string[] }> {
  return page.evaluate(
    ({ pattern, sides }) => {
      const utility = new RegExp(pattern);
      let checked = 0;
      const problems: string[] = [];
      for (const element of document.querySelectorAll<HTMLElement>("body *")) {
        for (const token of element.classList) {
          const match = utility.exec(token);
          if (!match) continue;
          const [, negative, kind, axis, amount] = match;
          const property = kind === "p" ? "padding" : "margin";
          const length = amount.startsWith("[")
            ? amount.slice(1, -1).replaceAll("_", " ")
            : `calc(var(--spacing) * ${amount})`;
          const probe = document.createElement("div");
          probe.style.position = "absolute";
          probe.style.visibility = "hidden";
          probe.style.setProperty(`${property}-left`, negative ? `calc(${length} * -1)` : length, "important");
          element.parentElement?.appendChild(probe);
          const expected = getComputedStyle(probe).getPropertyValue(`${property}-left`);
          probe.remove();
          const computed = getComputedStyle(element);
          for (const side of sides[axis]) {
            const actual = computed.getPropertyValue(`${property}-${side}`);
            if (actual !== expected) {
              const name = (element.textContent ?? "").trim().slice(0, 20);
              problems.push(
                `${element.tagName.toLowerCase()} "${name}" の ${token}（${side}）が ${actual}（本来 ${expected}）`,
              );
            }
          }
          checked += 1;
        }
      }
      return { checked, problems };
    },
    { pattern: SPACING_UTILITY.source, sides: SIDES },
  );
}

/** 2本の指を(x, y)の左右に置き、外へ開く。Input.synthesizePinchGestureはページの拡大を再現しない
 * （docs/conventions/testing.md パターン4）。 */
export async function pinchOpen(client: CDPSession, x: number, y: number): Promise<void> {
  const fingers = (spread: number) => [
    { x: x - 2 - spread, y, id: 1 },
    { x: x + 2 + spread, y, id: 2 },
  ];
  await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: fingers(0) });
  for (let step = 1; step <= 12; step += 1) {
    await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: fingers(step * 8) });
  }
  await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
}

export interface PinchTarget {
  x: number;
  y: number;
  label: string;
}

/** 画面を8px格子で走査し、最前面に当たった地図のcanvas以外の部品（押せる要素ごとに1点）。 */
export async function pinchTargets(page: Page): Promise<PinchTarget[]> {
  return page.evaluate(() => {
    const canvas = document.querySelector("canvas.maplibregl-canvas");
    const found = new Map<Element, { x: number; y: number; label: string }>();
    for (let y = 4; y < window.innerHeight; y += 8) {
      for (let x = 4; x < window.innerWidth; x += 8) {
        const element = document.elementFromPoint(x, y);
        if (!element || element === canvas) continue;
        const owner = element.closest("button, a, [role], label, input") ?? element;
        if (found.has(owner)) continue;
        const box = owner.getBoundingClientRect();
        const center = { x: box.left + box.width / 2, y: box.top + box.height / 2 };
        const hit = document.elementFromPoint(center.x, center.y);
        const point = hit && owner.contains(hit) ? center : { x, y };
        const name = owner.getAttribute("aria-label") ?? owner.textContent?.trim().slice(0, 16) ?? "";
        found.set(owner, { ...point, label: `${owner.tagName.toLowerCase()} "${name}"` });
      }
    }
    return [...found.values()];
  });
}

/**
 * 観点2: 地図のcanvas以外の部品から始めたピンチが、ページ全体の拡大にならないか（地図の上の
 * ピンチが地図を拡大することは map-runtime.spec.ts が見る）。
 * 拡大したら倍率を戻す（戻らなければ座標がずれるので、残りは未検査として打ち切る）。
 */
export async function scanPinch(page: Page, client: CDPSession): Promise<{ checked: number; problems: string[] }> {
  const targets = await pinchTargets(page);
  const problems: string[] = [];
  for (const [index, target] of targets.entries()) {
    await pinchOpen(client, target.x, target.y);
    await page.waitForTimeout(200);
    const scale = await page.evaluate(() => window.visualViewport?.scale ?? 1);
    if (scale === 1) continue;
    problems.push(`${target.label} (${Math.round(target.x)},${Math.round(target.y)}) → ×${scale.toFixed(2)}`);
    await client.send("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });
    await page.waitForTimeout(200);
    if ((await page.evaluate(() => window.visualViewport?.scale ?? 1)) !== 1) {
      problems.push(`（倍率を戻せないため、残り${targets.length - index - 1}件は未検査）`);
      break;
    }
  }
  return { checked: targets.length, problems };
}
