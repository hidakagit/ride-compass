/**
 * トップページ（`app/page.tsx`）——画面の枠（区分・シートの開閉と高さ・「ルート設定」のタブ・新着の印）と、機能の間の
 * 値の受け渡し（生成の条件・走行条件・結果・乗り換えを、地図・フォーム・「ルート結果」・ヘッダーへ）。
 *
 * ここで見ないもの（各機能の入口のテストが見る）:
 * - 生成の条件の保存と揃え → `features/route/useGenerationConditions.ts`
 * - 生成の入力・進み方・案内・条件のずれ・実験スロット → `features/route/useRouteGeneration.ts`
 * - 結果の状態 → `features/route/useRouteResults.ts`、乗り換え → `features/route/useSpliceSession.ts`
 * - 「ルート結果」の中身 → `features/route/RouteOutcome/RouteOutcome.tsx`
 * - 走行条件 → `features/conditions/useRideConditions.ts`、位置の取得 → `hooks/useLocation.ts`
 *
 * 機能のフックは本物を通す（ページの仕事はフックの間の受け渡しで、それはフックを通さないと見えない）。
 * 差し替えた部品と、それで見えなくなるもの:
 * - 地図（`MapView`）・地図の見え方（`useMapView`）・レンズ・地図上チップ・「ルート結果」の中身（`RouteOutcome`）・
 *   入力欄（`RouteForm`）・重みと除外のパネル・走行方位と走行条件の部品・ヘッダーの天気と警報とメニュー・
 *   デバッグコンソール: 渡す値と、上がる操作だけを見る。部品自身の表示は見えない。
 * - 下部シート（`BottomSheet`）: 開閉・見出しへの差し込み・渡す高さだけを見る。ドラッグと自動の高さ合わせは見えない。
 * - 軸カタログ・天気の取得・ルート生成の通信・位置情報（`navigator.geolocation`）・スマホ幅の判定（`useIsMobile`）:
 *   返す値をテストが決める。
 */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "./page";
import type BottomSheet from "@/components/BottomSheet/BottomSheet";
import { DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import type DebugConsole from "@/components/DebugConsole/DebugConsole";
import type HeaderMenu from "@/components/HeaderMenu/HeaderMenu";
import type RideConditionBar from "@/features/conditions/RideConditionBar/RideConditionBar";
import type TodayOutlook from "@/features/conditions/TodayOutlook/TodayOutlook";
import type TravelBearingControl from "@/features/conditions/TravelBearingControl/TravelBearingControl";
import type WarningBadgeList from "@/features/conditions/WarningBadge/WarningBadge";
import type WeatherPanel from "@/features/conditions/WeatherPanel/WeatherPanel";
import { dotVariants } from "@/components/ui/Dot/Dot";
import { useWeatherConditions } from "@/features/conditions/useWeatherConditions";
import type LensControl from "@/features/map/LensControl/LensControl";
import type MapOverlayControls from "@/features/map/MapOverlayControls/MapOverlayControls";
import type MapView from "@/features/map/MapView/MapView";
import type { useMapView } from "@/features/map/view/useMapView";
import type RouteForm from "@/features/route/RouteForm/RouteForm";
import type RouteOutcome from "@/features/route/RouteOutcome/RouteOutcome";
import type HardFilterPanel from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import type RouteSettingsPanel from "@/features/route/RouteSettingsPanel/RouteSettingsPanel";
import { generateRoutes } from "@/features/route/routeApi";
import { SPLICED_ROUTE_ID_PREFIX } from "@/features/route/routeTabLabel";
import { axisCatalogFromResponse, CLIENT_TUNING_IDS, EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";
import { catalogEntry } from "@/testing/catalogAxes";
import { LENS_DIFFICULTY_ID } from "@/lib/mapDisplay/routeStyleModes";
import { setResearchEnabled } from "@/lib/researchMode";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import type { Coordinates, GenerationConditions, RouteCandidate, RouteSegmentDetail } from "@/types/route";

const { stubComponent, stubModule, stubProps } = await vi.hoisted(() => import("@/testing/componentStubs"));
const stubs = vi.hoisted(() => ({
  catalog: null as unknown,
  catalogRetries: 0,
  isMobile: false,
  mapView: null as unknown,
  mapViewInputs: null as unknown,
}));

vi.mock("@/features/map/MapView/MapView", stubModule("MapView"));
vi.mock("@/features/map/LensControl/LensControl", stubModule("LensControl"));
vi.mock("@/features/map/MapOverlayControls/MapOverlayControls", stubModule("MapOverlayControls"));
vi.mock("@/features/route/RouteOutcome/RouteOutcome", stubModule("RouteOutcome"));
vi.mock("@/features/route/RouteForm/RouteForm", async (importOriginal) => {
  const react = await import("react");
  return {
    ...(await importOriginal<typeof import("@/features/route/RouteForm/RouteForm")>()),
    // 重みと除外のパネルは入力欄の中身として渡るので、描いて受け渡しを見られるようにする。
    default: stubComponent("RouteForm", (props) =>
      react.createElement(react.Fragment, null, props.weightsPanel as ReactNode, props.exclusionsPanel as ReactNode),
    ),
  };
});
vi.mock("@/features/route/RouteSettingsPanel/RouteSettingsPanel", stubModule("RouteSettingsPanel"));
vi.mock("@/features/route/RouteSettingsPanel/HardFilterPanel", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/route/RouteSettingsPanel/HardFilterPanel")>()),
  default: stubComponent("HardFilterPanel"),
}));
vi.mock("@/features/conditions/TravelBearingControl/TravelBearingControl", stubModule("TravelBearingControl"));
vi.mock("@/features/conditions/RideConditionBar/RideConditionBar", stubModule("RideConditionBar"));
vi.mock("@/features/conditions/WeatherPanel/WeatherPanel", stubModule("WeatherPanel"));
vi.mock("@/features/conditions/TodayOutlook/TodayOutlook", stubModule("TodayOutlook"));
vi.mock("@/features/conditions/WarningBadge/WarningBadge", stubModule("WarningBadgeList"));
vi.mock("@/components/HeaderMenu/HeaderMenu", stubModule("HeaderMenu"));
vi.mock("@/components/DebugConsole/DebugConsole", stubModule("DebugConsole"));
vi.mock("@/components/BottomSheet/BottomSheet", async (importOriginal) => {
  const react = await import("react");
  return {
    ...(await importOriginal<typeof import("@/components/BottomSheet/BottomSheet")>()),
    default: stubComponent(
      (props) => `BottomSheet:${String(props.title)}`,
      (props) =>
        props.open
          ? react.createElement(
              "section",
              { "aria-label": String(props.title) },
              props.headerLead as ReactNode,
              props.headerAction as ReactNode,
              props.children as ReactNode,
            )
          : null,
    ),
  };
});
vi.mock("@/hooks/useAxisCatalog", () => ({
  useAxisCatalog: () => stubs.catalog,
  retryAxisCatalogFetch: () => {
    stubs.catalogRetries += 1;
  },
}));
vi.mock("@/hooks/useIsMobile", () => ({ useIsMobile: () => stubs.isMobile }));
vi.mock("@/features/map/view/useMapView", () => ({
  useMapView: (inputs: unknown) => {
    stubs.mapViewInputs = inputs;
    return stubs.mapView;
  },
}));
vi.mock("@/features/conditions/useWeatherConditions", () => ({ useWeatherConditions: vi.fn() }));
vi.mock("@/features/route/routeApi", () => ({ generateRoutes: vi.fn() }));

