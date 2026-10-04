/**
 * トップページ（`app/page.tsx`）——画面の枠（区分・シートの開閉と高さ・「ルート設定」のタブ・新着の印）と、機能の間の
 * 受け渡し（ある機能の変化が別の機能の振る舞いを変えるもの）を、ページを描いて確かめる。
 *
 * ここで見ること:
 * - 区分（デスクトップ）とシート（モバイル）の開閉・高さ・保存と、生成の結果が出たときの知らせ方
 * - 生成の条件・走行条件・地図のレンズ・出発地が、生成の要求・地図・「ルート結果」へ同じ値で届くこと
 * - 地図で地点・区間を扱えるのは、それを持つパネルを見ている間だけで、編集中は止まること
 * - 結果・生成・区間の乗り換えをつなぐもの（`features/route/useRoutePlanner.ts`。各機能の単体では見えないので、ここで
 *   受け渡しとして見る）: 作った候補が結果へ入る・全消去と作り直しで編集が終わる・候補の有無が条件のずれの知らせに効く
 * - ヘッダー（天気・警報・取得の失敗の印・メニュー）と、地図の上の操作（まとめて戻す・現在地）の受け渡し
 *
 * ここで見ないもの（持ち主のテストが見る）:
 * - 子の部品の描くもの → 各部品のテスト（下の代役の一覧）。地図（`MapView`）の入口は #98 の対象
 * - 生成の検証・送信・条件のずれの判定・実験スロットの積み方 → `features/route/useRouteGeneration.test.ts`
 * - 結果の選択・編集で作ったルートの番号 → `features/route/useRouteResults.test.ts`
 * - 乗り換え先の求め方・作る前の評価・失敗の出し方 → `features/route/useSpliceSession.test.ts`
 * - 地図の見え方の中身（レンズの選択肢・凡例・チップ） → `features/map/view/useMapView.test.ts`
 * - 位置の取得の並走と決着 → `hooks/useLocation.test.ts`
 *
 * 差し替えたもの:
 * - backendを呼ぶ口（軸カタログ・天気・ルート生成）。地図の見え方が気象庁の配信を取る口は口のモジュールを持たないので、
 *   網（`fetch`）を失敗で答える（地図の見え方の中身はここで見ない）
 * - 位置情報（`navigator.geolocation`。テスト環境に無いブラウザの機能）。スマホ幅の印は根の要素の`--is-mobile`へ置く
 * - 子の部品（`@/testing/componentStubs`の代役）。地図はWebGLを要し、ほかは入口のテストを持つ機能の部品。
 *   区分の開閉（`Disclosure`）・タブ・ボタンは描く
 */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import { fetchDynamicWayValues } from "@/features/map/regionApi";
import type { MapLook } from "@/features/map/view/mapLook";
import { generateRoutes, type GenerationProgress } from "@/features/route/routeApi";
import { CLIENT_TUNING_IDS } from "@/lib/axisCatalog";
import { setDebugEnabled } from "@/lib/debugLog";
import { setResearchEnabled } from "@/lib/researchMode";
import { getAxisCatalog } from "@/services/axisCatalogApi";
import {
  getAmedasObservation,
  getCurrentWeather,
  getFloodForecasts,
  getWbgtStatus,
  getWeatherWarnings,
} from "@/services/weatherApi";
import { stubBackend } from "@/testing/backendFetch";
import { catalogEntry, catalogResponse, dedicatedEntry, rampEntry } from "@/testing/catalogAxes";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import type { FetchFailure } from "@/types/fetchFailure";
import type {
  Coordinates,
  GenerationConditions,
  RouteCandidate,
  RouteGenerateRequest,
  RouteSegmentDetail,
} from "@/types/route";

import Home from "./page";

const { stubComponent, stubModule, stubProps, isStubMounted } = await vi.hoisted(
  () => import("@/testing/componentStubs"),
);

vi.mock("@/services/axisCatalogApi", () => ({ getAxisCatalog: vi.fn() }));
vi.mock("@/services/weatherApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/weatherApi")>()),
  getCurrentWeather: vi.fn(),
  getAmedasObservation: vi.fn(),
  getWeatherWarnings: vi.fn(),
  getWbgtStatus: vi.fn(),
  getFloodForecasts: vi.fn(),
}));
vi.mock("@/features/map/regionApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/map/regionApi")>()),
  fetchDynamicWayValues: vi.fn(),
}));
vi.mock("@/features/route/routeApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/route/routeApi")>()),
  generateRoutes: vi.fn(),
}));

vi.mock("@/features/map/MapView/MapView", stubModule("MapView"));
vi.mock("@/features/map/LensControl/LensControl", stubModule("LensControl"));
vi.mock("@/features/map/MapOverlayControls/MapOverlayControls", stubModule("MapOverlayControls"));
vi.mock("@/features/conditions/TravelBearingControl/TravelBearingControl", stubModule("TravelBearingControl"));
vi.mock("@/features/conditions/RideConditionBar/RideConditionBar", stubModule("RideConditionBar"));
vi.mock("@/features/conditions/WeatherPanel/WeatherPanel", stubModule("WeatherPanel"));
vi.mock("@/features/conditions/TodayOutlook/TodayOutlook", stubModule("TodayOutlook"));
vi.mock("@/features/conditions/WarningBadge/WarningBadge", stubModule("WarningBadgeList"));
vi.mock("@/components/HeaderMenu/HeaderMenu", stubModule("HeaderMenu"));
vi.mock("@/components/DebugConsole/DebugConsole", stubModule("DebugConsole"));
vi.mock("@/components/UsageGuide/UsageGuide", stubModule("UsageGuide"));
vi.mock("@/components/FirstVisitIntro/FirstVisitIntro", stubModule("FirstVisitIntro"));
vi.mock("@/features/route/RouteOutcome/RouteOutcome", stubModule("RouteOutcome"));
vi.mock("@/features/route/RouteSettingsPanel/RouteSettingsPanel", stubModule("RouteSettingsPanel"));
vi.mock("@/features/route/RouteSettingsPanel/HardFilterPanel", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/route/RouteSettingsPanel/HardFilterPanel")>()),
  default: stubComponent("HardFilterPanel"),
}));
// 重み・除外のパネルは「ルート設定」が受け取って描くノードなので、代役もそれを描く。
vi.mock("@/features/route/RouteForm/RouteForm", () => ({
  default: stubComponent("RouteForm", (props) => (
    <>
      {props.weightsPanel as ReactNode}
      {props.exclusionsPanel as ReactNode}
    </>
  )),
}));
// シートは2枚あるので題名で分けて記録する。見出し行へ差し込むタブ・ボタンも描く。
vi.mock("@/components/BottomSheet/BottomSheet", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/BottomSheet/BottomSheet")>()),
  default: stubComponent(
    (props) => `BottomSheet:${String(props.title)}`,
    (props) => (
      <section aria-label={String(props.title)}>
        {props.headerLead as ReactNode}
        {props.headerAction as ReactNode}
        {props.children as ReactNode}
      </section>
    ),
  ),
}));

