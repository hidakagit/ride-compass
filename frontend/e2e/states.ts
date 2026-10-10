import { expect, type Page } from "@playwright/test";
import { catalogEntry } from "@/testing/catalogAxes";
import { makeRouteCandidate, routeThrough, type Places } from "@/testing/routeFixtures";
import {
  MOBILE_VIEWPORT,
  axisCatalogFixture,
  clickMap,
  defaultAxisCatalogFixture,
  doneJobFixture,
  openMobileSheet,
  routeGenerateResponseFixture,
  runGeneration,
} from "./fixtures";

// 走査する画面の状態（.claude/rules/testing-e2e.md パターン4）。土台は幅 × 段階（ルートの生成前・生成後・区間を乗り換えた後）。
// 土台の上では、画面がARIAで宣言している開閉の部品（`aria-expanded`・`role="tab"`）のうち、最前面で
// 押せるものを押せる限り辿る。どの状態へも1回だけ入る: 幅 × 段階ごとに1枚のページで辿り、開いたものは閉じて戻す。

export const WIDTHS = {
  mobile: MOBILE_VIEWPORT,
  desktop: { width: 1280, height: 800 },
} as const;
export type WidthName = keyof typeof WIDTHS;

/** アプリの段階。ルートを生成する前と後、区間を乗り換えた後で、画面に出る部品の集合が入れ替わる。 */
export const PHASES = ["生成前", "生成後", "乗り換え後"] as const;

/** 幅の分岐はCSSのブレークポイント1つだけで、WIDTHSはその両側に1つずつ置く。 */
export async function assertWidthsStraddleBreakpoint(page: Page): Promise<void> {
  const breakpoint = await page.evaluate(() =>
    Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--breakpoint-mobile")),
  );
  expect(breakpoint, "--breakpoint-mobile が読めない").toBeGreaterThan(0);
  expect(WIDTHS.mobile.width).toBeLessThanOrEqual(breakpoint);
  expect(WIDTHS.desktop.width).toBeGreaterThan(breakpoint);
}

interface Opener {
  id: number;
  label: string;
  /** 同じタブ列のタブ（同時に1つしか選べない兄弟）。開閉の部品はnull。 */
  group: number | null;
  /** タブ列で押す前に選ばれていたタブ。 */
  restoreId: number | null;
}
interface Spot {
  x: number;
  y: number;
  pressable: boolean;
}

interface PageHelpers {
  /** 部品の見分け: 要素から祖先（htmlの手前）までの、タグと並べ替えたクラスの並び。同じ並びには同じCSSの規則が当たる。 */
  componentKey(el: Element): string;
  /** 部品の検査を段階ごとに1回にする。その段階でkindについて初めて見る部品ならtrue（見たことを記録する）。 */
  firstInPhase(kind: string, key: string): boolean;
  resetPhase(): void;
  fingerprint(): string;
  snapshot(skipKeys: string[]): { fp: string; present: string[]; openers: Opener[] };
  center(id: number): Spot | null;
  settle(): Promise<{ ok: boolean; fp: string }>;
  stableScale(): Promise<number>;
  /** 検査のタッチが画面の状態を変えないようにする。(x, y)の入力欄の値を覚え、アプリへのタッチ・ポインタ・入力の
   * イベントを止める（ページの拡大はブラウザが`touch-action`で決めるので、止めても変わらない）。 */
  isolate(x: number, y: number): void;
  /** isolateをやめ、覚えた入力欄の値を戻す（ブラウザの既定の動きでスライダーのつまみが動くため）。 */
  release(): void;
}

declare global {
  interface Window {
    __e2e: PageHelpers;
  }
}