function propsOf<C extends (props: never) => unknown>(name: string): Parameters<C>[0] {
  return stubProps<Parameters<C>[0]>(name);
}
const map = () => propsOf<typeof MapView>("MapView");
const form = () => propsOf<typeof RouteForm>("RouteForm");
const outcome = () => propsOf<typeof RouteOutcome>("RouteOutcome");
const sheet = (title: string) => propsOf<typeof BottomSheet>(`BottomSheet:${title}`);
const mapViewInputs = () => stubs.mapViewInputs as Parameters<typeof useMapView>[0];
const badgeFailures = () => propsOf<typeof WarningBadgeList>("WarningBadgeList").failures ?? [];

const NOW = new Date("2026-09-25T03:02:00Z");
const HERE: Coordinates = { latitude: 35, longitude: 139 };
const NEAR: Coordinates = { latitude: 35.1, longitude: 139 };

const catalogWith = (clientTuning: Record<string, number>): AxisCatalog =>
  axisCatalogFromResponse([catalogEntry({ axis_id: "axis_a", default_weight: 1 })], {}, clientTuning, []);
const SPLICE_TUNING = { [CLIENT_TUNING_IDS.minStretchKm]: 0.2 };

function conditionsOf(overrides: Partial<GenerationConditions> = {}): GenerationConditions {
  return {
    latitude: 0,
    longitude: 0,
    distance_km: 0,
    distance_tolerance_km: 0,
    route_preference: {},
    penalty_strength: 0,
    max_average_grade_percent: null,
    hard_filters: {},
    max_routes: 0,
    start_time: "",
    assumed_speed_kmh: 0,
    waypoints: null,
    destination: null,
    corrected_destination: null,
    generated_at: "",
    ...overrides,
  };
}
function respond(routes: RouteCandidate[], conditions: Partial<GenerationConditions> = {}) {
  vi.mocked(generateRoutes).mockResolvedValueOnce({ routes, conditions: conditionsOf(conditions) });
}
const route = (id: string, overrides: Partial<RouteCandidate> = {}) => makeRouteCandidate({ id, ...overrides });
function lastRequest() {
  const call = vi.mocked(generateRoutes).mock.lastCall;
  if (!call) throw new Error("生成を呼んでいない");
  return call[0];
}

const geolocation = {
  getCurrentPosition: vi.fn<(onSuccess: PositionCallback, onError?: PositionErrorCallback | null) => void>(),
};
function answerHere() {
  geolocation.getCurrentPosition.mockImplementation((onSuccess) =>
    onSuccess({ coords: { latitude: HERE.latitude, longitude: HERE.longitude } } as GeolocationPosition),
  );
}