// ---- 代役が受け取るprops（読むものだけ） ----

interface MapViewProps {
  routes: RouteCandidate[];
  selectedRouteId: string | null;
  location: Coordinates;
  locationSource: string;
  look: { lens: string; layerVisibility: Record<string, boolean>; refreshToken: number };
  rideConditions: { bearingDeg: number; at: Date; speedKmh: number };
  routePreference: Record<string, number> | null;
  experimentSlots: unknown[];
  selectedRouteSegment: unknown;
  onRouteSegmentSelect: (selection: unknown) => void;
  waypoints: Coordinates[];
  onWaypointRemove: (index: number) => void;
  onWaypointMove: (index: number, point: Coordinates) => void;
  destination: Coordinates | null;
  onDestinationClear: () => void;
  armedPinRole: string | null;
  pointEditingEnabled: boolean;
  onPinPlace: (role: "origin" | "waypoint" | "destination", point: Coordinates) => void;
  measureRouteFitObscuredPx: () => { bottom: number } | undefined;
}

interface RouteFormProps {
  distance: string;
  onDistanceChange: (value: string) => void;
  maxRoutes: string;
  onMaxRoutesChange: (value: string) => void;
  routeMode: "loop" | "destination";
  onRouteModeChange: (mode: "loop" | "destination") => void;
  waypointCount: number;
  onWaypointsClear: () => void;
  destinationSet: boolean;
  onDestinationClear: () => void;
  originManual: boolean;
  originLocated: boolean;
  onOriginReset: () => void;
  armedPinRole: string | null;
  onArmPinRole: (role: "origin" | "waypoint" | "destination" | null) => void;
}

interface RouteOutcomeProps {
  results: {
    routes: RouteCandidate[];
    selectTab: (value: string) => void;
  };
  generation: { experimentSlots: unknown[]; failure: string | null; generatedInput: unknown };
  splice: {
    start: (routeId: string) => void;
    panel: { onCancel: () => void; onApply: () => Promise<void> } | null;
  };
  routeWeights: Record<string, number>;
}

interface SheetProps {
  open: boolean;
  onClose: () => void;
  heightVh: number;
  onHeightChange: (vh: number) => void;
  onHeightCommit: (vh: number) => void;
  autoFitHeight: boolean;
  fitKey?: string;
}

const mapView = () => stubProps<MapViewProps>("MapView");
const routeForm = () => stubProps<RouteFormProps>("RouteForm");
const outcome = () => stubProps<RouteOutcomeProps>("RouteOutcome");
const settingsSheet = () => stubProps<SheetProps>("BottomSheet:ルート設定");
const outcomeSheet = () => stubProps<SheetProps>("BottomSheet:ルート結果");

// ---- 位置情報 ----

const HERE: Coordinates = { latitude: 35.68, longitude: 139.77 };
const PICKED: Coordinates = { latitude: 35.7, longitude: 139.8 };

interface PendingPosition {
  succeed: (point: Coordinates) => void;
  fail: () => void;
}

/** 位置の要求に、すぐ現在地を返す・すぐ断る・テストが決めるまで待つ。 */
let positionAnswer: "here" | "deny" | "wait";
let positionRequests: PendingPosition[];

function installGeolocation() {
  positionRequests = [];
  const geolocation = {
    getCurrentPosition(onSuccess: PositionCallback, onError: PositionErrorCallback) {
      const pending: PendingPosition = {
        succeed: (point) =>
          onSuccess({ coords: { latitude: point.latitude, longitude: point.longitude } } as GeolocationPosition),
        fail: () => onError({ code: 1, message: "denied" } as GeolocationPositionError),
      };
      positionRequests.push(pending);
      if (positionAnswer === "here") pending.succeed(HERE);
      if (positionAnswer === "deny") pending.fail();
    },
  };
  Object.defineProperty(navigator, "geolocation", { value: geolocation, configurable: true });
}

// ---- backend ----

const AXIS = "climb";
const WIND_AXIS = "headwind";

function usedConditions(overrides: Partial<GenerationConditions> = {}): GenerationConditions {
  return {
    latitude: HERE.latitude,
    longitude: HERE.longitude,
    distance_km: 30,
    distance_tolerance_km: 5,
    route_preference: { [AXIS]: 1 },
    penalty_strength: 1,
    max_average_grade_percent: null,
    hard_filters: {},
    max_routes: 3,
    start_time: "2026-10-04T00:00:00Z",
    assumed_speed_kmh: 20,
    waypoints: null,
    destination: null,
    corrected_destination: null,
    generated_at: "2026-10-04T00:00:00Z",
    ...overrides,
  };
}

function route(id: string, overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return makeRouteCandidate({ id, estimated_duration_seconds: 3600, ...overrides });
}

// 区間の乗り換えができる2本: 同じ地点（n0〜n5）で交わり、2つの分かれ道で別の道を通る。
const NODES = ["n0", "n1", "n2", "n3", "n4", "n5"];
const lineOf = (points: [number, number][]) => ({ type: "LineString" as const, coordinates: points });
const ROUTE_A = route("a", {
  edge_ids: ["e1", "a1", "e2", "a2", "e3"],
  node_ids: NODES,
  edge_point_offsets: [0, 1, 2, 3, 4, 5],
  geometry: lineOf([
    [0, 0],
    [1, 0],
    [2, 0],
    [3, 0],
    [4, 0],
    [5, 0],
  ]),
});
const ROUTE_B = route("b", {
  estimated_duration_seconds: 4000,
  edge_ids: ["e1", "b1", "e2", "b2", "e3"],
  node_ids: NODES,
  edge_point_offsets: [0, 1, 3, 4, 6, 7],
  geometry: lineOf([
    [0, 0],
    [1, 0],
    [1.5, 1],
    [2, 0],
    [3, 0],
    [3.5, 1],
    [4, 0],
    [5, 0],
  ]),
});
const SPLICEABLE_CATALOG = catalogResponse([catalogEntry({ axis_id: AXIS, default_weight: 1 })], {
  client_tuning: { [CLIENT_TUNING_IDS.minStretchKm]: 0.2 },
});

/** 次の生成を、渡した候補で答える。 */
function answerGeneration(routes: RouteCandidate[], conditions = usedConditions()) {
  vi.mocked(generateRoutes).mockResolvedValueOnce({ routes, conditions });
}

/** 次の生成を、テストが決めるまで終えない。進み方を送ってから、候補か失敗で終える。 */
function holdGeneration() {
  let onProgress: ((progress: GenerationProgress) => void) | undefined;
  let settle!: { resolve: (routes: RouteCandidate[]) => void; reject: (error: Error) => void };
  const pending = new Promise<Awaited<ReturnType<typeof generateRoutes>>>((resolve, reject) => {
    settle = { resolve: (routes) => resolve({ routes, conditions: usedConditions() }), reject };
  });
  vi.mocked(generateRoutes).mockImplementationOnce((_request, progress) => {
    onProgress = progress;
    return pending;
  });
  return {
    progress: (progress: GenerationProgress) => act(async () => onProgress?.(progress)),
    finish: (routes: RouteCandidate[]) => act(async () => settle.resolve(routes)),
  };
}