/** ページが読み込まれる前に入れる補助（`page.addInitScript`へ渡す。ブラウザの中で動く）。 */
export function installPageHelpers(): void {
  const OPENER = '[aria-expanded="false"], [role="tab"][aria-selected="false"]';
  const SWITCH = '[aria-expanded], [role="tab"]';

  // 落ち着きの判定で待つ通信は、メインスレッドのfetch・XHRだけ（地図のタイルはWorkerの中で取るので、この包みは及ばない）。
  let inflight = 0;
  const originalFetch = window.fetch;
  window.fetch = function (...args: Parameters<typeof fetch>) {
    inflight += 1;
    return originalFetch.apply(this, args).finally(() => (inflight -= 1));
  };
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args: Parameters<XMLHttpRequest["send"]>) {
    inflight += 1;
    this.addEventListener("loadend", () => (inflight -= 1), { once: true });
    return originalSend.apply(this, args);
  };
  let mutations = 0;
  new MutationObserver((records) => (mutations += records.length)).observe(document, {
    subtree: true,
    childList: true,
    attributes: true,
    characterData: true,
  });

  const ids = new WeakMap<Element, number>();
  const nodes = new Map<number, Element>();
  let next = 1;
  const id = (el: Element) => {
    let n = ids.get(el);
    if (!n) {
      n = next++;
      ids.set(el, n);
      nodes.set(n, el);
    }
    return n;
  };
  const seen = new Map<string, Set<string>>();
  const visible = (el: Element) => {
    const box = el.getBoundingClientRect();
    return box.width > 0 && box.height > 0 && el.checkVisibility({ visibilityProperty: true });
  };
  const componentKey = (el: Element) => {
    const parts: string[] = [];
    for (let e: Element | null = el; e && e !== document.documentElement; e = e.parentElement) {
      parts.push(
        e.tagName.toLowerCase() +
          [...e.classList]
            .sort()
            .map((c) => `.${c}`)
            .join(""),
      );
    }
    return parts.join("<");
  };
  // 同じタブ列のタブは見分けが同じになり、選ばれたタブが移っても多重集合は変わらないので、列の中の位置を添える。
  const switchKey = (el: Element) => {
    if (el.getAttribute("role") !== "tab") return componentKey(el);
    const tabs = [...(el.closest('[role="tablist"]')?.querySelectorAll('[role="tab"]') ?? [])];
    return `${componentKey(el)}#${tabs.indexOf(el)}`;
  };
  // 指紋: 開閉の値を部品の見分けごとに集めたもの（同じ部品が複数あれば多重集合）と倍率。localStorageは入れない
  // ——辿る間にページを読み直さないので、保存値はアプリの状態を通してしか画面に効かず、それは開閉の値で読める。
  const fingerprint = () =>
    [
      ...[...document.querySelectorAll(SWITCH)]
        .map((el) => `${switchKey(el)} = ${el.getAttribute("aria-expanded")}/${el.getAttribute("aria-selected")}`)
        .sort(),
      `倍率 ${window.visualViewport?.scale ?? 1}`,
    ].join("\n");
  const frame = () => new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  // アプリより先に入れるので、windowの捕捉の段でアプリのどの受け口よりも先に呼ばれる。
  let held: { input: HTMLInputElement; value: string } | null = null;
  let isolating = false;
  for (const type of [
    "touchstart",
    "touchmove",
    "touchend",
    "touchcancel",
    "pointerdown",
    "pointermove",
    "pointerup",
    "pointercancel",
    "input",
    "change",
  ]) {
    window.addEventListener(type, (event) => isolating && event.stopImmediatePropagation(), {
      capture: true,
      passive: true,
    });
  }

  window.__e2e = {
    componentKey,
    firstInPhase(kind, key) {
      const keys = seen.get(kind) ?? new Set<string>();
      seen.set(kind, keys);
      if (keys.has(key)) return false;
      keys.add(key);
      return true;
    },
    resetPhase() {
      seen.clear();
    },
    fingerprint,
    snapshot(skipKeys) {
      const skip = new Set(skipKeys);
      const present = [...new Set([...document.querySelectorAll(SWITCH)].filter(visible).map(componentKey))];
      const openers: Opener[] = [];
      for (const el of document.querySelectorAll(OPENER)) {
        if (!visible(el) || skip.has(componentKey(el))) continue;
        let group: number | null = null;
        let restoreId: number | null = null;
        if (el.getAttribute("role") === "tab") {
          const list = el.closest('[role="tablist"]');
          group = list ? id(list) : null;
          const selected = list?.querySelector('[role="tab"][aria-selected="true"]');
          restoreId = selected ? id(selected) : null;
        }
        const name = (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 30);
        openers.push({
          id: id(el),
          label: `${el.getAttribute("role") ?? el.tagName.toLowerCase()} "${name}"`,
          group,
          restoreId,
        });
      }
      return { fp: fingerprint(), present, openers };
    },
    // 押せる: 中心点（Playwrightが押す点と同じ）が画面内にあり、そこでのヒットテストが部品自身か子孫を返す。
    center(n) {
      const el = nodes.get(n);
      if (!el || !el.isConnected) return null;
      const box = el.getBoundingClientRect();
      const x = box.left + box.width / 2;
      const y = box.top + box.height / 2;
      const inside = x >= 0 && y >= 0 && x < window.innerWidth && y < window.innerHeight;
      const hit = inside ? document.elementFromPoint(x, y) : null;
      return { x, y, pressable: !!hit && el.contains(hit) };
    },
    // 落ち着いた: メインスレッドの通信0件・実行中のアニメーション0件・1フレームの間のDOMの変化0件・指紋が前の
    // フレームと同じ。
    async settle() {
      const deadline = performance.now() + 15_000;
      let previous = "";
      while (performance.now() < deadline) {
        mutations = 0;
        await frame();
        const running = document.getAnimations().filter((a) => a.playState === "running").length;
        const current = fingerprint();
        if (current === previous && running === 0 && inflight === 0 && mutations === 0)
          return { ok: true, fp: current };
        previous = current;
      }
      return { ok: false, fp: fingerprint() };
    },
    async stableScale() {
      let previous = -1;
      for (let i = 0; i < 60; i += 1) {
        await frame();
        const scale = window.visualViewport?.scale ?? 1;
        if (scale === previous) return scale;
        previous = scale;
      }
      return previous;
    },
    isolate(x, y) {
      const hit = document.elementFromPoint(x, y);
      held = hit instanceof HTMLInputElement ? { input: hit, value: hit.value } : null;
      isolating = true;
    },
    release() {
      isolating = false;
      if (held) held.input.value = held.value;
      held = null;
    },
  };
}