function renderPage(): UserEvent {
  const user = userEvent.setup();
  render(<Home />);
  return user;
}
const generateButton = () => screen.getByRole("button", { name: "ルート生成" });
async function generate(user: UserEvent) {
  await user.click(generateButton());
  await waitFor(() => expect(generateButton()).toBeEnabled());
}
const settingsSection = () => screen.getByRole("button", { name: "ルート設定" });
const outcomeSection = () => screen.getByRole("button", { name: "ルート結果" });
async function generateToDestination(user: UserEvent, routes: RouteCandidate[]) {
  act(() => form().onRouteModeChange("destination"));
  act(() => map().onPinPlace("destination", NEAR));
  respond(routes);
  await generate(user);
}

const EMPTY_WEATHER = {
  weather: null,
  weatherLoading: false,
  weatherError: null,
  amedas: null,
  amedasLoading: false,
  amedasError: null,
  warningBadgeItems: [],
  warningFetchFailures: [],
};

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  stubs.catalog = catalogWith(SPLICE_TUNING);
  stubs.catalogRetries = 0;
  stubs.isMobile = false;
  stubs.mapView = {
    look: { marker: "見え方" },
    lensControl: { marker: "レンズ" },
    overlayControls: { marker: "チップ" },
    bulk: {
      anyLayerOn: false,
      hideAllLayers: vi.fn(),
      anyLegendHidden: false,
      showAllLegendRows: vi.fn(),
      redraw: vi.fn(),
    },
    lens: LENS_DIFFICULTY_ID,
  };
  vi.mocked(useWeatherConditions).mockReset().mockReturnValue(EMPTY_WEATHER);
  vi.mocked(generateRoutes)
    .mockReset()
    .mockImplementation(async () => ({ routes: [route("route-0")], conditions: conditionsOf() }));
  Object.defineProperty(window.navigator, "geolocation", { value: geolocation, configurable: true });
  geolocation.getCurrentPosition.mockReset();
  answerHere();
  setResearchEnabled(false);
});

afterEach(() => {
  vi.useRealTimers();
  setResearchEnabled(false);
});

describe("区分とサイドバー（デスクトップ）", () => {
  it("区分の開閉は開き直しても保つ", async () => {
    const user = userEvent.setup();
    const first = render(<Home />);
    await user.click(settingsSection());
    await user.click(outcomeSection());
    first.unmount();
    render(<Home />);
    expect(settingsSection()).toHaveAttribute("aria-expanded", "false");
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "false");
  });

  it("サイドバーは閉じると区分を隠し、開き直すと戻す", async () => {
    const user = renderPage();
    await user.click(screen.getByRole("button", { name: "パネルを閉じる" }));
    expect(screen.queryByRole("button", { name: "ルート設定" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "パネルを開く" }));
    expect(settingsSection()).toBeInTheDocument();
  });
});

describe("生成の条件の受け渡し", () => {
  it("入力欄・重み・除外のパネルへ生成の条件を渡し、そこで変えた値で生成する", async () => {
    const user = renderPage();
    act(() => form().onDistanceChange("45"));
    act(() => propsOf<typeof RouteSettingsPanel>("RouteSettingsPanel").onOverrideEnabledChange(true));
    expect(form().distance).toBe("45");
    expect(propsOf<typeof RouteSettingsPanel>("RouteSettingsPanel")).toMatchObject({
      routePreference: { axis_a: 1 },
      overrideEnabled: true,
    });
    const filters = propsOf<typeof HardFilterPanel>("HardFilterPanel").hardFilters;
    await generate(user);
    expect(lastRequest()).toMatchObject({ distance_km: 45, route_preference: { axis_a: 1 }, hard_filters: filters });
  });

  it("入力欄の出発地の行は、位置が手で置いたものか・実際の位置かと、現在地の取り直しを受け取る", async () => {
    renderPage();
    await waitFor(() => expect(form().originLocated).toBe(true));
    expect(form().originManual).toBe(false);
    act(() => map().onPinPlace("origin", NEAR));
    expect(form().originManual).toBe(true);
    act(() => form().onOriginReset());
    await waitFor(() => expect(form().originManual).toBe(false));
  });

  it("地図で置いた出発地から生成する", async () => {
    const user = renderPage();
    act(() => map().onPinPlace("origin", NEAR));
    await generate(user);
    expect(lastRequest()).toMatchObject({ latitude: NEAR.latitude, longitude: NEAR.longitude });
  });

  it("目的地の間だけ、置いた経由地・目的地を地図へ渡す。地図での動かす・消すが置いた点に効く", async () => {
    renderPage();
    act(() => form().onRouteModeChange("destination"));
    act(() => map().onPinPlace("waypoint", HERE));
    act(() => map().onPinPlace("destination", NEAR));
    expect(map()).toMatchObject({ waypoints: [HERE], destination: NEAR });
    act(() => map().onWaypointMove(0, NEAR));
    expect(map().waypoints).toEqual([NEAR]);
    act(() => map().onWaypointRemove(0));
    act(() => map().onDestinationClear());
    expect(map()).toMatchObject({ waypoints: [], destination: null });

    act(() => map().onPinPlace("destination", NEAR));
    act(() => form().onRouteModeChange("loop"));
    expect(map()).toMatchObject({ waypoints: [], destination: null });
    expect(form().destinationSet).toBe(true);
  });
});