function lastRequest(): RouteGenerateRequest {
  const call = vi.mocked(generateRoutes).mock.lastCall;
  if (!call) throw new Error("生成を頼んでいない");
  return call[0];
}

// ---- 描く ----

function setMobile(mobile: boolean) {
  document.documentElement.style.setProperty("--is-mobile", mobile ? "1" : "0");
}

/** 描いて、位置の決着と軸カタログの到着を待つ。 */
async function renderHome() {
  const view = render(<Home />);
  await waitFor(() => expect(getAxisCatalog).toHaveBeenCalled());
  await act(async () => {});
  return view;
}

async function generate(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "ルート生成" }));
}

// 待つ act は async の関数で渡す。同期の関数の act を待つと、Testing Library が act の環境の印を先に戻し、
// React が残りを流す間に届いた更新が「act の環境ではない」と警告される。
const call = <A extends unknown[]>(fn: (...args: A) => void, ...args: A) => act(async () => fn(...args));

beforeEach(() => {
  stubBackend(() => new Response(null, { status: 503 }));
  localStorage.clear();
  positionAnswer = "here";
  installGeolocation();
  setMobile(false);
  vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse([catalogEntry({ axis_id: AXIS, default_weight: 1 })]));
  vi.mocked(getCurrentWeather).mockResolvedValue({ temperature_c: 20 } as never);
  vi.mocked(getAmedasObservation).mockResolvedValue({ station_name: "東京" } as never);
  vi.mocked(getWeatherWarnings).mockResolvedValue({ warnings: [] } as never);
  vi.mocked(getWbgtStatus).mockResolvedValue({ reading: null } as never);
  vi.mocked(getFloodForecasts).mockResolvedValue({ forecasts: [] } as never);
  vi.mocked(fetchDynamicWayValues).mockResolvedValue({ values: {}, error: false });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  vi.mocked(generateRoutes).mockReset();
  setDebugEnabled(false);
  setResearchEnabled(false);
  document.documentElement.style.removeProperty("--is-mobile");
  Object.defineProperty(navigator, "geolocation", { value: undefined, configurable: true });
});

describe("区分とサイドバー（デスクトップ）", () => {
  it("2つの区分は開いて始まり、見出しで畳んだ状態は描き直しても保つ", async () => {
    const user = userEvent.setup();
    const { unmount } = await renderHome();
    expect(screen.getByRole("button", { name: "ルート設定" })).toHaveAttribute("aria-expanded", "true");
    expect(isStubMounted("RouteOutcome")).toBe(true);

    await user.click(screen.getByRole("button", { name: "ルート設定" }));
    await user.click(screen.getByRole("button", { name: "ルート結果" }));
    expect(isStubMounted("RouteForm")).toBe(false);
    expect(isStubMounted("RouteOutcome")).toBe(false);

    unmount();
    await renderHome();
    expect(screen.getByRole("button", { name: "ルート設定" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "ルート結果" })).toHaveAttribute("aria-expanded", "false");
  });

  it("パネルを閉じると区分ごと隠し、開き直すと区分の開閉を保ったまま戻す", async () => {
    const user = userEvent.setup();
    await renderHome();
    await user.click(screen.getByRole("button", { name: "ルート結果" }));

    expect(screen.getByRole("button", { name: "パネルを閉じる" })).toHaveTextContent("✕");
    await user.click(screen.getByRole("button", { name: "パネルを閉じる" }));
    expect(screen.getByRole("button", { name: "パネルを開く" })).toHaveTextContent("☰");
    expect(screen.queryByRole("button", { name: "ルート設定" })).toBeNull();
    expect(screen.queryByRole("button", { name: "ルート生成" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "パネルを開く" }));
    expect(screen.getByRole("button", { name: "ルート設定" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "ルート結果" })).toHaveAttribute("aria-expanded", "false");
  });

  it("デスクトップには下部タブもシートも無い", async () => {
    await renderHome();
    expect(screen.queryByRole("navigation", { name: "パネル切り替え" })).toBeNull();
    expect(isStubMounted("BottomSheet:ルート設定")).toBe(false);
  });
});

describe("生成", () => {
  it("入力欄で変えた距離・候補の数と、出発地・地図のレンズで生成を頼む", async () => {
    const user = userEvent.setup();
    await renderHome();
    await call(routeForm().onDistanceChange, "42");
    await call(routeForm().onMaxRoutesChange, "5");
    await call(stubProps<{ onLensChange: (lens: string) => void }>("LensControl").onLensChange, AXIS);
    expect(routeForm()).toMatchObject({ distance: "42", maxRoutes: "5" });
    answerGeneration([route("a")]);

    await generate(user);

    expect(lastRequest()).toMatchObject({
      latitude: HERE.latitude,
      longitude: HERE.longitude,
      distance_km: 42,
      max_routes: 5,
      lens_axis_id: AXIS,
    });
  });

  it("実行中は押せず、順番待ちか経過時間をボタンに出す", async () => {
    const user = userEvent.setup();
    await renderHome();
    const held = holdGeneration();

    await generate(user);
    const button = () => screen.getByRole("button", { name: /^(生成中|順番待ち)/ });
    expect(button()).toBeDisabled();
    expect(button()).toHaveAccessibleName("生成中...");
    expect(button()).toHaveTextContent("生成中");

    await held.progress({ status: "queued", elapsedMs: 1000 });
    expect(button()).toHaveAccessibleName("順番待ち...");
    expect(button()).toHaveTextContent("順番待ち");

    await held.progress({ status: "running", elapsedMs: 12_400 });
    expect(button()).toHaveAccessibleName("生成中...(12秒経過)");

    await held.finish([route("a")]);
    expect(screen.getByRole("button", { name: "ルート生成" })).toBeEnabled();
  });

  it("候補・失敗・入力の誤りのどれが出ても、閉じていた「ルート結果」を開く", async () => {
    const user = userEvent.setup();
    positionAnswer = "deny";
    await renderHome();
    const outcomeSection = () => screen.getByRole("button", { name: "ルート結果" });

    await user.click(outcomeSection());
    await generate(user);
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "true");

    await call(mapView().onPinPlace, "origin", PICKED);
    await user.click(outcomeSection());
    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混雑しています"));
    await generate(user);
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "true");

    await user.click(outcomeSection());
    answerGeneration([route("a")]);
    await generate(user);
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "true");
  });

  it("候補を地図と「ルート結果」へ渡し、「ルート結果」で選んだ候補を地図でも選ぶ", async () => {
    const user = userEvent.setup();
    await renderHome();
    answerGeneration([route("a"), route("b", { estimated_duration_seconds: 4000 })]);

    await generate(user);
    expect(mapView().routes.map((r) => r.id)).toEqual(["a", "b"]);
    expect(outcome().results.routes.map((r) => r.id)).toEqual(["a", "b"]);
    expect(mapView().selectedRouteId).toBe("a");

    await call(outcome().results.selectTab, "b");
    expect(mapView().selectedRouteId).toBe("b");
  });

  it("候補を選んだか・選んだ候補が区間の内訳を持つかを、地図の見え方（チップ・レンズ）へ渡す", async () => {
    const user = userEvent.setup();
    await renderHome();
    const routeOnlyChips = () =>
      stubProps<{ layers: { id: string; disabled?: boolean }[] }>("MapOverlayControls")
        .layers.filter((layer) => layer.disabled)
        .map((layer) => layer.id);
    const lockedBeforeRoute = routeOnlyChips();
    expect(lockedBeforeRoute.length).toBeGreaterThan(0);
    expect(stubProps<{ hasDetail: boolean }>("LensControl").hasDetail).toBe(false);
    answerGeneration([route("a", { segments: [{} as RouteSegmentDetail] })]);

    await generate(user);

    expect(routeOnlyChips().filter((id) => lockedBeforeRoute.includes(id))).toEqual([]);
    expect(stubProps<{ hasDetail: boolean }>("LensControl").hasDetail).toBe(true);
  });

  it("作った後に条件を変えると、「生成」の隣に印を付ける", async () => {
    const user = userEvent.setup();
    await renderHome();
    const mark = () => screen.queryByRole("img", { name: "生成条件が変更されています" });
    answerGeneration([route("a")]);
    await generate(user);
    expect(mark()).toBeNull();

    await call(routeForm().onDistanceChange, "50");

    expect(mark()).not.toBeNull();
  });

  it("「全消去」は候補がある間だけ見出しに出し、押すと地図と「ルート結果」から候補を消す。置いた地点は残す", async () => {
    const user = userEvent.setup();
    await renderHome();
    expect(screen.queryByRole("button", { name: "候補を全消去" })).toBeNull();
    await call(routeForm().onRouteModeChange, "destination");
    await call(mapView().onPinPlace, "destination", PICKED);
    answerGeneration([route("a")]);
    await generate(user);

    const clear = screen.getByRole("button", { name: "候補を全消去" });
    expect(clear).toHaveTextContent("全消去");
    expect(clear.querySelector("svg")).not.toBeNull();

    await user.click(clear);

    expect(mapView().routes).toEqual([]);
    expect(outcome().results.routes).toEqual([]);
    expect(mapView().destination).toEqual(PICKED);
    expect(screen.queryByRole("button", { name: "候補を全消去" })).toBeNull();
  });
});

