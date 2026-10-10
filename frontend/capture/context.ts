import { expect, type Locator, type Page } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import path from "node:path";
import { mapDisplay } from "@/types/generated/mapDisplay";
import * as catalogAxes from "@/testing/catalogAxes";
import * as fixtures from "../e2e/fixtures";
import * as states from "../e2e/states";
import { LIVE_POINT, chooseLens, settleMap } from "../e2e-live/live";

// 脚本（scripts/capture.mjs の --script）が受け取る口。脚本はこの口だけを使い、何も読み込まない（型の読み込みは実行時に
// 消えるのでよい）。そのため作業ツリーの外に置いても、読み込みの解決に頼らずに動く。e2e の段取りと応答の雛形はモジュールごと
// 口に載せるので、そこへ足した関数は口を変えずに脚本から呼べる。

interface OpenOptions {
  /** 現在地（出発地）。既定は、モックなら e2e/fixtures.ts: installApiMocks の地点、本物の backend なら e2e-live/live.ts: LIVE_POINT。 */
  point?: { latitude: number; longitude: number };
  /** 開いたあとに寄せる地図の倍率。 */
  zoom?: number;
  /** ON にするレイヤーの id（mapDisplay.layers）。渡さないレイヤーは既定の表示のまま。 */
  layers?: string[];
  /** 開く前に入れる保存状態（localStorage）。 */
  storedState?: Record<string, string>;
  /** 開く前・モックの後に呼ぶ（後から登録したルートが先に当たるので、応答の上書きはここで足す）。 */
  routes?: (page: Page) => Promise<unknown>;
}

interface OpenAdminOptions {
  /** 選ぶタブの名前。既定は開いたときのタブ。 */
  tab?: string;
  /** 開く前・モックの後に呼ぶ。管理APIの応答（`/admin/api/…`）はここで page.route で足す（足さない管理APIは失敗の表示になる）。 */
  routes?: (page: Page) => Promise<unknown>;
}

export interface CaptureContext {
  page: Page;
  expect: typeof expect;
  /** e2e/fixtures.ts の段取りと応答（openMobileSheet・generateRoutes・doneJobFixture 等）。 */
  fixtures: typeof fixtures;
  /** e2e/states.ts の全状態の走査の段取り（installScanMocks・splice 等）。 */
  states: typeof states;
  /** src/testing/catalogAxes.ts の軸の雛形（catalogEntry・rampEntry 等）。モックの軸カタログを組むときに fixtures.axisCatalogFixture へ渡す。 */
  catalogAxes: typeof catalogAxes;
  /** アプリを開き、地図の全ソースの読み終わりまで待つ。初回の案内は閉じた状態で開く。 */
  open(options?: OpenOptions): Promise<void>;
  /**
   * 管理画面（/admin）を撮影用の資格情報で開き、タブを選んで、そのタブの中身を返す。応答はモックだけで開ける（本番と本物の
   * backend は撮影用の資格情報を通さない）。選べなければ、選べるタブを並べて止まる。
   */
  openAdmin(options?: OpenAdminOptions): Promise<Locator>;
  /** 地図の色分け（レンズ）を名前で選び、読み終わりまで待つ。選べなければ、選べる名前を並べて止まる。 */
  chooseLens(label: string): Promise<void>;
  /**
   * 「表示」の一覧の行の名前で凡例の内訳を開き、その内訳を返す。一覧が閉じていれば開く。`row` を渡せば、その行の説明も開く。
   * 開けなければ、選べる名前を並べて止まる。
   */
  openLegend(layer: string, row?: string): Promise<Locator>;
  /** 地図の上の経度・緯度の点を押す。その点が画面の外か、地図の上に別の部品が重なっていれば止める。 */
  clickMap(lngLat: [number, number]): Promise<void>;
  /** 地図の見えている所（部品に覆われていない所）へ経度・緯度の点を寄せてから押す。点が画面の外や部品の下に来うるときに使う。 */
  clickVisible(lngLat: [number, number]): Promise<void>;
  /**
   * 地図に描かれた、押すと開くもの（道の詳細・点の詳細・ルートの区間・乗り換えの帯等）を、経度・緯度を渡さずに1つ押す。
   * `target` は地図の当たり判定の対象の名前（例: "road"）で、いまの地図に無い名前を渡すと押せる名前を並べて止まる。持つレイヤーが
   * 非表示・画面に描かれていないときも止まるので、open の layers・位置・倍率で描かれる状態にしてから呼ぶ（例は examples/road-detail.ts）。
   */
  clickFeature(target: string): Promise<void>;
  /**
   * URL が glob に当たる応答の本文を `transform` の返した JSON に替える。本物の応答を取ってから本文だけを替えるので、CORS 等の
   * ヘッダーは本物のまま残る（ヘッダーの無い応答で返すと、別オリジンの backend への取得としてブラウザが捨てる）。
   * 本物の応答が失敗（本番の backend にまだ無い経路の 404 等）なら、`transform` に undefined を渡し、返した JSON を成功（200）の
   * 応答として CORS のヘッダーを付けて返す。新しい経路の応答も、作業ツリーの版を本番の backend へ向けたまま替えられる（例は examples/place-area.ts）。
   * open より前に呼ぶ（open が開くときに取る応答も替える）。
   * 本物の backend へ向けたときに使う（モックの応答を替えるなら open の routes で page.route を足す。例は examples/axis-catalog.ts）。
   * 本文を JSON として読み替えるだけなので、画像等の JSON でない応答は替えられない。作業ツリーの backend が変える、DB を読まない
   * 経路の応答は、scripts/capture.mjs の --backend で作業ツリーの backend に返させる（例は examples/jma-precipitation.ts）。
   */
  patch(glob: string, transform: (json: unknown) => unknown): Promise<void>;
  /** 地図の全ソースの読み終わりまで待つ。 */
  settle(): Promise<void>;
  /** 今の画面（`target` を渡せばその要素だけ）を撮り、書いたファイルを返す。 */
  shot(name: string, target?: Locator): Promise<string>;
  /**
   * スマホのキーボードが出た画面に見立てて撮り、書いたファイルを返す。`field`（打つ欄）がキーボードの上に隠れず見えるだけ画面を
   * 上へずらし、下からキーボードの高さを板で覆う。ページには何も足さず、撮った画像を組み直す（ページへ板を重ねると、
   * ヘッドレスの地図の描き直しが崩れて白く抜ける）。`height` はキーボードの高さ（CSS の px。既定は e2e/fixtures.ts: KEYBOARD_HEIGHT。
   * 候補の帯や Safari の入力の補助の帯が出る欄で見せたいときは、脚本が足す）。
   */
  shotWithKeyboard(name: string, field: Locator, options?: { height?: number }): Promise<string>;
}