describe("走行条件の受け渡し", () => {
  it("走行方位・出発時刻・想定速度は、地図の見え方・地図・生成リクエストが同じ値を読む", async () => {
    const user = renderPage();
    const pinned = new Date("2026-09-26T00:30:00Z");
    act(() => propsOf<typeof TravelBearingControl>("TravelBearingControl").onChange(90));
    act(() => propsOf<typeof RideConditionBar>("RideConditionBar").onDepartureTimeChange(pinned));
    act(() => propsOf<typeof RideConditionBar>("RideConditionBar").onSpeedKmhChange(25));
    const ride = { bearingDeg: 90, at: pinned, speedKmh: 25 };
    expect(mapViewInputs().ride).toEqual(ride);
    expect(map().rideConditions).toEqual(ride);
    expect(propsOf<typeof TravelBearingControl>("TravelBearingControl").value).toBe(90);
    expect(propsOf<typeof RideConditionBar>("RideConditionBar")).toMatchObject({ departureTime: pinned, speedKmh: 25 });
    await generate(user);
    expect(lastRequest()).toMatchObject({ start_time: pinned.toISOString(), assumed_speed_kmh: 25 });

    act(() => propsOf<typeof RideConditionBar>("RideConditionBar").onDepartureNow());
    expect(map().rideConditions?.at).not.toEqual(pinned);
  });
});

describe("生成と結果の受け渡し", () => {
  it("「ルート結果」の中身へ結果・生成・乗り換えといまの重みを渡す", () => {
    renderPage();
    expect(outcome()).toMatchObject({ currentWeights: { axis_a: 1 } });
    expect(outcome().results.routes).toEqual([]);
    expect(outcome().generation.running).toBe(false);
    expect(outcome().splice.panel).toBeNull();
  });

  it("生成した候補を地図と「ルート結果」へ渡し、地図の見え方へ候補を選んだか・区間まで確定したか・使われた重みを渡す", async () => {
    const user = renderPage();
    const detailed = route("route-0", { segments: [{} as RouteSegmentDetail] });
    respond([detailed], { route_preference: { axis_a: 0.4 } });
    await generate(user);
    expect(map().routes).toEqual([detailed]);
    expect(map().selectedRouteId).toBe("route-0");
    expect(outcome().results.routes).toEqual([detailed]);
    expect(mapViewInputs()).toMatchObject({ hasSelectedRoute: true, hasDetail: true, usedWeights: { axis_a: 0.4 } });
    expect(map().routePreference).toBeNull();
  });

  it("地図の塗る軸を生成に渡す", async () => {
    stubs.mapView = { ...(stubs.mapView as object), lens: "axis_a" };
    const user = renderPage();
    await generate(user);
    expect(lastRequest()).toMatchObject({ lens_axis_id: "axis_a" });
  });

  it("生成の実行中は、進み方を「ルート生成」ボタンに出して押せなくする", async () => {
    let report: ((progress: { status: "queued" | "running"; elapsedMs: number }) => void) | undefined;
    vi.mocked(generateRoutes).mockImplementationOnce((_request, onProgress) => {
      report = onProgress;
      return new Promise(() => {});
    });
    const user = renderPage();
    await user.click(generateButton());
    const running = screen.getByRole("button", { name: "生成中..." });
    expect(running).toBeDisabled();
    expect(running).toHaveTextContent("生成中");
    act(() => report?.({ status: "queued", elapsedMs: 0 }));
    expect(running).toHaveAccessibleName("順番待ち...");
    expect(running).toHaveTextContent("順番待ち");
  });

  it("作った後に条件を変えると、「ルート生成」の隣に印を付ける", async () => {
    const user = renderPage();
    await generate(user);
    expect(screen.queryByRole("img", { name: "生成条件が変更されています" })).not.toBeInTheDocument();
    act(() => form().onDistanceChange("45"));
    expect(screen.getByRole("img", { name: "生成条件が変更されています" })).toBeInTheDocument();
  });

  it("候補0件の後は、条件を変えても変わったとは知らせない（比べる候補が無い）", async () => {
    const user = renderPage();
    respond([]);
    await generate(user);
    act(() => form().onDistanceChange("45"));
    expect(screen.queryByRole("img", { name: "生成条件が変更されています" })).not.toBeInTheDocument();
    expect(outcome().generation.conditionsDirty).toBe(false);
  });

  it.each([
    ["候補0件", () => respond([])],
    ["生成の失敗", () => vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混み合っています"))],
  ])("%sは「ルート結果」でしか見えないので、閉じていても開く", async (_c, arrange) => {
    localStorage.setItem("ridecompass:outcome-open", "false");
    const user = renderPage();
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "false");
    arrange();
    await generate(user);
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "true");
  });

  it("入力の誤りも「ルート結果」を開いて知らせる", async () => {
    localStorage.setItem("ridecompass:outcome-open", "false");
    const user = renderPage();
    act(() => form().onRouteModeChange("destination"));
    await user.click(generateButton());
    expect(generateRoutes).not.toHaveBeenCalled();
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "true");
  });

  it("「全消去」は候補がある間だけ出し、押すと地図と「ルート結果」から候補を消す。地点は消さない", async () => {
    const user = renderPage();
    expect(screen.queryByRole("button", { name: "候補を全消去" })).not.toBeInTheDocument();
    await generateToDestination(user, [route("route-0")]);
    await user.click(screen.getByRole("button", { name: "候補を全消去" }));
    expect(map().routes).toEqual([]);
    expect(outcome().results.routes).toEqual([]);
    expect(outcome().generation.failure).toBeNull();
    expect(map().destination).toEqual(NEAR);
  });

  it("「全消去」はシートの閉じる✕と見分けられるよう、✕の字ではなくアイコンと名前で出す", async () => {
    const user = renderPage();
    await generate(user);
    const clear = screen.getByRole("button", { name: "候補を全消去" });
    expect(clear).toHaveTextContent("全消去");
    expect(clear.textContent).not.toMatch(/[×✕✖]/);
    expect(clear.querySelector("svg")).not.toBeNull();
  });

  it("実験スロットは研究モードで「比較」を見ている間だけ地図へ重ねる", async () => {
    setResearchEnabled(true);
    const user = renderPage();
    await generate(user);
    expect(map().experimentSlots).toEqual([]);
    act(() => outcome().results.selectTab("comparison"));
    expect(map().experimentSlots).toHaveLength(1);
    expect(map().selectedRouteId).toBe("route-0");
  });
});