describe("結果・生成・区間の乗り換えのつなぎ", () => {
  it("候補0件の後は、条件を変えても変わったとは知らせない（比べる候補が無い）", async () => {
    const user = userEvent.setup();
    await renderHome();
    answerGeneration([]);
    await generate(user);

    await call(routeForm().onDistanceChange, "50");

    expect(screen.queryByRole("img", { name: "生成条件が変更されています" })).toBeNull();
  });

  it("「全消去」は生成の側も消す: 条件の変更の印と、作った条件を消す", async () => {
    const user = userEvent.setup();
    await renderHome();
    answerGeneration([route("a")]);
    await generate(user);
    await call(routeForm().onDistanceChange, "50");

    await user.click(screen.getByRole("button", { name: "候補を全消去" }));

    expect(screen.queryByRole("img", { name: "生成条件が変更されています" })).toBeNull();
    expect(outcome().generation.generatedInput).toBeNull();
  });

  it("編集で地図の帯を選んで作ると、作ったルートを足して選び、閉じていた「ルート結果」を開く。地図には元と作ったものだけを描き、直前の生成の失敗の文言は消す", async () => {
    const user = userEvent.setup();
    vi.mocked(getAxisCatalog).mockResolvedValue(SPLICEABLE_CATALOG);
    await renderHome();
    answerGeneration([ROUTE_A, ROUTE_B]);
    await generate(user);
    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混雑しています"));
    await generate(user);
    expect(outcome().generation.failure).toBe("混雑しています");

    await call(outcome().splice.start, "a");
    const stretches = stubProps<{ spliceStretches: { index: number }[] }>("MapView").spliceStretches;
    expect(stretches.length).toBeGreaterThan(0);
    await call(
      stubProps<{ onSpliceStretchSelect: (index: number) => void }>("MapView").onSpliceStretchSelect,
      stretches[0].index,
    );
    expect(stubProps<{ splicedRoute: unknown[] | null }>("MapView").splicedRoute).not.toBeNull();
    const apply = outcome().splice.panel!.onApply;
    await user.click(screen.getByRole("button", { name: "ルート結果" }));
    const spliced = route("from-backend", { edge_ids: ["e1", "b1", "e2", "a2", "e3"] });
    answerGeneration([spliced]);

    await act(async () => apply());

    expect(screen.getByRole("button", { name: "ルート結果" })).toHaveAttribute("aria-expanded", "true");
    expect(outcome().results.routes).toHaveLength(3);
    expect(mapView().routes.map((r) => r.edge_ids)).toEqual([ROUTE_A.edge_ids, spliced.edge_ids]);
    expect(outcome().generation.failure).toBeNull();
    expect(outcome().splice.panel).toBeNull();
  });

  it("編集中に「全消去」を押すと編集も終わって地点の操作が戻る", async () => {
    const user = userEvent.setup();
    await renderHome();
    answerGeneration([route("a"), route("b")]);
    await generate(user);
    await call(outcome().splice.start, "a");
    expect(mapView().pointEditingEnabled).toBe(false);

    await user.click(screen.getByRole("button", { name: "候補を全消去" }));

    expect(mapView().pointEditingEnabled).toBe(true);
    expect(outcome().splice.panel).toBeNull();
  });

  it("作り直すと編集を終える（作り直した候補のidが同じでも、前の編集を残さない）", async () => {
    const user = userEvent.setup();
    await renderHome();
    answerGeneration([route("a"), route("b")]);
    await generate(user);
    await call(outcome().splice.start, "a");
    expect(outcome().splice.panel).not.toBeNull();

    answerGeneration([route("a"), route("b")]);
    await generate(user);

    expect(outcome().splice.panel).toBeNull();
    expect(mapView().pointEditingEnabled).toBe(true);
  });
});