export type CaptureScript = (context: CaptureContext) => Promise<void>;

export interface WorktreeBackend {
  /** 作業ツリーの backend（backend/scripts/serve_capture.py）のオリジン。 */
  origin: string;
  /** --api の backend のオリジン。 */
  api: string;
  /** 作業ツリーの backend に返させるパスの頭（scripts/capture.mjs の --backend）。 */
  paths: string[];
}

/**
 * 作業ツリーの backend の応答を待つ上限。気象庁のタイルの中継は気象庁への秒間上限を守って待つ（backend/app/config.py:
 * jma_tile_upstream_max_requests_per_second）ので、地図が一度に取るタイルの数だけ待ちが積もる。
 */
const WORKTREE_BACKEND_TIMEOUT_MS = 5 * 60_000;

/**
 * 撮った画像（PNG）の上を `shift` だけ切り落とし、下から `keyboard` の高さを板で覆った画像を、同じ寸法で組み直す。iOS の
 * Safari はキーボードが出てもレイアウトの寸法を変えず、見える範囲を欄が見えるだけずらすので、画面の中身は動かない。
 */
async function composeKeyboard(
  page: Page,
  image: Buffer,
  { width, height }: { width: number; height: number },
  { shift, keyboard }: { shift: number; keyboard: number },
): Promise<Buffer> {
  const sheet = await page.context().newPage();
  try {
    await sheet.setViewportSize({ width, height });
    await sheet.setContent(`<!doctype html>
<body style="margin:0;width:${width}px;height:${height}px;overflow:hidden;position:relative">
  <img src="data:image/png;base64,${image.toString("base64")}"
    style="position:absolute;left:0;top:${-shift}px;width:${width}px;height:${height}px">
  <div style="position:absolute;left:0;right:0;bottom:0;height:${keyboard}px;background:#9ca3af;color:#fff;
    display:flex;align-items:center;justify-content:center;font:20px sans-serif">キーボード（見立て）</div>
</body>`);
    await sheet.locator("img").evaluate((img: HTMLImageElement) => img.decode());
    return await sheet.screenshot();
  } finally {
    await sheet.close();
  }
}