describe("地図で扱える操作（デスクトップ）", () => {
  it("地点を置けるのは「ルート設定」の「条件」タブが見えている間の目的地モードだけ", async () => {
    const user = renderPage();
    act(() => form().onRouteModeChange("destination"));
    expect(map()).toMatchObject({ armedPinRole: "destination", pointEditingEnabled: true });

    await user.click(screen.getByRole("tab", { name: "重み" }));
    expect(map()).toMatchObject({ armedPinRole: null, pointEditingEnabled: false });
    await user.click(screen.getByRole("tab", { name: "条件" }));
    await user.click(settingsSection());
    expect(map()).toMatchObject({ armedPinRole: null, pointEditingEnabled: false });
  });

  it("周回の間は置く役割を選んでいても地図のタップを置く操作にしない", () => {
    renderPage();
    act(() => form().onArmPinRole("waypoint"));
    expect(map().armedPinRole).toBeNull();
    expect(form().armedPinRole).toBe("waypoint");
  });

  it("区間を選べるのは「ルート結果」が見えている間だけ", async () => {
    const user = renderPage();
    await generate(user);
    const selection = { segment: {} as RouteSegmentDetail, latitude: 35, longitude: 139 };
    await user.click(outcomeSection());
    act(() => map().onRouteSegmentSelect?.(selection));
    expect(map().selectedRouteSegment).toBeNull();
    await user.click(outcomeSection());
    act(() => map().onRouteSegmentSelect?.(selection));
    expect(map().selectedRouteSegment).toBe(selection);
    expect(outcome().results.selectedRouteSegment).toBe(selection);
  });

  it("サイドバーを閉じている間は、区分が開いていても地図で地点も区間も扱わない", async () => {
    const user = renderPage();
    act(() => form().onRouteModeChange("destination"));
    await user.click(screen.getByRole("button", { name: "パネルを閉じる" }));
    expect(map()).toMatchObject({ pointEditingEnabled: false, armedPinRole: null });
    act(() => map().onRouteSegmentSelect?.({ segment: {} as RouteSegmentDetail, latitude: 0, longitude: 0 }));
    expect(map().selectedRouteSegment).toBeNull();
  });
});