describe("重み・除外の受け渡し", () => {
  it("重みを上書きすると、その重みを地図の道の評価と生成へ渡す。上書きしない間はどちらにも渡さない", async () => {
    const user = userEvent.setup();
    await renderHome();
    const panel = () =>
      stubProps<{
        routePreference: Record<string, number>;
        onRoutePreferenceChange: (weights: Record<string, number>) => void;
        overrideEnabled: boolean;
        onOverrideEnabledChange: (on: boolean) => void;
      }>("RouteSettingsPanel");
    expect(mapView().routePreference).toBeNull();

    await call(panel().onOverrideEnabledChange, true);
    await call(panel().onRoutePreferenceChange, { [AXIS]: 3 });
    expect(panel()).toMatchObject({ overrideEnabled: true, routePreference: { [AXIS]: 3 } });
    answerGeneration([route("a")]);
    await generate(user);

    expect(mapView().routePreference).toEqual({ [AXIS]: 3 });
    expect(lastRequest().route_preference).toEqual({ [AXIS]: 3 });
  });

  it("「ルート結果」とレンズの選択肢が未使用を分ける重みは、生成前はいまの重み、生成後は生成に使われた重み", async () => {
    const user = userEvent.setup();
    await renderHome();
    const lensUnused = () =>
      stubProps<{ axisOptions: { id: string; unused: boolean }[] }>("LensControl").axisOptions.find(
        (option) => option.id === AXIS,
      )?.unused;
    await call(
      stubProps<{ onRoutePreferenceChange: (w: Record<string, number>) => void }>("RouteSettingsPanel")
        .onRoutePreferenceChange,
      {
        [AXIS]: 2,
      },
    );
    expect(outcome().routeWeights).toEqual({ [AXIS]: 2 });
    expect(lensUnused()).toBe(false);

    answerGeneration([route("a")], usedConditions({ route_preference: { [AXIS]: 0 } }));
    await generate(user);

    expect(outcome().routeWeights).toEqual({ [AXIS]: 0 });
    expect(lensUnused()).toBe(true);
  });

  it("除外のパネルで変えた道路の種類を生成へ渡す", async () => {
    const user = userEvent.setup();
    await renderHome();
    const panel = () =>
      stubProps<{ hardFilters: Record<string, boolean>; onHardFiltersChange: (f: Record<string, boolean>) => void }>(
        "HardFilterPanel",
      );
    const changed = Object.fromEntries(Object.entries(panel().hardFilters).map(([key, on]) => [key, !on]));

    await call(panel().onHardFiltersChange, changed);
    answerGeneration([route("a")]);
    await generate(user);

    expect(lastRequest().hard_filters).toEqual(changed);
  });

  it("実験スロットは研究モードで「比較」を見ている間だけ地図へ重ねる", async () => {
    const user = userEvent.setup();
    setResearchEnabled(true);
    await renderHome();
    answerGeneration([route("a")]);
    await generate(user);
    expect(outcome().generation.experimentSlots).toHaveLength(1);
    expect(mapView().experimentSlots).toEqual([]);

    await call(outcome().results.selectTab, "comparison");

    expect(mapView().experimentSlots).toEqual(outcome().generation.experimentSlots);
  });
});

describe("走行条件の受け渡し", () => {
  it("走行方位・出発時刻・想定速度は、地図と生成が同じ値を読む", async () => {
    const user = userEvent.setup();
    await renderHome();
    const departure = new Date("2026-10-05T06:00:00+09:00");

    await call(stubProps<{ onChange: (deg: number) => void }>("TravelBearingControl").onChange, 90);
    await call(
      stubProps<{ onDepartureTimeChange: (at: Date) => void }>("RideConditionBar").onDepartureTimeChange,
      departure,
    );
    await call(stubProps<{ onSpeedKmhChange: (speed: number) => void }>("RideConditionBar").onSpeedKmhChange, 28);

    expect(stubProps<{ value: number }>("TravelBearingControl").value).toBe(90);
    expect(stubProps<{ departureTime: Date; speedKmh: number }>("RideConditionBar")).toMatchObject({
      departureTime: departure,
      speedKmh: 28,
    });
    expect(mapView().rideConditions).toEqual({ bearingDeg: 90, at: departure, speedKmh: 28 });
    answerGeneration([route("a")]);
    await generate(user);
    expect(lastRequest()).toMatchObject({ start_time: departure.toISOString(), assumed_speed_kmh: 28 });
  });

  it("地図の見え方も同じ走行条件で道の色分けを取る", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(
      catalogResponse([
        dedicatedEntry(WIND_AXIS, [1, 2], { dynamic_way_value_conditions: ["at", "bearing_deg", "speed_kmh"] }),
      ]),
    );
    await renderHome();
    const departure = new Date("2026-10-05T06:00:00+09:00");
    await call(stubProps<{ onChange: (deg: number) => void }>("TravelBearingControl").onChange, 90);
    await call(
      stubProps<{ onDepartureTimeChange: (at: Date) => void }>("RideConditionBar").onDepartureTimeChange,
      departure,
    );
    await call(stubProps<{ onSpeedKmhChange: (speed: number) => void }>("RideConditionBar").onSpeedKmhChange, 28);
    await call(stubProps<{ onLensChange: (lens: string) => void }>("LensControl").onLensChange, WIND_AXIS);

    await call(stubProps<{ look: MapLook }>("MapView").look.onViewportChange, {
      west: 139.7,
      south: 35.6,
      east: 139.71,
      north: 35.61,
      zoom: 14,
    });

    await waitFor(() => expect(fetchDynamicWayValues).toHaveBeenCalled());
    const [axisId, , , , bearingDeg, at, speedKmh] = vi.mocked(fetchDynamicWayValues).mock.lastCall!;
    expect({ axisId, bearingDeg, at, speedKmh }).toEqual({
      axisId: WIND_AXIS,
      bearingDeg: 90,
      at: departure,
      speedKmh: 28,
    });
  });

  it("出発時刻を「今」へ戻すと、地図は選んでいた時刻を離れる", async () => {
    await renderHome();
    const departure = new Date("2030-01-01T06:00:00+09:00");
    const bar = () =>
      stubProps<{ onDepartureTimeChange: (at: Date) => void; onDepartureNow: () => void }>("RideConditionBar");
    await call(bar().onDepartureTimeChange, departure);

    await call(bar().onDepartureNow);

    expect(mapView().rideConditions.at).not.toEqual(departure);
  });
});

