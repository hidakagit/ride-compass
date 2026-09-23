import type { CDPSession, Page } from "@playwright/test";

// 1つの画面状態に当てる走査（パターン4 観点1〜3）。どれも「画面に在るもの全部」を性質で集め、
// 違反を文字列の配列で返す（空なら違反なし）。どの状態に当てるかは states.ts が決める。
// 判定が読むものから2種類に分かれる:
// - 配置の検査（座標・寸法を読む。何が開いているかで変わる）: 状態ごとに当てる
// - 部品の検査（要素と祖先の計算後のスタイルで決まる）: 段階ごとに各部品1回（window.__e2e.firstInPhase）

/**
 * 操作できる部品のロール。WAI-ARIA 1.2「5.3.2 Widget Roles」（https://www.w3.org/TR/wai-aria-1.2/#widget_roles）の
 * 単独の部品とまとめ役の部品。separatorはフォーカスできるときだけ部品に当たる（同節）。
 */
const WIDGET_ROLES = new Set([
  "button",
  "checkbox",
  "gridcell",
  "link",
  "menuitem",
  "menuitemcheckbox",
  "menuitemradio",
  "option",
  "progressbar",
  "radio",
  "scrollbar",
  "searchbox",
  "separator",
  "slider",
  "spinbutton",
  "switch",
  "tab",
  "tabpanel",
  "textbox",
  "treeitem",
  "combobox",
  "grid",
  "listbox",
  "menu",
  "menubar",
  "radiogroup",
  "tablist",
  "tree",
  "treegrid",
]);

interface AXNode {
  ignored: boolean;
  role?: { value?: string };
  backendDOMNodeId?: number;
  properties?: { name: string; value: { value?: unknown } }[];
}

/**
 * 観点1（配置の検査）: ページが横にスクロールしないこと、操作できる部品が画面の横幅からはみ出さないこと。
 * 部品はブラウザが計算したロール（アクセシビリティツリー）で決める。部品が横スクロールする容器（祖先の計算後の
 * `overflow-x`が`auto`・`scroll`。縦にスクロールする容器も計算後は`auto`になる）の中にあれば、容器を
 * スクロールすれば届くので、部品の代わりに最も近いその容器が画面の横幅に収まるかを見る（件数は`viaContainer`）。
 * `resolved`は解決済みのノードの使い回し（同じページの間だけ有効）。
 */
export async function scanLayout(
  page: Page,
  client: CDPSession,
  resolved: Map<number, string>,
): Promise<{ checked: number; viaContainer: number; problems: string[] }> {
  const problems: string[] = [];
  const scroll = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    return root.scrollWidth > window.innerWidth + 1 ? root.scrollWidth : null;
  });
  if (scroll !== null) problems.push(`ページが横にスクロールする（幅${scroll}px）`);

  const { nodes } = (await client.send("Accessibility.getFullAXTree")) as { nodes: AXNode[] };
  const objectIds: string[] = [];
  for (const node of nodes) {
    const role = String(node.role?.value ?? "").toLowerCase();
    if (node.ignored || !node.backendDOMNodeId || !WIDGET_ROLES.has(role)) continue;
    if (role === "separator" && !node.properties?.some((p) => p.name === "focusable" && p.value.value === true))
      continue;
    let objectId = resolved.get(node.backendDOMNodeId);
    if (!objectId) {
      try {
        const { object } = (await client.send("DOM.resolveNode", { backendNodeId: node.backendDOMNodeId })) as {
          object: { objectId?: string };
        };
        objectId = object.objectId;
      } catch {
        continue;
      }
      if (!objectId) continue;
      resolved.set(node.backendDOMNodeId, objectId);
    }
    objectIds.push(objectId);
  }
  if (objectIds.length === 0) return { checked: 0, viaContainer: 0, problems };

  const { result } = (await client.send("Runtime.callFunctionOn", {
    objectId: objectIds[0],
    returnByValue: true,
    arguments: objectIds.map((objectId) => ({ objectId })),
    functionDeclaration: `function (...targets) {
      return targets.map((node) => {
        const el = node.nodeType === 1 ? node : node.parentElement;
        if (!el) return null;
        const box = el.getBoundingClientRect();
        if (box.width === 0 || box.height === 0 || !el.checkVisibility({ visibilityProperty: true })) return null;
        const describe = (e, b) => {
          const name = e.getAttribute("aria-label") ?? (e.textContent ?? "").trim().slice(0, 20);
          return e.tagName.toLowerCase() + ' "' + name + '"' + " が画面の横からはみ出す（" +
            Math.round(b.left) + "〜" + Math.round(b.right) + "px）";
        };
        const fits = (b) => b.left >= -1 && b.right <= window.innerWidth + 1;
        // ページ全体のスクロール要素まで来たら、部品自身で見る（ページの横スクロールは別に見ている）。
        for (let p = el.parentElement; p && p !== document.scrollingElement; p = p.parentElement) {
          const overflowX = getComputedStyle(p).overflowX;
          if (overflowX !== "auto" && overflowX !== "scroll") continue;
          const outer = p.getBoundingClientRect();
          return { via: true, problem: fits(outer) ? "" : "容器 " + describe(p, outer) };
        }
        return { via: false, problem: fits(box) ? "" : describe(el, box) };
      });
    }`,
  })) as { result: { value: ({ via: boolean; problem: string } | null)[] } };
  let checked = 0;
  let viaContainer = 0;
  for (const value of result.value) {
    if (value === null) continue;
    checked += 1;
    if (value.via) viaContainer += 1;
    if (value.problem !== "") problems.push(value.problem);
  }
  return { checked, viaContainer, problems };
}