describe("区間の乗り換えの受け渡し", () => {
  // 2本は同じ地点（n0〜n3）で交わり、真ん中の区間だけ別の道を通る。
  const NODES = ["n0", "n1", "n2", "n3"];
  const ROUTES = [
    route("route-0", {
      estimated_duration_seconds: 600,
      edge_ids: ["e1", "a1", "e2"],
      node_ids: NODES,
      edge_point_offsets: [0, 1, 2, 3],
      geometry: {
        type: "LineString",
        coordinates: [
          [0, 0],
          [1, 0],
          [2, 0],
          [3, 0],
        ],
      },
    }),
    route("route-1", {
      estimated_duration_seconds: 900,
      edge_ids: ["e1", "b1", "e2"],
      node_ids: NODES,
      edge_point_offsets: [0, 1, 3, 4],
      geometry: {
        type: "LineString",
        coordinates: [
          [0, 0],
          [1, 0],
          [1.5, 1],
          [2, 0],
          [3, 0],
        ],
      },
    }),
  ];

  it("編集を始めると、地図へ乗り換えの値を渡し、地点の操作と区間の選択を止める。やめると戻す", async () => {
    const user = renderPage();
    await generateToDestination(user, ROUTES);
    expect(outcome().splice.canStart).toBe(true);
    act(() => outcome().splice.start("route-0"));
    expect(map().splicedRoute).toEqual(ROUTES[0].geometry.coordinates);
    expect(map().onSpliceStretchSelect).toEqual(expect.any(Function));
    expect(map().pointEditingEnabled).toBe(false);
    act(() => map().onRouteSegmentSelect?.({ segment: {} as RouteSegmentDetail, latitude: 0, longitude: 0 }));
    expect(map().selectedRouteSegment).toBeNull();

    act(() => outcome().splice.panel?.onCancel());
    expect(map().splicedRoute).toBeNull();
    expect(map().pointEditingEnabled).toBe(true);
  });

  it("編集中に「全消去」を押すと編集も終わって地点の操作が戻り、作り直せばまた編集に入れる", async () => {
    const user = renderPage();
    await generateToDestination(user, ROUTES);
    act(() => outcome().splice.start("route-0"));
    await user.click(screen.getByRole("button", { name: "候補を全消去" }));
    expect(outcome().splice.panel).toBeNull();
    expect(map().splicedRoute).toBeNull();
    expect(map().pointEditingEnabled).toBe(true);

    respond(ROUTES);
    await generate(user);
    expect(outcome().splice.panel).toBeNull();
    act(() => outcome().splice.start("route-0"));
    expect(outcome().splice.panel?.appliedCount).toBe(0);
  });

  it("作り直すと編集を終える（作り直した候補のidが同じでも、前の編集を残さない）", async () => {
    const user = renderPage();
    await generateToDestination(user, ROUTES);
    act(() => outcome().splice.start("route-0"));
    respond(ROUTES);
    await generate(user);
    expect(outcome().splice.panel).toBeNull();
    expect(map().pointEditingEnabled).toBe(true);
  });

  it("作ると一覧へ入れて選び、閉じていた「ルート結果」を開く。直前の生成の失敗の文言は消す", async () => {
    const user = renderPage();
    await generateToDestination(user, ROUTES);
    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混み合っています"));
    await generate(user);
    expect(outcome().generation.failure).toBe("混み合っています");

    act(() => outcome().splice.start("route-0"));
    const [stretch] = map().spliceStretches ?? [];
    act(() => map().onSpliceStretchSelect?.(stretch.index));
    // 閉じると中身ごと外れるので、作る操作は閉じる前に受け取っておく。
    const apply = outcome().splice.panel?.onApply;
    await user.click(outcomeSection());
    respond([route("made", { edge_ids: ["e1", "x", "e2"], estimated_duration_seconds: 700 })]);
    await act(async () => apply?.());
    expect(outcome().results.routes.map((r) => r.id)).toEqual(["route-0", `${SPLICED_ROUTE_ID_PREFIX}-2`, "route-1"]);
    expect(map().selectedRouteId).toBe(`${SPLICED_ROUTE_ID_PREFIX}-2`);
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "true");
    expect(outcome().generation.failure).toBeNull();
  });
});