describe("出発地と地点", () => {
  it("出発地の行は、現在地か地図で置いた地点かを受け取り、地図で置いた出発地から生成する", async () => {
    const user = userEvent.setup();
    await renderHome();
    expect(routeForm()).toMatchObject({ originLocated: true, originManual: false });
    expect(mapView().location).toEqual(HERE);

    await call(mapView().onPinPlace, "origin", PICKED);

    expect(routeForm()).toMatchObject({ originLocated: true, originManual: true });
    expect(mapView()).toMatchObject({ location: PICKED, locationSource: "manual" });
    answerGeneration([route("a")]);
    await generate(user);
    expect(lastRequest()).toMatchObject({ latitude: PICKED.latitude, longitude: PICKED.longitude });
  });

  it("出発地の行の「現在地に戻す」で位置を取り直す", async () => {
    await renderHome();
    await call(mapView().onPinPlace, "origin", PICKED);
    const before = positionRequests.length;

    await call(routeForm().onOriginReset);

    expect(positionRequests).toHaveLength(before + 1);
    expect(mapView().location).toEqual(HERE);
    expect(routeForm().originManual).toBe(false);
  });

  it("経由地・目的地は目的地の間だけ地図へ渡す。周回へ切り替えても消さない", async () => {
    await renderHome();
    await call(routeForm().onRouteModeChange, "destination");
    await call(mapView().onPinPlace, "waypoint", HERE);
    await call(mapView().onPinPlace, "destination", PICKED);
    expect(mapView()).toMatchObject({ waypoints: [HERE], destination: PICKED });
    expect(routeForm()).toMatchObject({ waypointCount: 1, destinationSet: true });

    await call(routeForm().onRouteModeChange, "loop");
    expect(mapView()).toMatchObject({ waypoints: [], destination: null });

    await call(routeForm().onRouteModeChange, "destination");
    expect(mapView()).toMatchObject({ waypoints: [HERE], destination: PICKED });
  });

  it("地図で動かした経由地から生成し、地図と入力欄のどちらで消しても置いた点が消える", async () => {
    const user = userEvent.setup();
    await renderHome();
    await call(routeForm().onRouteModeChange, "destination");
    await call(mapView().onPinPlace, "waypoint", HERE);
    await call(mapView().onPinPlace, "waypoint", HERE);
    await call(mapView().onPinPlace, "destination", PICKED);

    await call(mapView().onWaypointMove, 1, PICKED);
    expect(mapView().waypoints).toEqual([HERE, PICKED]);
    answerGeneration([route("a")]);
    await generate(user);
    expect(lastRequest().waypoints).toEqual([HERE, PICKED]);

    await call(mapView().onWaypointRemove, 0);
    expect(mapView().waypoints).toEqual([PICKED]);
    await call(routeForm().onWaypointsClear);
    await call(routeForm().onDestinationClear);
    expect(mapView()).toMatchObject({ waypoints: [], destination: null });

    await call(mapView().onPinPlace, "destination", PICKED);
    await call(mapView().onDestinationClear);
    expect(routeForm()).toMatchObject({ waypointCount: 0, destinationSet: false });
  });
});

describe("地図で扱える操作（デスクトップ）", () => {
  it("地点を置けるのは「ルート設定」が開いていて「条件」タブを見ている間だけ", async () => {
    const user = userEvent.setup();
    await renderHome();
    await call(routeForm().onRouteModeChange, "destination");
    await call(routeForm().onArmPinRole, "destination");
    expect(mapView()).toMatchObject({ pointEditingEnabled: true, armedPinRole: "destination" });

    await user.click(screen.getByRole("tab", { name: "重み" }));
    expect(mapView()).toMatchObject({ pointEditingEnabled: false, armedPinRole: null });

    await user.click(screen.getByRole("tab", { name: "条件" }));
    await user.click(screen.getByRole("button", { name: "ルート設定" }));
    expect(mapView()).toMatchObject({ pointEditingEnabled: false, armedPinRole: null });
  });

  it("周回の間に地図のタップで置けるのは出発地だけ", async () => {
    await renderHome();
    await call(routeForm().onArmPinRole, "waypoint");
    expect(routeForm().armedPinRole).toBe("waypoint");
    expect(mapView()).toMatchObject({ pointEditingEnabled: true, armedPinRole: null });

    await call(routeForm().onArmPinRole, "origin");
    expect(mapView().armedPinRole).toBe("origin");
  });

  it("地図で区間を選べるのは「ルート結果」が開いている間だけ", async () => {
    const user = userEvent.setup();
    await renderHome();
    answerGeneration([route("a")]);
    await generate(user);
    const segment = { routeId: "a", segmentIndex: 0 };

    await user.click(screen.getByRole("button", { name: "ルート結果" }));
    await call(mapView().onRouteSegmentSelect, segment);
    expect(mapView().selectedRouteSegment).toBeNull();

    await user.click(screen.getByRole("button", { name: "ルート結果" }));
    await call(mapView().onRouteSegmentSelect, segment);
    expect(mapView().selectedRouteSegment).toEqual(segment);
  });

  it("パネルを閉じている間は、区分が開いていても地図で地点も区間も扱わない", async () => {
    const user = userEvent.setup();
    await renderHome();
    answerGeneration([route("a")]);
    await generate(user);
    await call(routeForm().onArmPinRole, "origin");

    await user.click(screen.getByRole("button", { name: "パネルを閉じる" }));
    await call(mapView().onRouteSegmentSelect, { routeId: "a", segmentIndex: 0 });

    expect(mapView()).toMatchObject({ pointEditingEnabled: false, armedPinRole: null, selectedRouteSegment: null });
  });

  it("区間の乗り換えの編集中は地点の操作も区間の選択も止め、やめると戻す", async () => {
    const user = userEvent.setup();
    await renderHome();
    answerGeneration([route("a"), route("b")]);
    await generate(user);
    await call(routeForm().onArmPinRole, "origin");

    await call(outcome().splice.start, "a");
    await call(mapView().onRouteSegmentSelect, { routeId: "a", segmentIndex: 0 });
    expect(mapView()).toMatchObject({ pointEditingEnabled: false, armedPinRole: null, selectedRouteSegment: null });

    await call(outcome().splice.panel!.onCancel);
    expect(mapView()).toMatchObject({ pointEditingEnabled: true, armedPinRole: "origin" });
  });

  it("デスクトップでは、ルートを地図へ収めるときに覆われた高さを渡さない", async () => {
    await renderHome();
    expect(mapView().measureRouteFitObscuredPx()).toBeUndefined();
  });
});

describe("地図の見え方", () => {
  it("レンズで選んだ塗り方を地図へ渡す", async () => {
    await renderHome();

    await call(stubProps<{ onLensChange: (lens: string) => void }>("LensControl").onLensChange, AXIS);

    expect(mapView().look.lens).toBe(AXIS);
    expect(stubProps<{ lens: string }>("LensControl").lens).toBe(AXIS);
  });

  it("「まとめて非表示」は表示中のレイヤーがある間だけ押せ、押すと地図とチップの全部を消す", async () => {
    const user = userEvent.setup();
    await renderHome();
    const hideAll = () => screen.getByRole("button", { name: "表示中のレイヤーをすべて非表示にする" });
    const chips = () =>
      stubProps<{ layers: { id: string; on: boolean }[]; onToggle: (id: string, on: boolean) => void }>(
        "MapOverlayControls",
      );
    expect(chips().layers.some((layer) => layer.on)).toBe(true);
    expect(hideAll()).toBeEnabled();

    await user.click(hideAll());

    expect(chips().layers.every((layer) => !layer.on)).toBe(true);
    expect(Object.values(mapView().look.layerVisibility).every((on) => !on)).toBe(true);
    expect(hideAll()).toBeDisabled();
    await call(chips().onToggle, chips().layers[0].id, true);
    expect(hideAll()).toBeEnabled();
  });

  it("凡例で隠した段が無い間は「絞り込みを解除」を押せず、あれば押すと全部を戻す", async () => {
    const user = userEvent.setup();
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse([rampEntry(AXIS, [1, 2])]));
    await renderHome();
    await call(stubProps<{ onLensChange: (lens: string) => void }>("LensControl").onLensChange, AXIS);
    const showAll = () => screen.getByRole("button", { name: "絞り込みをすべて解除する" });
    const lens = () =>
      stubProps<{ legend: { key: string }[]; hiddenLegendKeys: string[]; onToggleLegendKey: (key: string) => void }>(
        "LensControl",
      );
    expect(showAll()).toBeDisabled();

    await call(lens().onToggleLegendKey, lens().legend[0].key);
    expect(showAll()).toBeEnabled();

    await user.click(showAll());
    expect(lens().hiddenLegendKeys).toEqual([]);
    expect(showAll()).toBeDisabled();
  });

  it("「再描画」はいつでも押せ、押すたびに地図へ描き直しを伝える", async () => {
    const user = userEvent.setup();
    await renderHome();
    const before = mapView().look.refreshToken;

    await user.click(screen.getByRole("button", { name: "地図の表示を再描画する" }));

    expect(mapView().look.refreshToken).not.toBe(before);
  });
});