async function settle(page: Page): Promise<string> {
  const settled = await page.evaluate(() => window.__e2e.settle());
  expect(settled.ok, "15秒たっても画面が落ち着かない").toBe(true);
  return settled.fp;
}

/** 画面を開き、基本の状態（シート・パネルを開いていない）で落ち着くまで待つ。 */
export async function openApp(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "メニュー" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 15_000 });
  await settle(page);
}

/** ルートを1回生成し、基本の状態へ戻して落ち着くまで待つ。 */
export async function generate(page: Page, width: WidthName): Promise<void> {
  if (width === "mobile") {
    const sheet = await openMobileSheet(page, "ルート設定");
    await runGeneration(sheet);
    await page.getByRole("button", { name: "ルート設定", exact: true }).click();
    await expect(sheet).toBeHidden();
  } else {
    await runGeneration(page);
  }
  await settle(page);
}

// 乗り換え後の段階の段取り。目的地へ向かう2候補が途中の1区間だけ別の道（N1 → VIA → N2）を通り、その区間が乗り換え先になる。
// 地点は出発地（installApiMocks の現在地）の近くに置く。
const API_BASE = "http://localhost:8000";
const SPLICE_PLACES: Places = {
  S: [139.7387, 35.7597],
  N1: [139.7406, 35.7604],
  VIA: [139.7421, 35.7634],
  N2: [139.7436, 35.7613],
  D: [139.7466, 35.7622],
};

/**
 * 走査の軸カタログ。アプリを開く前に入れる。本番と同じく重みのある軸を3つ持つ（重みのある軸が2つ以上のときだけ
 * 出る部品があり、既定の1軸では走査に入らない）。乗り換えの入口が出るように、区間を割る下限の較正値を持つ。
 */
export async function installScanMocks(page: Page): Promise<void> {
  const catalog = axisCatalogFixture([
    ...defaultAxisCatalogFixture().axes,
    ...["first", "second", "third"].map((axisId) => ({ ...catalogEntry({ axis_id: axisId }), default_weight: 1 / 3 })),
  ]);
  catalog.client_tuning = { "splice.min_stretch_km": 0 };
  await page.route(`${API_BASE}/api/axis-catalog*`, (route) => route.fulfill({ json: catalog }));
}