describe("モバイルの下部タブとシート", () => {
  beforeEach(() => {
    stubs.isMobile = true;
  });
  const tab = (name: string) =>
    within(screen.getByRole("navigation", { name: "パネル切り替え" })).getByRole("button", { name });

  it("タブを押すとそのシートを開き、同じタブをもう一度押すと閉じる。シートは1枚ずつ開く", async () => {
    const user = renderPage();
    await user.click(tab("ルート設定"));
    expect(sheet("ルート設定").open).toBe(true);
    await user.click(tab("ルート結果"));
    expect(sheet("ルート設定").open).toBe(false);
    expect(sheet("ルート結果").open).toBe(true);
    expect(tab("ルート結果")).toHaveAttribute("aria-expanded", "true");
    await user.click(tab("ルート結果"));
    expect(sheet("ルート結果").open).toBe(false);
  });

  it("シートの側から閉じても地図だけの状態へ戻る", async () => {
    const user = renderPage();
    await user.click(tab("ルート設定"));
    act(() => sheet("ルート設定").onClose());
    expect(sheet("ルート設定").open).toBe(false);
    await user.click(tab("ルート結果"));
    act(() => sheet("ルート結果").onClose());
    expect(sheet("ルート結果").open).toBe(false);
    expect(tab("ルート結果")).toHaveAttribute("aria-expanded", "false");
  });

  it("「ルート設定」シートは見出しの行にタブと「ルート生成」を置き、「ルート結果」シートは候補がある間だけ「全消去」を置く", async () => {
    const user = renderPage();
    await user.click(tab("ルート設定"));
    const settings = screen.getByRole("region", { name: "ルート設定" });
    expect(within(settings).getByRole("tablist", { name: "ルート設定" })).toBeInTheDocument();
    expect(within(settings).getByRole("button", { name: "ルート生成" })).toBeInTheDocument();
    expect(sheet("ルート結果").headerAction).toBeUndefined();
    await user.click(within(settings).getByRole("button", { name: "ルート生成" }));
    await waitFor(() => expect(sheet("ルート結果").headerAction).toBeDefined());
  });

  it("新しい結果・失敗・条件の変更を「ルート結果」タブの印で知らせ、失敗だけ色を変える。タブを開くと新着の印は消える", async () => {
    const user = renderPage();
    await user.click(tab("ルート設定"));
    const settings = () => screen.getByRole("region", { name: "ルート設定" });
    await user.click(within(settings()).getByRole("button", { name: "ルート生成" }));
    await waitFor(() => expect(tab("ルート結果")).toHaveAttribute("aria-description", "新しい結果があります"));

    await user.click(tab("ルート結果"));
    expect(tab("ルート結果")).not.toHaveAttribute("aria-description");
    await user.click(tab("ルート設定"));
    act(() => form().onDistanceChange("45"));
    expect(tab("ルート結果")).toHaveAttribute("aria-description", "生成条件が変更されています");

    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混み合っています"));
    await user.click(within(settings()).getByRole("button", { name: "ルート生成" }));
    await waitFor(() => expect(tab("ルート結果")).toHaveAttribute("aria-description", "生成に失敗しました"));
    const dot = tab("ルート結果").querySelector('span[aria-hidden="true"]') as HTMLElement;
    for (const token of dotVariants({ tone: "error" }).split(" ")) expect(dot.className).toContain(token);
  });

  it("シートの高さは2枚で共有し、操作中の高さはすぐ反映し、確定した高さだけを保存して自動の調整をやめる", async () => {
    const user = renderPage();
    await user.click(tab("ルート設定"));
    expect(sheet("ルート設定")).toMatchObject({ heightVh: DEFAULT_SHEET_HEIGHT_VH, autoFitHeight: true });
    act(() => sheet("ルート設定").onHeightChange(60));
    expect(sheet("ルート結果").heightVh).toBe(60);
    expect(localStorage.getItem("ridecompass:mobile-sheet-height-vh")).toBeNull();
    act(() => sheet("ルート設定").onHeightCommit?.(70));
    expect(sheet("ルート結果")).toMatchObject({ heightVh: 70, autoFitHeight: false });
    expect(localStorage.getItem("ridecompass:mobile-sheet-height-vh")).toBe("70");
  });

  it.each([
    ["範囲の外", "999", 80],
    ["数でない", '"high"', DEFAULT_SHEET_HEIGHT_VH],
    ["読めない", "{high", DEFAULT_SHEET_HEIGHT_VH],
  ])("保存した高さが%sなら、範囲へ寄せるか既定の高さで始める", (_c, stored, expected) => {
    localStorage.setItem("ridecompass:mobile-sheet-height-vh", stored);
    renderPage();
    expect(sheet("ルート設定").heightVh).toBe(expected);
  });

  it("「ルート設定」シートは、タブかモードが変わると中身が別物になったとして高さを合わせ直す", async () => {
    const user = renderPage();
    await user.click(tab("ルート設定"));
    expect(sheet("ルート設定").fitKey).toBe("generate:loop");
    await user.click(screen.getByRole("tab", { name: "除外" }));
    act(() => form().onRouteModeChange("destination"));
    expect(sheet("ルート設定").fitKey).toBe("exclusions:destination");
  });

  it("ルートを地図へ収めるときは、下部タブとシートが覆う高さを地図へ渡す", async () => {
    const user = renderPage();
    expect(map().measureRouteFitObscuredPx?.()).toEqual({ bottom: 0 });
    await user.click(tab("ルート結果"));
    expect(map().measureRouteFitObscuredPx?.()).toEqual({
      bottom: (window.innerHeight * DEFAULT_SHEET_HEIGHT_VH) / 100,
    });
  });

  it("地図で地点を扱えるのは「ルート設定」シートの「条件」タブを開いている間、区間を選べるのは「ルート結果」シートを開いている間", async () => {
    const user = renderPage();
    expect(map().pointEditingEnabled).toBe(false);
    await user.click(tab("ルート設定"));
    act(() => form().onRouteModeChange("destination"));
    expect(map()).toMatchObject({ pointEditingEnabled: true, armedPinRole: "destination" });
    const selection = { segment: {} as RouteSegmentDetail, latitude: 0, longitude: 0 };
    act(() => map().onRouteSegmentSelect?.(selection));
    expect(map().selectedRouteSegment).toBeNull();
    await user.click(tab("ルート結果"));
    expect(map().pointEditingEnabled).toBe(false);
    act(() => map().onRouteSegmentSelect?.(selection));
    expect(map().selectedRouteSegment).toBe(selection);
  });
});