describe("ヘッダーとメニュー", () => {
  it("現在地が分かってから、その位置で天気・実測・警報を取り、取れた値をヘッダーへ渡す", async () => {
    positionAnswer = "wait";
    vi.mocked(getWeatherWarnings).mockResolvedValue({
      warnings: [{ code: "03", name: "大雨警報", level: "warning", additions: [] }],
    } as never);
    await renderHome();
    expect(getCurrentWeather).not.toHaveBeenCalled();
    expect(getWeatherWarnings).not.toHaveBeenCalled();

    await act(async () => positionRequests[0].succeed(HERE));

    await waitFor(() =>
      expect(stubProps<{ amedas: unknown }>("WeatherPanel").amedas).toEqual({ station_name: "東京" }),
    );
    expect(stubProps<{ weather: unknown }>("TodayOutlook").weather).toEqual({ temperature_c: 20 });
    await waitFor(() =>
      expect(stubProps<{ items: { label: string }[] }>("WarningBadgeList").items.map((item) => item.label)).toEqual([
        "大雨警報",
      ]),
    );
    for (const fetcher of [
      getCurrentWeather,
      getAmedasObservation,
      getWeatherWarnings,
      getWbgtStatus,
      getFloodForecasts,
    ]) {
      expect(fetcher).toHaveBeenCalledWith(HERE);
    }
  });

  it("現在地が分からないと決まったら天候・警報を取らず、ヘッダーの印に「現在地」を出して、そこから取り直せる", async () => {
    positionAnswer = "deny";
    await renderHome();
    const failures = () => stubProps<{ failures: FetchFailure[] }>("WarningBadgeList").failures;

    expect(failures().map((failure) => failure.label)).toEqual(["現在地"]);
    expect(getCurrentWeather).not.toHaveBeenCalled();

    positionAnswer = "here";
    await call(failures()[0].onRetry!);
    await waitFor(() => expect(getCurrentWeather).toHaveBeenCalledWith(HERE));
    expect(failures()).toEqual([]);
  });

  it("天気・実測の取得の失敗はそれぞれの欄へ、警報の取得の失敗と軸一覧を取得できないことはヘッダーの印に並べる", async () => {
    vi.mocked(getCurrentWeather).mockRejectedValue(new Error("予報を取れませんでした"));
    vi.mocked(getAmedasObservation).mockRejectedValue(new Error("実測を取れませんでした"));
    vi.mocked(getWeatherWarnings).mockRejectedValue(new Error("警報を取れませんでした"));
    vi.mocked(getAxisCatalog).mockRejectedValue(new Error("軸一覧を取れませんでした"));
    await renderHome();

    await waitFor(() =>
      expect(stubProps<{ error: string | null }>("WeatherPanel").error).toBe("実測を取れませんでした"),
    );
    expect(stubProps<{ error: string | null }>("TodayOutlook").error).toBe("予報を取れませんでした");

    await waitFor(() =>
      expect(stubProps<{ failures: FetchFailure[] }>("WarningBadgeList").failures.map((f) => f.label)).toEqual([
        "警報・注意報",
        "軸一覧",
      ]),
    );
  });

  it("メニューの「使い方を見る」で説明を見る状態に入り、説明の側で終えると抜ける", async () => {
    await renderHome();
    expect(isStubMounted("UsageGuide")).toBe(false);

    await call(stubProps<{ onStartUsageGuide: () => void }>("HeaderMenu").onStartUsageGuide);
    expect(isStubMounted("UsageGuide")).toBe(true);

    await call(stubProps<{ onEnd: () => void }>("UsageGuide").onEnd);
    expect(isStubMounted("UsageGuide")).toBe(false);
  });

  it("メニューからデバッグログを開閉し、コンソールの側からも閉じられる", async () => {
    // デバッグログは取得の失敗を console.error へ出すので、網の取得を通しておく。
    stubBackend(() => Response.json([]));
    setDebugEnabled(true);
    await renderHome();
    const menu = () =>
      stubProps<{ debugEnabled: boolean; debugConsoleOpen: boolean; onToggleDebugConsole: () => void }>("HeaderMenu");
    const consoleProps = () => stubProps<{ open: boolean; onClose: () => void }>("DebugConsole");
    expect(menu()).toMatchObject({ debugEnabled: true, debugConsoleOpen: false });

    await call(menu().onToggleDebugConsole);
    expect(consoleProps().open).toBe(true);
    expect(menu().debugConsoleOpen).toBe(true);

    await call(consoleProps().onClose);
    expect(consoleProps().open).toBe(false);
  });
});

describe("現在地のボタン", () => {
  it("待つ間は押せず、取れなかったら理由を地図の上に出す", async () => {
    const user = userEvent.setup();
    await renderHome();
    positionAnswer = "wait";

    await user.click(screen.getByRole("button", { name: "現在地に移動" }));
    expect(screen.getByRole("button", { name: "現在地に移動" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "現在地に移動" })).toHaveTextContent("…");

    await act(async () => positionRequests.at(-1)!.fail());

    expect(screen.getByRole("button", { name: "現在地に移動" })).toBeEnabled();
    expect(screen.getByText(/現在地を取得できませんでした/)).toBeInTheDocument();
  });
});