/**
 * Tailwindの余白ユーティリティ（`p-2`・`px-[0.9rem]`・`-mt-1`等）。変種付き（`sm:`・`hover:`）は、今の画面で
 * その条件が成り立つかを判定しないので対象外。
 */
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
 * 観点3（部品の検査）: Tailwindの余白ユーティリティが、globals.cssのリセットに潰されていないか。
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
        if (![...element.classList].some((token) => utility.test(token))) continue;
        if (!window.__e2e.firstInPhase("spacing", window.__e2e.componentKey(element))) continue;
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

/**
 * 観点2（部品の検査）: 地図のcanvas以外の部品から始めたピンチが、ページ全体の拡大にならないか（地図の上の
 * ピンチが地図を拡大することは map-runtime.spec.ts が見る）。対象は、見えている要素の中心点で最前面になる要素
 * （指が実際に触れる要素）。指は1回の移動で画面の左右の端まで開く——ブラウザがピンチとして扱うかが見えれば足り、
 * 移動を分けても検知は変わらない。拡大したら倍率を戻す（戻らなければ座標がずれるので、残りは未検査として打ち切る）。
 */
export async function scanPinch(page: Page, client: CDPSession): Promise<{ checked: number; problems: string[] }> {
  const width = await page.evaluate(() => window.innerWidth);
  const targets = await page.evaluate(() => {
    const canvas = document.querySelector("canvas.maplibregl-canvas");
    const found: { x: number; y: number; label: string }[] = [];
    for (const el of document.querySelectorAll("body *")) {
      const box = el.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) continue;
      const x = box.left + box.width / 2;
      const y = box.top + box.height / 2;
      if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) continue;
      const hit = document.elementFromPoint(x, y);
      if (!hit || hit === canvas || !window.__e2e.firstInPhase("pinch", window.__e2e.componentKey(hit))) continue;
      const name = hit.getAttribute("aria-label") ?? (hit.textContent ?? "").trim().slice(0, 16);
      found.push({ x, y, label: `${hit.tagName.toLowerCase()} "${name}"` });
    }
    return found;
  });
  const problems: string[] = [];
  for (const [index, target] of targets.entries()) {
    await client.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [
        { x: target.x - 2, y: target.y, id: 1 },
        { x: target.x + 2, y: target.y, id: 2 },
      ],
    });
    await client.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [
        { x: 0, y: target.y, id: 1 },
        { x: width - 1, y: target.y, id: 2 },
      ],
    });
    await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    const scale = await page.evaluate(() => window.__e2e.stableScale());
    if (scale === 1) continue;
    problems.push(
      `${target.label} (${Math.round(target.x)},${Math.round(target.y)}) から始めたピンチでページが×${scale.toFixed(2)}に拡大した`,
    );
    await client.send("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });
    if ((await page.evaluate(() => window.__e2e.stableScale())) !== 1) {
      problems.push(`（倍率を戻せないため、残り${targets.length - index - 1}件は未検査）`);
      break;
    }
  }
  return { checked: targets.length, problems };
}