/**
 * 地図が見えている点（浮いた部品・シート・案内に覆われていない点）のうち真ん中に近い所へ、経度・緯度の点を寄せてから押す
 * （地図は生成した候補へ寄るので、そのままでは点が画面の外や部品の下に来うる）。
 */
export async function clickVisible(page: Page, lngLat: readonly [number, number]): Promise<void> {
  await page.evaluate(
    (center) => {
      const map = window.__liveMap();
      const canvas = map.getCanvas();
      const box = canvas.getBoundingClientRect();
      const middle = { x: box.left + box.width / 2, y: box.top + box.height / 2 };
      let best: { x: number; y: number } | null = null;
      for (let y = box.top + 20; y < Math.min(box.bottom, window.innerHeight) - 20; y += 20) {
        for (let x = box.left + 20; x < Math.min(box.right, window.innerWidth) - 20; x += 20) {
          if (document.elementFromPoint(x, y) !== canvas) continue;
          if (!best || Math.hypot(x - middle.x, y - middle.y) < Math.hypot(best.x - middle.x, best.y - middle.y))
            best = { x, y };
        }
      }
      if (!best) throw new Error("地図の見えている所が無い");
      map.easeTo({ center, zoom: 16, offset: [best.x - middle.x, best.y - middle.y], duration: 0 });
    },
    lngLat as [number, number],
  );
  await settle(page);
  await clickMap(page, lngLat as [number, number]);
}

/** 目的地モードで2候補を生成し、1つ目の候補で合成を始めて乗り換え先を1つ押し、基本の状態へ戻して落ち着くまで待つ。 */
export async function splice(page: Page, width: WidthName): Promise<void> {
  const result = routeGenerateResponseFixture();
  result.routes = [
    makeRouteCandidate({
      ...routeThrough(SPLICE_PLACES, ["S", "N1", "N2", "D"]),
      id: "route-1",
      kind: "destination",
      spliceable: true,
      distance_km: 3.1,
    }),
    makeRouteCandidate({
      ...routeThrough(SPLICE_PLACES, ["S", "N1", "VIA", "N2", "D"]),
      id: "route-2",
      kind: "destination",
      spliceable: true,
      distance_km: 3.6,
    }),
  ];
  await page.route(`${API_BASE}/api/routes/generate/*`, (route) => route.fulfill({ json: doneJobFixture(result) }));
  const scope = width === "mobile" ? await openMobileSheet(page, "ルート設定") : page;
  await scope.getByRole("radio", { name: "目的地" }).click();
  // スマホ幅は、シートを閉じると目的地の指定が外れるので、開いたまま見えている地図を押す。
  await clickVisible(page, SPLICE_PLACES.D);
  await expect(scope.getByRole("button", { name: "目的地を地図で置き直す" })).toBeVisible();
  await runGeneration(scope);
  if (width === "mobile") {
    await page.getByRole("button", { name: "ルート設定", exact: true }).click();
    const sheet = await openMobileSheet(page, "ルート結果");
    await sheet.getByRole("button", { name: "ルートを合成" }).first().click();
    await page.getByRole("button", { name: "ルート結果", exact: true }).click();
    await expect(sheet).toBeHidden();
  } else {
    await page.getByRole("button", { name: "ルートを合成" }).first().click();
  }
  await settle(page);
  await clickVisible(page, SPLICE_PLACES.VIA);
  await settle(page);
  if (width === "mobile") {
    const sheet = await openMobileSheet(page, "ルート結果");
    await expect(sheet.getByText("1回")).toBeVisible();
    await page.getByRole("button", { name: "ルート結果", exact: true }).click();
    await expect(sheet).toBeHidden();
  } else {
    await expect(page.getByText("1回")).toBeVisible();
  }
  await settle(page);
}

/** 部品の検査の「段階ごとに1回」を始め直す。 */
export async function resetPhase(page: Page): Promise<void> {
  await page.evaluate(() => window.__e2e.resetPhase());
}