/** 「表示」のボタンと、押すと開く一覧の名前（`MapOverlayControls`）。 */
const OVERLAY_LIST_NAME = "地図に出す情報";

/**
 * ブラウザが --api の backend へ選んだパスの頭で取りに行くものを、作業ツリーの backend から取って返す。page.route の
 * route.fetch は向け先のプロトコルを変えられない（本番の https から手元の http へ替えられない）ので、page.request で取る。
 * 脚本の routes・patch より先に登録する（後から登録したルートが先に当たる）。
 */
export async function routeToWorktreeBackend(page: Page, { origin, api, paths }: WorktreeBackend): Promise<void> {
  const apiOrigin = new URL(api).origin;
  await page.route(
    (url) => url.origin === apiOrigin && paths.some((head) => url.pathname.startsWith(head)),
    async (route) => {
      const url = new URL(route.request().url());
      const response = await page.request.get(`${origin}${url.pathname}${url.search}`, {
        timeout: WORKTREE_BACKEND_TIMEOUT_MS,
      });
      await route.fulfill({ response });
    },
  );
}

function fileName(name: string): string {
  return name.replace(/[\\/:*?"<>|\s]+/g, "_");
}

/** 選び損ねた直後に呼ぶので、選択肢が閉じていれば開く。 */
async function lensLabels(page: Page): Promise<string[]> {
  const group = page.getByRole("radiogroup", { name: "地図の色分け" });
  if (!(await group.isVisible())) await page.getByRole("button", { name: /^地図の色分け: / }).click();
  const labels = await group.getByRole("radio").allInnerTexts();
  return labels.map((label) => label.replace(/\s+/g, " ").trim());
}

async function ariaLabels(scope: Page | Locator, suffix: string): Promise<string[]> {
  const labels = await scope
    .getByRole("button", { name: new RegExp(`${suffix}$`) })
    .evaluateAll((buttons) => buttons.map((button) => button.getAttribute("aria-label") ?? ""));
  return labels.filter((label) => label.endsWith(suffix)).map((label) => label.slice(0, -suffix.length));
}

export function captureContext(page: Page, { out, mocked }: { out: string; mocked: boolean }): CaptureContext {
  let count = 0;
  const nextFile = (name: string) => {
    count += 1;
    return path.join(out, `${count}-${fileName(name)}.png`);
  };
  const settle = () => settleMap(page);
  return {
    page,
    expect,
    fixtures,
    states,
    catalogAxes,
    settle,
    async open({ point, zoom, layers = [], storedState, routes } = {}) {
      const layerIds: string[] = mapDisplay.layers.map(({ id }) => id);
      const unknown = layers.filter((id) => !layerIds.includes(id));
      if (unknown.length > 0) {
        throw new Error(`知らないレイヤー: ${unknown.join(" / ")}。選べるレイヤー: ${layerIds.join(" / ")}`);
      }
      if (mocked) await fixtures.installApiMocks(page);
      if (point || !mocked) {
        await page.context().grantPermissions(["geolocation"]);
        await page.context().setGeolocation(point ?? LIVE_POINT);
      }
      if (routes) await routes(page);
      await page.addInitScript(states.installPageHelpers);
      await page.addInitScript(fixtures.installMapFinder);
      await fixtures.seedStoredState(page, {
        ...fixtures.INTRO_CLOSED,
        ...(layers.length > 0
          ? { "ridecompass:layer-visibility": JSON.stringify(Object.fromEntries(layers.map((id) => [id, true]))) }
          : {}),
        ...storedState,
      });
      await page.goto("/");
      await expect(page.locator(".maplibregl-map")).toBeVisible({ timeout: 60_000 });
      await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 60_000 });
      await settle();
      if (zoom !== undefined) {
        await page.evaluate((z) => window.__liveMap().jumpTo({ zoom: z }), zoom);
        await settle();
      }
    },
    async openAdmin({ tab, routes } = {}) {
      // 資格情報は scripts/capture.mjs が手元で起動する版へ渡したもの。
      const { ADMIN_BASIC_AUTH_USERNAME: username, ADMIN_BASIC_AUTH_PASSWORD: password } = process.env;
      if (!mocked || !username || !password) {
        throw new Error("管理画面はモックの応答でだけ開ける（--app production と --api を外す）");
      }
      await fixtures.installApiMocks(page);
      if (routes) await routes(page);
      await page.setExtraHTTPHeaders({
        Authorization: `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`,
      });
      await page.goto("/admin");
      // タブの中身にも入れ子のタブがあるので、一番外の並びで選ぶ。
      const tabs = page.getByRole("tablist").first();
      await expect(tabs).toBeVisible();
      if (tab !== undefined) {
        const trigger = tabs.getByRole("tab", { name: tab, exact: true });
        if (!(await trigger.isVisible())) {
          const names = await tabs.getByRole("tab").allInnerTexts();
          throw new Error(`管理画面のタブ「${tab}」を選べない。選べるタブ: ${names.join(" / ")}`);
        }
        await trigger.click();
      }
      const selected = await tabs.getByRole("tab", { selected: true }).innerText();
      return page.getByRole("tabpanel", { name: selected.trim(), exact: true });
    },
    async chooseLens(label) {
      try {
        await chooseLens(page, label);
      } catch (error) {
        throw new Error(`レンズ「${label}」を選べない。選べるレンズ: ${(await lensLabels(page)).join(" / ")}`, {
          cause: error,
        });
      }
      await settle();
    },
    async openLegend(layer, row) {
      const trigger = page.getByRole("button", { name: `${layer}の凡例`, exact: true });
      // ▶は「表示」の一覧の行にある。
      const list = page.getByRole("dialog", { name: OVERLAY_LIST_NAME, exact: true });
      if (!(await list.isVisible())) await page.getByRole("button", { name: OVERLAY_LIST_NAME, exact: true }).click();
      await expect(list).toBeVisible();
      if (!(await trigger.isVisible())) {
        throw new Error(`凡例「${layer}」を開けない。選べる凡例: ${(await ariaLabels(list, "の凡例")).join(" / ")}`);
      }
      // 内訳は一覧の行のすぐ下に開く。
      const panel = page.getByRole("region", { name: `${layer}の内訳` });
      if (!(await panel.isVisible())) await trigger.click();
      await expect(panel).toBeVisible();
      if (row !== undefined) {
        const info = panel.getByRole("button", { name: `${row}の説明を表示`, exact: true });
        if (!(await info.isVisible())) {
          const rows = await ariaLabels(panel, "の説明を表示");
          throw new Error(`凡例「${layer}」の行「${row}」の説明を開けない。説明のある行: ${rows.join(" / ")}`);
        }
        await info.click();
      }
      return panel;
    },
    async clickMap(lngLat) {
      await fixtures.clickMap(page, lngLat);
    },
    async clickVisible(lngLat) {
      await states.clickVisible(page, lngLat);
    },
    async clickFeature(target) {
      // 生成・レイヤーの切り替えの直後は、まだ描かれていない。
      await settle();
      await fixtures.clickFeature(page, target);
    },
    async patch(glob, transform) {
      await page.route(glob, async (route) => {
        const response = await route.fetch();
        if (response.ok()) {
          await route.fulfill({ response, json: await transform(await response.json()) });
          return;
        }
        // 本物の backend にまだ無い経路（404 等）。失敗の状態を引き継ぐと替えた本文も失敗として読まれるので、成功で返す。
        await route.fulfill({ json: await transform(undefined), headers: { "access-control-allow-origin": "*" } });
      });
    },
    async shot(name, target) {
      const file = nextFile(name);
      await (target ?? page).screenshot({ path: file });
      console.log(`[capture] ${file}`);
      return file;
    },
    async shotWithKeyboard(name, field, { height: keyboard = fixtures.KEYBOARD_HEIGHT } = {}) {
      const viewport = page.viewportSize();
      const box = await field.boundingBox();
      if (!viewport || !box) throw new Error(`「${name}」: 打つ欄が画面に無い`);
      if (keyboard <= 0 || keyboard >= viewport.height) {
        throw new Error(`「${name}」: キーボードの高さ ${keyboard} は画面の高さ ${viewport.height} の中に収まらない`);
      }
      // 見える範囲は、レイアウトの下端より下へはずれない。
      const shift = Math.min(keyboard, Math.max(0, box.y + box.height - (viewport.height - keyboard)));
      const image = await composeKeyboard(page, await page.screenshot(), viewport, { shift, keyboard });
      const file = nextFile(name);
      await writeFile(file, image);
      console.log(`[capture] ${file}`);
      return file;
    },
  };
}