describe("モバイルの下部タブとシート", () => {
  beforeEach(() => setMobile(true));

  const tab = (name: string) =>
    within(screen.getByRole("navigation", { name: "パネル切り替え" })).getByRole("button", { name });

  it("タブを押すとそのシートを開き、同じタブでもう一度押すと閉じる。シートは1枚ずつ開く", async () => {
    const user = userEvent.setup();
    await renderHome();
    expect(screen.queryByRole("button", { name: "パネルを閉じる" })).toBeNull();
    expect(settingsSheet().open).toBe(false);

    await user.click(tab("ルート設定"));
    expect(settingsSheet().open).toBe(true);
    expect(tab("ルート設定")).toHaveAttribute("aria-expanded", "true");

    await user.click(tab("ルート結果"));
    expect(settingsSheet().open).toBe(false);
    expect(outcomeSheet().open).toBe(true);

    await user.click(tab("ルート結果"));
    expect(outcomeSheet().open).toBe(false);
  });

  it("シートの側から閉じても地図だけの状態へ戻る", async () => {
    const user = userEvent.setup();
    await renderHome();
    await user.click(tab("ルート設定"));
    await call(settingsSheet().onClose);
    expect(settingsSheet().open).toBe(false);

    await user.click(tab("ルート結果"));
    await call(outcomeSheet().onClose);
    expect(outcomeSheet().open).toBe(false);
  });

  it("「ルート設定」シートは見出しにタブと「生成」を置き、「ルート結果」シートは候補がある間だけ「全消去」を置く", async () => {
    const user = userEvent.setup();
    await renderHome();
    const settings = within(screen.getByRole("region", { name: "ルート設定" }));
    const results = within(screen.getByRole("region", { name: "ルート結果" }));
    expect(settings.getAllByRole("tab").map((t) => t.textContent)).toEqual(["条件", "重み", "除外"]);
    expect(results.queryByRole("button", { name: "候補を全消去" })).toBeNull();

    answerGeneration([route("a")]);
    await user.click(settings.getByRole("button", { name: "ルート生成" }));

    expect(results.getByRole("button", { name: "候補を全消去" })).toBeInTheDocument();
  });

  it("入力の誤りは「ルート設定」シートの中にも出し、直して生成すると消える", async () => {
    const user = userEvent.setup();
    positionAnswer = "deny";
    await renderHome();
    const settings = within(screen.getByRole("region", { name: "ルート設定" }));

    await user.click(settings.getByRole("button", { name: "ルート生成" }));
    expect(settings.getByText(/現在地が分かりません/)).toBeInTheDocument();

    await call(mapView().onPinPlace, "origin", PICKED);
    answerGeneration([route("a")]);
    await user.click(settings.getByRole("button", { name: "ルート生成" }));
    expect(settings.queryByText(/現在地が分かりません/)).toBeNull();
  });

  it("「ルート結果」タブの印: 失敗は赤の失敗、新しい結果と条件の変更は橙。タブを開くと新着の印は消え、条件の変更は残る", async () => {
    const user = userEvent.setup();
    await renderHome();
    const settings = within(screen.getByRole("region", { name: "ルート設定" }));
    const signal = () => tab("ルート結果").getAttribute("aria-description");
    expect(signal()).toBeNull();

    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混雑しています"));
    await user.click(settings.getByRole("button", { name: "ルート生成" }));
    expect(signal()).toBe("生成に失敗しました");

    answerGeneration([route("a")]);
    await user.click(settings.getByRole("button", { name: "ルート生成" }));
    expect(signal()).toBe("新しい結果があります");

    await user.click(tab("ルート結果"));
    expect(signal()).toBeNull();

    await call(routeForm().onDistanceChange, "50");
    expect(signal()).toBe("生成条件が変更されています");
  });

  it("シートの高さは2枚で共有し、動かしている間の高さはすぐ渡し、決めた高さだけを保存して中身に合わせるのをやめる", async () => {
    const { unmount } = await renderHome();
    expect(settingsSheet()).toMatchObject({ heightVh: DEFAULT_SHEET_HEIGHT_VH, autoFitHeight: true });

    await call(settingsSheet().onHeightChange, 63);
    expect(outcomeSheet().heightVh).toBe(63);
    expect(settingsSheet().autoFitHeight).toBe(true);

    await call(outcomeSheet().onHeightCommit, 70);
    expect(settingsSheet()).toMatchObject({ heightVh: 70, autoFitHeight: false });

    unmount();
    await renderHome();
    expect(outcomeSheet()).toMatchObject({ heightVh: 70, autoFitHeight: false });
  });

  it.each([
    { saved: "99", heightVh: 80, autoFitHeight: false },
    { saved: '"tall"', heightVh: DEFAULT_SHEET_HEIGHT_VH, autoFitHeight: true },
    { saved: "{", heightVh: DEFAULT_SHEET_HEIGHT_VH, autoFitHeight: true },
  ])("保存した高さ $saved は、範囲へ寄せるか既定の高さで始める", async ({ saved, heightVh, autoFitHeight }) => {
    localStorage.setItem("ridecompass:mobile-sheet-height-vh", saved);
    await renderHome();
    expect(settingsSheet()).toMatchObject({ heightVh, autoFitHeight });
  });

  it("「ルート設定」シートは、タブかモードが変わると中身に合わせ直す鍵が変わる", async () => {
    const user = userEvent.setup();
    await renderHome();
    const before = settingsSheet().fitKey;

    await user.click(screen.getByRole("tab", { name: "除外" }));
    const afterTab = settingsSheet().fitKey;
    await call(routeForm().onRouteModeChange, "destination");

    expect(new Set([before, afterTab, settingsSheet().fitKey]).size).toBe(3);
  });

  it("シートを開いている間だけ、地図の枠と、ルートを地図へ収めるときの覆われた高さにシートの高さを渡す", async () => {
    const user = userEvent.setup();
    const { container } = await renderHome();
    const pane = () => container.querySelector<HTMLElement>(".app-map-pane")!;
    expect(pane().style.getPropertyValue("--mobile-sheet-height")).toBe("0px");
    expect(mapView().measureRouteFitObscuredPx()).toEqual({ bottom: 0 });

    await user.click(tab("ルート結果"));

    expect(pane().style.getPropertyValue("--mobile-sheet-height")).toBe(`${DEFAULT_SHEET_HEIGHT_VH}vh`);
    expect(mapView().measureRouteFitObscuredPx()).toEqual({
      bottom: (window.innerHeight * DEFAULT_SHEET_HEIGHT_VH) / 100,
    });
  });

  it("地図で地点を扱えるのは「ルート設定」シートを開いている間、区間を選べるのは「ルート結果」シートを開いている間", async () => {
    const user = userEvent.setup();
    await renderHome();
    answerGeneration([route("a")]);
    await user.click(
      within(screen.getByRole("region", { name: "ルート設定" })).getByRole("button", { name: "ルート生成" }),
    );
    const segment = { routeId: "a", segmentIndex: 0 };
    expect(mapView().pointEditingEnabled).toBe(false);

    await user.click(tab("ルート設定"));
    expect(mapView().pointEditingEnabled).toBe(true);
    await call(mapView().onRouteSegmentSelect, segment);
    expect(mapView().selectedRouteSegment).toBeNull();

    await user.click(tab("ルート結果"));
    expect(mapView().pointEditingEnabled).toBe(false);
    await call(mapView().onRouteSegmentSelect, segment);
    expect(mapView().selectedRouteSegment).toEqual(segment);
  });

  it("初めて開いたときの案内へ、スマホ幅かを渡す", async () => {
    await renderHome();
    expect(stubProps<{ isMobile: boolean }>("FirstVisitIntro").isMobile).toBe(true);
  });
});