/** 2つの指紋の違い（消えた行・増えた行）。部品の見分けは末尾の2段だけ出す。 */
function describeDiff(before: string, after: string): string {
  const count = (fp: string) => {
    const lines = new Map<string, number>();
    for (const line of fp.split("\n")) lines.set(line, (lines.get(line) ?? 0) + 1);
    return lines;
  };
  const a = count(before);
  const b = count(after);
  const short = (line: string) => {
    const [key, value] = line.split(" = ");
    return value === undefined ? line : `${key.split("<").slice(0, 2).join("<")} = ${value}`;
  };
  const lost = [...a].filter(([line, n]) => (b.get(line) ?? 0) < n).map(([line]) => short(line));
  const gained = [...b].filter(([line, n]) => (a.get(line) ?? 0) < n).map(([line]) => short(line));
  return `消えた ${lost.slice(0, 3).join(" | ")} ／ 増えた ${gained.slice(0, 3).join(" | ")}`;
}

export interface TraverseResult {
  /** 検査した状態の数（土台を含む）。 */
  states: number;
  problems: string[];
}

/**
 * 土台から開閉の部品を辿り、各状態で`inspect`を呼ぶ。祖先の状態にあった部品（部品の見分けが同じもの）は押さない。
 * 同じタブ列のタブは戻らずに次へ渡り、最後に元のタブへ戻す。閉じたあと指紋が押す前と一致しなければ違反にする。
 */
export async function traverse(
  page: Page,
  root: string,
  inspect: (path: string) => Promise<void>,
): Promise<TraverseResult> {
  const problems: string[] = [];
  let states = 0;
  const press = async (spot: Spot) => {
    await page.mouse.click(spot.x, spot.y);
    return settle(page);
  };
  const center = (n: number) => page.evaluate((n) => window.__e2e.center(n), n);

  const visit = async (path: string, ancestors: string[], entered: string) => {
    states += 1;
    await inspect(path);
    const snap = await page.evaluate((skip) => window.__e2e.snapshot(skip), ancestors);
    if (snap.fp !== entered) problems.push(`検査の操作で状態が変わった: ${path}（${describeDiff(entered, snap.fp)}）`);
    const base = snap.fp;
    const next = [...ancestors, ...snap.present];
    const groups = new Map<number, Opener[]>();
    for (const opener of snap.openers) {
      if (opener.group !== null) groups.set(opener.group, [...(groups.get(opener.group) ?? []), opener]);
    }

    for (const opener of snap.openers.filter((o) => o.group === null)) {
      const spot = await center(opener.id);
      if (!spot?.pressable) continue;
      const opened = await press(spot);
      if (opened === base) continue;
      await visit(`${path} > ${opener.label}`, next, opened);
      const self = await center(opener.id);
      let back: string;
      if (self?.pressable) back = await press(self);
      else {
        await page.keyboard.press("Escape");
        back = await settle(page);
      }
      if (back !== base)
        problems.push(`閉じても元に戻らない: ${path} > ${opener.label}（${describeDiff(base, back)}）`);
    }

    for (const members of groups.values()) {
      let current = base;
      let moved = false;
      for (const member of members) {
        const spot = await center(member.id);
        if (!spot?.pressable) continue;
        const opened = await press(spot);
        if (opened === current) continue;
        moved = true;
        await visit(`${path} > ${member.label}`, next, opened);
        current = opened;
      }
      const restoreId = members[0].restoreId;
      if (!moved) continue;
      if (restoreId === null) {
        problems.push(`選ばれていたタブが無く、タブ列を元へ戻せない: ${path}`);
        continue;
      }
      const spot = await center(restoreId);
      let back: string;
      if (spot?.pressable) back = await press(spot);
      else {
        await page.keyboard.press("Escape");
        back = await settle(page);
      }
      if (back !== base) problems.push(`元のタブへ戻せない: ${path}（${describeDiff(base, back)}）`);
    }
  };

  await visit(root, [], await page.evaluate(() => window.__e2e.fingerprint()));
  return { states, problems };
}