describe("画面の枠と地図の周り", () => {
  it("デスクトップでは、ルートを地図へ収めるときに覆われた高さを渡さない", () => {
    renderPage();
    expect(map().measureRouteFitObscuredPx?.()).toBeUndefined();
  });

  it("地図の見え方の値を地図・レンズ・地図上チップへそのまま渡す", () => {
    renderPage();
    expect(map().look).toEqual({ marker: "見え方" });
    expect(propsOf<typeof LensControl>("LensControl")).toEqual({ marker: "レンズ" });
    expect(propsOf<typeof MapOverlayControls>("MapOverlayControls")).toEqual({ marker: "チップ" });
  });

  it("表示中のレイヤーも隠した段も無い間は、まとめて消す・解除するを押せない。描き直しはいつでも押せる", async () => {
    const bulk = (stubs.mapView as { bulk: Record<string, unknown> }).bulk;
    const user = renderPage();
    expect(screen.getByRole("button", { name: "表示中のレイヤーをすべて非表示にする" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "絞り込みをすべて解除する" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "地図の表示を再描画する" }));
    expect(bulk.redraw).toHaveBeenCalled();
  });

  it("表示中のレイヤー・隠した段があれば、まとめて消す・解除するを地図の見え方へ伝える", async () => {
    const current = stubs.mapView as { bulk: Record<string, unknown> };
    const bulk: Record<string, unknown> = { ...current.bulk, anyLayerOn: true, anyLegendHidden: true };
    stubs.mapView = { ...current, bulk };
    const user = renderPage();
    await user.click(screen.getByRole("button", { name: "表示中のレイヤーをすべて非表示にする" }));
    await user.click(screen.getByRole("button", { name: "絞り込みをすべて解除する" }));
    expect(bulk.hideAllLayers).toHaveBeenCalled();
    expect(bulk.showAllLegendRows).toHaveBeenCalled();
  });

  it("ヘッダーの天気・実測・警報は、位置が決まってからその位置で取り、取れた値をそのまま渡す", async () => {
    const weather = {
      ...EMPTY_WEATHER,
      weather: { marker: "今日" },
      amedas: { marker: "実測" },
      warningBadgeItems: [{ id: "w" }],
    };
    vi.mocked(useWeatherConditions).mockReturnValue(weather as never);
    renderPage();
    await waitFor(() => expect(vi.mocked(useWeatherConditions).mock.lastCall).toEqual([HERE, true]));
    expect(propsOf<typeof WeatherPanel>("WeatherPanel").amedas).toEqual({ marker: "実測" });
    expect(propsOf<typeof TodayOutlook>("TodayOutlook").weather).toEqual({ marker: "今日" });
    expect(propsOf<typeof WarningBadgeList>("WarningBadgeList").items).toEqual([{ id: "w" }]);
  });

  it("現在地が分からない間は天候・警報を取らず、ヘッダーの印に「現在地」を出して、そこから取り直せる", async () => {
    geolocation.getCurrentPosition.mockImplementation((_ok, onError) => onError?.({} as GeolocationPositionError));
    renderPage();
    await waitFor(() => expect(badgeFailures().map((f) => f.id)).toEqual(["location"]));
    expect(vi.mocked(useWeatherConditions).mock.lastCall?.[1]).toBe(false);
    answerHere();
    act(() => badgeFailures()[0].onRetry?.());
    await waitFor(() => expect(badgeFailures()).toEqual([]));
  });

  it("警報の取得失敗と、軸一覧を取得できないことをヘッダーの印に並べ、軸一覧はそこから取り直せる", async () => {
    stubs.catalog = { ...EMPTY_CATALOG, failed: true };
    vi.mocked(useWeatherConditions).mockReturnValue({
      ...EMPTY_WEATHER,
      warningFetchFailures: [{ id: "warnings", label: "警報", effect: "" }],
    } as never);
    renderPage();
    await waitFor(() => expect(badgeFailures().map((f) => f.id)).toEqual(["warnings", "axis-catalog"]));
    act(() => badgeFailures()[1].onRetry?.());
    expect(stubs.catalogRetries).toBe(1);
  });

  it("メニューからデバッグログを開閉し、コンソールの側からも閉じられる", () => {
    renderPage();
    expect(propsOf<typeof DebugConsole>("DebugConsole").open).toBe(false);
    act(() => propsOf<typeof HeaderMenu>("HeaderMenu").onToggleDebugConsole());
    expect(propsOf<typeof HeaderMenu>("HeaderMenu").debugConsoleOpen).toBe(true);
    expect(propsOf<typeof DebugConsole>("DebugConsole").open).toBe(true);
    act(() => propsOf<typeof DebugConsole>("DebugConsole").onClose());
    expect(propsOf<typeof DebugConsole>("DebugConsole").open).toBe(false);
  });

  it("現在地の取り直しは、待つ間は押せず、失敗したら理由を地図の上に出す", async () => {
    const user = renderPage();
    let fail: (() => void) | undefined;
    geolocation.getCurrentPosition.mockImplementation((_ok, onError) => {
      fail = () => onError?.({} as GeolocationPositionError);
    });
    await user.click(screen.getByRole("button", { name: "現在地に移動" }));
    expect(screen.getByRole("button", { name: "現在地に移動" })).toBeDisabled();
    act(() => fail?.());
    expect(screen.getByRole("button", { name: "現在地に移動" })).toBeEnabled();
    expect(screen.getByText(/現在地を取得できませんでした/)).toBeInTheDocument();
  });
});
