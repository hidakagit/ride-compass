/**
 * トップページ（`app/page.tsx`）——画面の状態の持ち主として、何を保存し、子の部品へ何を渡し、子から上がった
 * 操作で何を変えるか。
 *
 * ここで見ないもの:
 * - 生成リクエストのpayloadと「条件が変わった」の比較キーの組み立て規則 → `features/route/generationRequest.ts`
 * - 重み・除外の保存値を今の軸・項目へ揃える規則 → `features/route/routePreferenceSync.ts`・`hardFilterSync.ts`
 * - 乗り換えの区間の求め方・合成した候補の並べ方 → `features/route/routeSplice.ts`
 * - 候補の行の最速の印と所要時間・「+N分」・負荷の帯の高さの決め方 → `features/route/routeTabLabel.ts`・`difficultyLoadBar.ts`
 * - 入力の検証の文言 → `features/route/RouteForm/useRouteFormSubmit.ts`
 * - 位置の取得の並走と文言 → `hooks/useLocation.ts`
 *
 * 差し替えた部品と、それで見えなくなるもの:
 * - 地図（`MapView`）・地図の見え方（`useMapView`）・レンズ（`LensControl`）・地図上チップ（`MapOverlayControls`）:
 *   渡す値と、地図から上がる操作だけを見る。MapLibreでの描画、地図のタップがどの操作として上がるか、
 *   レイヤー・凡例の状態の持ち方は見えない。
 * - 下部シート（`BottomSheet`）: 開閉・見出しへの差し込み・渡す高さだけを見る。ドラッグとキー操作、
 *   中身に合わせた高さの自動調整は見えない。
 * - 候補の中身（`RouteAxisProfile`）・区間の内訳の帯（`AxisContributionBar`）・比較表（`ComparisonPanel`）・
 *   重みと除外のパネル・走行方位と走行条件の部品・ヘッダーの天気と警報とメニュー・デバッグコンソール:
 *   渡す値と、上がる操作だけを見る。部品自身の表示は見えない。
 * - 軸カタログ・材料カタログ・天気の取得・ルート生成の通信・GPXの書き出し・位置情報（`navigator.geolocation`）・
 *   スマホ幅の判定（`useIsMobile`）: 返す値をテストが決める。取得の失敗の扱い・CSSの`--is-mobile`との対応は見えない。
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "./page";
import type AxisContributionBar from "@/components/AxisContributionBar/AxisContributionBar";
import { DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import type BottomSheet from "@/components/BottomSheet/BottomSheet";
import type DebugConsole from "@/components/DebugConsole/DebugConsole";
import type HeaderMenu from "@/components/HeaderMenu/HeaderMenu";
import type RideConditionBar from "@/features/conditions/RideConditionBar/RideConditionBar";
import type TodayOutlook from "@/features/conditions/TodayOutlook/TodayOutlook";
import type TravelBearingControl from "@/features/conditions/TravelBearingControl/TravelBearingControl";
import type WarningBadgeList from "@/features/conditions/WarningBadge/WarningBadge";
import type WeatherPanel from "@/features/conditions/WeatherPanel/WeatherPanel";
import { useWeatherConditions } from "@/features/conditions/useWeatherConditions";
import type LensControl from "@/features/map/LensControl/LensControl";
import type MapOverlayControls from "@/features/map/MapOverlayControls/MapOverlayControls";
import type MapView from "@/features/map/MapView/MapView";
import type { useMapView } from "@/features/map/view/useMapView";
import type ComparisonPanel from "@/features/route/ComparisonPanel/ComparisonPanel";
import type RouteAxisProfile from "@/features/route/RouteAxisProfile/RouteAxisProfile";
import { DEFAULT_HARD_FILTERS } from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import type HardFilterPanel from "@/features/route/RouteSettingsPanel/HardFilterPanel";
import type RouteSettingsPanel from "@/features/route/RouteSettingsPanel/RouteSettingsPanel";
import { downloadGpx } from "@/features/route/gpxExport";
import { generateRoutes, type GenerationProgress } from "@/features/route/routeApi";
import { SPLICED_ROUTE_ID_PREFIX } from "@/features/route/routeTabLabel";
import { axisCatalogFromResponse, CLIENT_TUNING_IDS, EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";
import { catalogEntry } from "@/lib/mapDisplay/__fixtures__/catalogAxes";
import { LENS_DIFFICULTY_ID, LENS_NONE_ID } from "@/lib/mapDisplay/routeStyleModes";
import { setResearchEnabled } from "@/lib/researchMode";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import { EXPERIMENT_SLOT_COLORS, MAX_EXPERIMENT_SLOTS } from "@/types/experimentSlot";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { Coordinates, GenerationConditions, RouteCandidate, RouteSegmentDetail } from "@/types/route";

// 差し替えた部品は、描かれている間の最新のpropsを名前で引けるようにする（外れたら引けなくなる）。
const stubs = vi.hoisted(() => {
  const mounted = new Map<string, { token: object; props: Record<string, unknown> }>();
  return {
    mounted,
    catalog: null as unknown,
    materials: [] as unknown[],
    isMobile: false,
    mapView: null as unknown,
    mapViewInputs: null as unknown,
    component(
      react: typeof import("react"),
      nameOf: (props: Record<string, unknown>) => string,
      draw: (props: Record<string, unknown>) => ReactNode = () => null,
    ) {
      return function Stub(props: Record<string, unknown>) {
        const [token] = react.useState(() => ({}));
        const name = nameOf(props);
        react.useLayoutEffect(() => {
          mounted.set(name, { token, props });
        });
        react.useLayoutEffect(
          () => () => {
            if (mounted.get(name)?.token === token) mounted.delete(name);
          },
          [name, token],
        );
        return draw(props);
      };
    },
  };
});

function stubModule(name: string) {
  return async () => ({ default: stubs.component(await import("react"), () => name) });
}

vi.mock("@/features/map/MapView/MapView", stubModule("MapView"));
vi.mock("@/features/map/LensControl/LensControl", stubModule("LensControl"));
vi.mock("@/features/map/MapOverlayControls/MapOverlayControls", stubModule("MapOverlayControls"));
vi.mock("@/features/route/RouteAxisProfile/RouteAxisProfile", stubModule("RouteAxisProfile"));
vi.mock("@/features/route/ComparisonPanel/ComparisonPanel", stubModule("ComparisonPanel"));
vi.mock("@/components/AxisContributionBar/AxisContributionBar", stubModule("AxisContributionBar"));
vi.mock("@/features/route/RouteSettingsPanel/RouteSettingsPanel", stubModule("RouteSettingsPanel"));
vi.mock("@/features/conditions/TravelBearingControl/TravelBearingControl", stubModule("TravelBearingControl"));
vi.mock("@/features/conditions/RideConditionBar/RideConditionBar", stubModule("RideConditionBar"));
vi.mock("@/features/conditions/WeatherPanel/WeatherPanel", stubModule("WeatherPanel"));
vi.mock("@/features/conditions/TodayOutlook/TodayOutlook", stubModule("TodayOutlook"));
vi.mock("@/features/conditions/WarningBadge/WarningBadge", stubModule("WarningBadgeList"));
vi.mock("@/components/HeaderMenu/HeaderMenu", stubModule("HeaderMenu"));
vi.mock("@/components/DebugConsole/DebugConsole", stubModule("DebugConsole"));
vi.mock("@/features/route/RouteSettingsPanel/HardFilterPanel", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/route/RouteSettingsPanel/HardFilterPanel")>()),
  default: stubs.component(await import("react"), () => "HardFilterPanel"),
}));
vi.mock("@/components/BottomSheet/BottomSheet", async (importOriginal) => {
  const react = await import("react");
  return {
    ...(await importOriginal<typeof import("@/components/BottomSheet/BottomSheet")>()),
    default: stubs.component(
      react,
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
vi.mock("@/hooks/useAxisCatalog", () => ({ useAxisCatalog: () => stubs.catalog }));
vi.mock("@/hooks/useMaterialCatalog", () => ({
  useMaterialCatalog: () => ({ materials: stubs.materials, loaded: true }),
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
vi.mock("@/features/route/gpxExport", () => ({ downloadGpx: vi.fn() }));

function propsOf<C extends (props: never) => unknown>(name: string): Parameters<C>[0] {
  const entry = stubs.mounted.get(name);
  if (!entry) throw new Error(`${name}が描かれていない`);
  return entry.props as Parameters<C>[0];
}
const map = () => propsOf<typeof MapView>("MapView");
const profile = () => propsOf<typeof RouteAxisProfile>("RouteAxisProfile");
const comparison = () => propsOf<typeof ComparisonPanel>("ComparisonPanel");
const weightsPanel = () => propsOf<typeof RouteSettingsPanel>("RouteSettingsPanel");
const exclusionsPanel = () => propsOf<typeof HardFilterPanel>("HardFilterPanel");
const bearingControl = () => propsOf<typeof TravelBearingControl>("TravelBearingControl");
const rideBar = () => propsOf<typeof RideConditionBar>("RideConditionBar");
const sheet = (title: string) => propsOf<typeof BottomSheet>(`BottomSheet:${title}`);
const mapViewInputs = () => stubs.mapViewInputs as Parameters<typeof useMapView>[0];

// 生成は5分刻みの「今」を出発時刻として送る。
const NOW = new Date("2026-09-25T03:02:00Z");
const NOW_STEPPED = new Date("2026-09-25T03:00:00Z");
const PINNED = new Date("2026-09-26T00:30:00Z");

const HERE: Coordinates = { latitude: 35, longitude: 139 };
// 緯度0.1度はおよそ11.1km、1度はおよそ111km。
const NEAR: Coordinates = { latitude: 35.1, longitude: 139 };
const HALFWAY: Coordinates = { latitude: 35.05, longitude: 139 };
const FAR: Coordinates = { latitude: 36, longitude: 139 };

const AXES = [
  catalogEntry({ axis_id: "axis_a" }),
  catalogEntry({ axis_id: "axis_b" }),
  catalogEntry({ axis_id: "axis_c" }),
];
const SPLICE_TUNING = { [CLIENT_TUNING_IDS.minStretchKm]: 0.2 };
const catalogWith = (clientTuning: Record<string, number>): AxisCatalog =>
  axisCatalogFromResponse(AXES, {}, clientTuning, []);
const catalog = () => stubs.catalog as AxisCatalog;

const [FIRST_FILTER] = Object.keys(DEFAULT_HARD_FILTERS);
const FLIPPED_FILTERS = { ...DEFAULT_HARD_FILTERS, [FIRST_FILTER]: !DEFAULT_HARD_FILTERS[FIRST_FILTER] };
const WEIGHTS = { axis_a: 0.5, axis_b: 0.25, axis_c: 0 };

function route(id: string, overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return makeRouteCandidate({ id, ...overrides });
}

function segment(overrides: Partial<RouteSegmentDetail> = {}): RouteSegmentDetail {
  return {
    geometry: null,
    start_latitude: 0,
    start_longitude: 0,
    end_latitude: 0,
    end_longitude: 0,
    cumulative_distance_km: 0,
    distance_km: 0,
    estimated_arrival_time: null,
    axis_difficulties: {},
    axis_contributions: {},
    material_values: {},
    axis_raw_values: {},
    difficulty: null,
    wind: null,
    ...overrides,
  };
}

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
    generated_at: "",
    ...overrides,
  };
}

type GenerateResult = Awaited<ReturnType<typeof generateRoutes>>;

function respond(routes: RouteCandidate[], conditions: Partial<GenerationConditions> = {}, reason?: string) {
  vi.mocked(generateRoutes).mockResolvedValueOnce({
    routes,
    conditions: conditionsOf(conditions),
    noCandidatesReason: reason,
  });
}

function deferred() {
  let resolve!: (result: GenerateResult) => void;
  const promise = new Promise<GenerateResult>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

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
const resultTabs = () => within(screen.getByRole("tablist", { name: "ルート結果" })).getAllByRole("tab");
const settingsSection = () => screen.getByRole("button", { name: "ルート設定" });
const outcomeSection = () => screen.getByRole("button", { name: "ルート結果" });

async function chooseDestinationMode(user: UserEvent) {
  await user.click(screen.getByRole("radio", { name: "目的地" }));
}
async function generateToDestination(user: UserEvent, routes: RouteCandidate[]) {
  await chooseDestinationMode(user);
  act(() => map().onPinPlace("destination", NEAR));
  respond(routes);
  await generate(user);
}

// 3本とも同じ地点（n0〜n5）で交わる。AとCは1つ目の分かれ道だけ、AとBは両方の分かれ道で別の道を通る。
const NODES = ["n0", "n1", "n2", "n3", "n4", "n5"];
/** 経度・緯度を交互に並べた数の列を、座標の列にする。 */
function pointsOf(flat: number[]): GeoJSON.Position[] {
  return Array.from({ length: flat.length / 2 }, (_, i) => [flat[2 * i], flat[2 * i + 1]]);
}
const lineOf = (flat: number[]) => ({ type: "LineString" as const, coordinates: pointsOf(flat) });
const ROUTE_A = route("route-0", {
  distance_km: 10,
  overall_difficulty: 30,
  edge_ids: ["e1", "a1", "e2", "a2", "e3"],
  node_ids: NODES,
  edge_point_offsets: [0, 1, 2, 3, 4, 5],
  geometry: lineOf([0, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5, 0]),
});
const ROUTE_B = route("route-1", {
  distance_km: 12,
  overall_difficulty: 40,
  edge_ids: ["e1", "b1", "e2", "b2", "e3"],
  node_ids: NODES,
  edge_point_offsets: [0, 1, 3, 4, 6, 7],
  geometry: lineOf([0, 0, 1, 0, 1.5, 1, 2, 0, 3, 0, 3.5, 1, 4, 0, 5, 0]),
});
const ROUTE_C = route("route-2", {
  distance_km: 11,
  overall_difficulty: 50,
  edge_ids: ["e1", "c1", "e2", "a2", "e3"],
  node_ids: NODES,
  edge_point_offsets: [0, 1, 3, 4, 5, 6],
  geometry: lineOf([0, 0, 1, 0, 1.5, -1, 2, 0, 3, 0, 4, 0, 5, 0]),
});
// Bの1つ目・2つ目の分かれ道、Cの分かれ道を通る点。
const B_FIRST: GeoJSON.Position = [1.5, 1];
const B_SECOND: GeoJSON.Position = [3.5, 1];
const C_FIRST: GeoJSON.Position = [1.5, -1];

async function startSpliceEditing(user: UserEvent, routes = [ROUTE_A, ROUTE_B, ROUTE_C]) {
  await generateToDestination(user, routes);
  await user.click(screen.getByRole("button", { name: "ルートを合成" }));
}
function passed<T>(value: T | undefined, what: string): T {
  if (value === undefined) throw new Error(`地図へ${what}を渡していない`);
  return value;
}
const spliceStretches = () => passed(map().spliceStretches, "乗り換え先");
const measureObscured = () => passed(map().measureRouteFitObscuredPx, "覆われた高さを測る関数")();
function chooseStretchThrough(point: GeoJSON.Position) {
  const found = spliceStretches().find((stretch) =>
    stretch.coordinates.some(([x, y]) => x === point[0] && y === point[1]),
  );
  if (!found) throw new Error(`${point.join(",")}を通る乗り換え先が無い`);
  const select = passed(map().onSpliceStretchSelect, "乗り換え先の選択");
  act(() => select(found.index));
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
  stubs.materials = [];
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
  vi.mocked(downloadGpx).mockReset();
  Object.defineProperty(window.navigator, "geolocation", { value: geolocation, configurable: true });
  geolocation.getCurrentPosition.mockReset();
  answerHere();
  setResearchEnabled(false);
});

afterEach(() => {
  vi.useRealTimers();
  setResearchEnabled(false);
});

describe("生成条件の保存と復元", () => {
  it("操作した生成条件は開き直しても同じ値で送り、置いた地点と選んだ出発時刻は持ち越さない", async () => {
    let user = renderPage();
    fireEvent.change(screen.getByLabelText("距離"), { target: { value: "45" } });
    await user.click(screen.getByRole("button", { name: "候補数を増やす" }));
    act(() => weightsPanel().onOverrideEnabledChange(true));
    act(() => weightsPanel().onRoutePreferenceChange(WEIGHTS));
    act(() => exclusionsPanel().onHardFiltersChange(FLIPPED_FILTERS));
    act(() => rideBar().onSpeedKmhChange(25));
    act(() => rideBar().onDepartureTimeChange(PINNED));
    await chooseDestinationMode(user);
    act(() => map().onPinPlace("destination", NEAR));
    cleanup();

    user = renderPage();
    expect(screen.getByRole("radio", { name: "目的地" })).toHaveAttribute("aria-checked", "true");
    expect(map().destination).toBeNull();
    expect(rideBar().departureTime).toEqual(NOW_STEPPED);
    await user.click(screen.getByRole("radio", { name: "周回" }));
    await generate(user);
    expect(lastRequest()).toMatchObject({
      distance_km: 45,
      max_routes: routeGenerateConfig.default_max_routes + 1,
      route_preference: WEIGHTS,
      hard_filters: FLIPPED_FILTERS,
      assumed_speed_kmh: 25,
      start_time: NOW_STEPPED.toISOString(),
    });
  });

  it.each([
    ["下限", "1", "1", routeGenerateConfig.min_assumed_speed_kmh],
    [
      "上限",
      String(routeGenerateConfig.max_distance_km),
      String(routeGenerateConfig.max_routes),
      routeGenerateConfig.max_assumed_speed_kmh,
    ],
  ])("距離・候補数・想定速度の保存値は、%sちょうどでも復元して送る", async (_bound, distance, maxRoutes, speed) => {
    localStorage.setItem("ridecompass:distance-km", distance);
    localStorage.setItem("ridecompass:max-routes", maxRoutes);
    localStorage.setItem("ridecompass:assumed-speed-kmh", String(speed));
    const user = renderPage();
    await generate(user);
    expect(lastRequest()).toMatchObject({
      distance_km: Number(distance),
      max_routes: Number(maxRoutes),
      assumed_speed_kmh: speed,
    });
  });

  it.each([
    ["距離が0", "ridecompass:distance-km", "0"],
    ["距離が上限を超える", "ridecompass:distance-km", String(routeGenerateConfig.max_distance_km + 1)],
    ["距離が数でない", "ridecompass:distance-km", "abc"],
    ["候補数が0", "ridecompass:max-routes", "0"],
    ["候補数が上限を超える", "ridecompass:max-routes", String(routeGenerateConfig.max_routes + 1)],
    ["候補数が整数でない", "ridecompass:max-routes", "2.5"],
    ["想定速度が下限未満", "ridecompass:assumed-speed-kmh", String(routeGenerateConfig.min_assumed_speed_kmh - 1)],
    ["想定速度が上限を超える", "ridecompass:assumed-speed-kmh", String(routeGenerateConfig.max_assumed_speed_kmh + 1)],
    ["想定速度が整数でない", "ridecompass:assumed-speed-kmh", "20.5"],
    ["モードが知らない値", "ridecompass:route-mode", "circle"],
    ["除外がJSONとして読めない", "ridecompass:hard-filters", "{"],
  ])("%sの保存値は捨て、保存値が無いときと同じ値を送る", async (_case, key, raw) => {
    let user = renderPage();
    await generate(user);
    const withoutStored = lastRequest();
    cleanup();

    localStorage.setItem(key, raw);
    user = renderPage();
    await generate(user);
    expect(lastRequest()).toEqual(withoutStored);
  });

  it("保存した除外に今は無い項目が混じっていても、今の項目へ揃えて送る", async () => {
    localStorage.setItem("ridecompass:hard-filters", JSON.stringify({ ...FLIPPED_FILTERS, retired_filter: true }));
    const user = renderPage();
    await generate(user);
    expect(lastRequest().hard_filters).toEqual(FLIPPED_FILTERS);
  });

  it("区分の開閉は開き直しても保つ", async () => {
    const user = renderPage();
    await user.click(settingsSection());
    await user.click(outcomeSection());
    cleanup();

    renderPage();
    expect(settingsSection()).toHaveAttribute("aria-expanded", "false");
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("radio", { name: "周回" })).not.toBeInTheDocument();
  });
});

describe("生成リクエスト", () => {
  it("周回は、いまの位置・距離・候補数・走行条件・除外を送り、地点・重み・塗る軸は送らない", async () => {
    const user = renderPage();
    fireEvent.change(screen.getByLabelText("距離"), { target: { value: "45" } });
    await user.click(screen.getByRole("button", { name: "候補数を増やす" }));
    await generate(user);
    const request = lastRequest();
    expect(request).toMatchObject({
      latitude: HERE.latitude,
      longitude: HERE.longitude,
      distance_km: 45,
      distance_tolerance_km: routeGenerateConfig.default_distance_tolerance_km,
      max_routes: routeGenerateConfig.default_max_routes + 1,
      assumed_speed_kmh: routeGenerateConfig.default_assumed_speed_kmh,
      start_time: NOW_STEPPED.toISOString(),
      hard_filters: DEFAULT_HARD_FILTERS,
    });
    expect(request.waypoints).toBeUndefined();
    expect(request.destination).toBeUndefined();
    expect(request.route_preference).toBeUndefined();
    expect(request.lens_axis_id).toBeUndefined();
  });

  it("目的地は距離を送らず（探索の範囲はbackendが置いた点から決める）、経由地を置いた順に送る", async () => {
    const user = renderPage();
    await chooseDestinationMode(user);
    await user.click(screen.getByRole("button", { name: "経由地を追加" }));
    act(() => map().onPinPlace("waypoint", NEAR));
    act(() => map().onPinPlace("waypoint", { latitude: 35.02, longitude: 139 }));
    await user.click(screen.getByRole("button", { name: "目的地を地図で選ぶ" }));
    act(() => map().onPinPlace("destination", HALFWAY));
    await generate(user);
    expect(lastRequest()).toMatchObject({
      waypoints: [NEAR, { latitude: 35.02, longitude: 139 }],
      destination: HALFWAY,
      max_routes: routeGenerateConfig.routes_with_waypoints,
    });
    expect(lastRequest().distance_km).toBeUndefined();
  });

  it("経由地の無い目的地は、候補数の入力をそのまま送る", async () => {
    const user = renderPage();
    await chooseDestinationMode(user);
    act(() => map().onPinPlace("destination", NEAR));
    await user.click(screen.getByRole("button", { name: "候補数を増やす" }));
    await generate(user);
    expect(lastRequest().max_routes).toBe(routeGenerateConfig.default_max_routes + 1);
  });

  it("目的地を置かず経由地だけでも、距離も目的地も送らない", async () => {
    const user = renderPage();
    await chooseDestinationMode(user);
    await user.click(screen.getByRole("button", { name: "経由地を追加" }));
    act(() => map().onPinPlace("waypoint", NEAR));
    await generate(user);
    expect(lastRequest()).toMatchObject({ waypoints: [NEAR] });
    expect(lastRequest().distance_km).toBeUndefined();
    expect(lastRequest().destination).toBeUndefined();
  });

  it("周回へ戻すと置いた点を地図にも出さず送らず、目的地へ戻すと置いた点をそのまま出す", async () => {
    const user = renderPage();
    await chooseDestinationMode(user);
    await user.click(screen.getByRole("button", { name: "経由地を追加" }));
    act(() => map().onPinPlace("waypoint", HALFWAY));
    act(() => map().onPinPlace("destination", NEAR));

    await user.click(screen.getByRole("radio", { name: "周回" }));
    expect(map().waypoints).toEqual([]);
    expect(map().destination).toBeNull();
    await generate(user);
    expect(lastRequest().waypoints).toBeUndefined();
    expect(lastRequest().destination).toBeUndefined();
    expect(lastRequest().distance_km).toBe(30);

    await chooseDestinationMode(user);
    expect(map().waypoints).toEqual([HALFWAY]);
    expect(map().destination).toEqual(NEAR);
  });

  it.each([
    ["レンズが色分けなし", LENS_NONE_ID, true, undefined],
    ["レンズが総合難易度", LENS_DIFFICULTY_ID, true, undefined],
    ["軸カタログが届く前に軸を選んでいる", "axis_a", false, undefined],
    ["軸カタログが届いてから軸を選んでいる", "axis_a", true, "axis_a"],
  ])("塗る軸を送るか（%s）", async (_case, lens, loaded, expected) => {
    stubs.catalog = loaded ? catalogWith(SPLICE_TUNING) : EMPTY_CATALOG;
    (stubs.mapView as { lens: string }).lens = lens;
    const user = renderPage();
    await generate(user);
    expect(lastRequest().lens_axis_id).toBe(expected);
  });

  it("重みは、利用者が上書きを有効にした後だけ送る", async () => {
    const user = renderPage();
    await generate(user);
    expect(lastRequest().route_preference).toBeUndefined();

    act(() => weightsPanel().onOverrideEnabledChange(true));
    act(() => weightsPanel().onRoutePreferenceChange(WEIGHTS));
    expect(weightsPanel()).toMatchObject({ overrideEnabled: true, routePreference: WEIGHTS });
    await generate(user);
    expect(lastRequest().route_preference).toEqual(WEIGHTS);
  });

  it("重みを上書きしていても、軸カタログが届いていない間は送らない（届いた軸へ合わせられない）", async () => {
    stubs.catalog = EMPTY_CATALOG;
    const user = renderPage();
    act(() => weightsPanel().onOverrideEnabledChange(true));
    act(() => weightsPanel().onRoutePreferenceChange(WEIGHTS));
    await generate(user);
    expect(lastRequest().route_preference).toBeUndefined();
  });

  it("「除外」タブで変えた除外を、タブへ戻しつつ送る", async () => {
    const user = renderPage();
    act(() => exclusionsPanel().onHardFiltersChange(FLIPPED_FILTERS));
    expect(exclusionsPanel().hardFilters).toEqual(FLIPPED_FILTERS);
    await generate(user);
    expect(lastRequest().hard_filters).toEqual(FLIPPED_FILTERS);
  });

  it("走行方位・出発時刻・想定速度は、地図の見え方・地図・生成リクエストが同じ値を読む", async () => {
    const user = renderPage();
    expect(rideBar().departureTime).toEqual(NOW_STEPPED);
    expect(mapViewInputs().now).toEqual(NOW_STEPPED);

    act(() => bearingControl().onChange(90));
    act(() => rideBar().onSpeedKmhChange(25));
    act(() => rideBar().onDepartureTimeChange(PINNED));
    const ride = { bearingDeg: 90, at: PINNED, speedKmh: 25 };
    expect(mapViewInputs().ride).toEqual(ride);
    expect(map().rideConditions).toEqual(ride);
    expect(bearingControl().value).toBe(90);
    expect(rideBar()).toMatchObject({ departureTime: PINNED, speedKmh: 25 });
    await generate(user);
    expect(lastRequest()).toMatchObject({ assumed_speed_kmh: 25, start_time: PINNED.toISOString() });

    act(() => rideBar().onDepartureNow());
    expect(rideBar().departureTime).toEqual(NOW_STEPPED);
  });
});

describe("地点の指定", () => {
  it("目的地へ切り替えたとき、まだ何も置いていなければ次のタップで目的地を置けるようにし、周回へ戻すとやめる", async () => {
    const user = renderPage();
    expect(map().armedPinRole).toBeNull();
    await chooseDestinationMode(user);
    expect(map().armedPinRole).toBe("destination");
    await user.click(screen.getByRole("radio", { name: "周回" }));
    expect(map().armedPinRole).toBeNull();
  });

  it.each([
    ["目的地", "目的地を地図で選ぶ", "destination"],
    ["経由地", "経由地を追加", "waypoint"],
  ] as const)("%sを置いてあれば、目的地へ切り替えても自動では置けるようにしない", async (_label, rowName, role) => {
    const user = renderPage();
    await chooseDestinationMode(user);
    if (role === "waypoint") await user.click(screen.getByRole("button", { name: rowName }));
    act(() => map().onPinPlace(role, NEAR));
    await user.click(screen.getByRole("radio", { name: "周回" }));
    await chooseDestinationMode(user);
    expect(map().armedPinRole).toBeNull();
  });

  it("置いてある目的地の行を押すと、目的地を消さずに次のタップで置き直せる状態にする", async () => {
    const user = renderPage();
    await chooseDestinationMode(user);
    act(() => map().onPinPlace("destination", NEAR));
    expect(map().armedPinRole).toBeNull();
    await user.click(screen.getByRole("button", { name: "目的地を置き直す" }));
    expect(map().armedPinRole).toBe("destination");
    expect(map().destination).toEqual(NEAR);
  });

  it("出発地を地図で置くと手で決めた位置として送り、置いたら置く状態をやめる。「現在地に戻す」で取り直す", async () => {
    const user = renderPage();
    await chooseDestinationMode(user);
    await user.click(screen.getByRole("button", { name: "出発地を地図で選ぶ" }));
    expect(map().armedPinRole).toBe("origin");
    act(() => map().onPinPlace("origin", HALFWAY));
    expect(map().armedPinRole).toBeNull();
    expect(map()).toMatchObject({ location: HALFWAY, locationSource: "manual" });
    act(() => map().onPinPlace("destination", NEAR));
    await generate(user);
    expect(lastRequest()).toMatchObject({ latitude: HALFWAY.latitude, longitude: HALFWAY.longitude });

    const requestsBefore = geolocation.getCurrentPosition.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "出発地を現在地に戻す" }));
    expect(geolocation.getCurrentPosition).toHaveBeenCalledTimes(requestsBefore + 1);
    expect(map()).toMatchObject({ location: HERE, locationSource: "geolocation" });
  });

  it("経由地は置いたあとも続けて置け、目的地は1つ置いたら置く状態をやめる", async () => {
    const user = renderPage();
    await chooseDestinationMode(user);
    await user.click(screen.getByRole("button", { name: "経由地を追加" }));
    act(() => map().onPinPlace("waypoint", HALFWAY));
    expect(map().armedPinRole).toBe("waypoint");
    act(() => map().onPinPlace("waypoint", NEAR));
    expect(map().waypoints).toEqual([HALFWAY, NEAR]);

    await user.click(screen.getByRole("button", { name: "目的地を地図で選ぶ" }));
    act(() => map().onPinPlace("destination", FAR));
    expect(map().armedPinRole).toBeNull();
    expect(map().destination).toEqual(FAR);
  });

  it("地図での経由地の移動・削除と目的地の削除、フォームのクリアが、地図へ渡す地点に効く", async () => {
    const user = renderPage();
    await chooseDestinationMode(user);
    await user.click(screen.getByRole("button", { name: "経由地を追加" }));
    act(() => map().onPinPlace("waypoint", HALFWAY));
    act(() => map().onPinPlace("waypoint", NEAR));
    act(() => map().onWaypointMove(0, FAR));
    expect(map().waypoints).toEqual([FAR, NEAR]);
    act(() => map().onWaypointRemove(1));
    expect(map().waypoints).toEqual([FAR]);
    await user.click(screen.getByRole("button", { name: "経由地をクリア" }));
    expect(map().waypoints).toEqual([]);

    act(() => map().onPinPlace("destination", NEAR));
    act(() => map().onDestinationClear());
    expect(map().destination).toBeNull();
    act(() => map().onPinPlace("destination", NEAR));
    await user.click(screen.getByRole("button", { name: "目的地をクリア" }));
    expect(map().destination).toBeNull();
  });

  it("地図で地点を扱えるのは、「ルート設定」の「条件」タブが見えている間だけ", async () => {
    const user = renderPage();
    await chooseDestinationMode(user);
    expect(map()).toMatchObject({ pointEditingEnabled: true, armedPinRole: "destination" });

    await user.click(screen.getByRole("tab", { name: "重み" }));
    expect(map()).toMatchObject({ pointEditingEnabled: false, armedPinRole: null });
    await user.click(screen.getByRole("tab", { name: "条件" }));
    expect(map()).toMatchObject({ pointEditingEnabled: true, armedPinRole: "destination" });

    await user.click(settingsSection());
    expect(map()).toMatchObject({ pointEditingEnabled: false, armedPinRole: null });
  });
});

describe("生成の進み方と、結果の置き場", () => {
  it("生成の実行中は、進み方を「ルート生成」ボタンと「ルート結果」に出し、ボタンを押せなくする", async () => {
    let report: ((progress: GenerationProgress) => void) | undefined;
    const pending = deferred();
    vi.mocked(generateRoutes).mockImplementationOnce((_request, onProgress) => {
      report = onProgress;
      return pending.promise;
    });
    const user = renderPage();
    await user.click(generateButton());
    const running = screen.getByRole("button", { name: /生成中|順番待ち/ });
    expect(running).toBeDisabled();
    expect(running).toHaveTextContent("生成中");

    act(() => report?.({ status: "queued", elapsedMs: 0 }));
    expect(running).toHaveTextContent("順番待ち");
    act(() => report?.({ status: "running", elapsedMs: 1500 }));
    expect(running).toHaveAccessibleName("生成中...(2秒経過)");
    expect(screen.getByText("生成中...(2秒経過)")).toBeInTheDocument();

    await act(async () => pending.resolve({ routes: [route("route-0")], conditions: conditionsOf() }));
    expect(generateButton()).toBeEnabled();
  });

  it.each([
    ["届いた", "対象の道が見つかりません", "対象の道が見つかりません"],
    ["届かない", undefined, "条件に合うルート候補が見つかりませんでした。距離を変えて試してください。"],
  ])("候補0件は、理由が%sとき「ルート結果」にその理由を出し、閉じていても開く", async (_case, reason, shown) => {
    localStorage.setItem("ridecompass:outcome-open", "false");
    respond([], {}, reason);
    const user = renderPage();
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "false");
    await generate(user);
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(shown);
  });

  it.each([
    ["Error", new Error("通信に失敗しました"), "通信に失敗しました"],
    ["Error以外", "壊れた応答", "不明なエラーが発生しました"],
  ])("生成が%sで失敗したら「ルート結果」に出し、閉じていても開く", async (_case, failure, shown) => {
    localStorage.setItem("ridecompass:outcome-open", "false");
    vi.mocked(generateRoutes).mockRejectedValueOnce(failure);
    const user = renderPage();
    await generate(user);
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(shown);
  });

  it("候補がある間に作り直しが失敗したら、前の候補を残したまま先頭に失敗を出し、条件が変わった旨は重ねない", async () => {
    const user = renderPage();
    await generate(user);
    fireEvent.change(screen.getByLabelText("距離"), { target: { value: "45" } });
    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混み合っています"));
    await generate(user);
    expect(resultTabs()).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent("作り直せませんでした。混み合っています");
    expect(screen.queryByText("生成条件が変更されています")).not.toBeInTheDocument();

    await generate(user);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("作り直しの失敗は「全消去」で消え、生成前の案内へ持ち越さない", async () => {
    const user = renderPage();
    await generate(user);
    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混み合っています"));
    await generate(user);
    await user.click(screen.getByRole("button", { name: "候補を全消去" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("「生成」を押すと候補がここに並びます")).toBeInTheDocument();
  });

  it("入力の誤りは生成の失敗と同じ場所に出して閉じていても開き、直前の生成の案内より先に出す", async () => {
    respond([], {}, "直前の理由");
    const user = renderPage();
    await generate(user);
    await user.click(outcomeSection());
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "false");

    await chooseDestinationMode(user);
    await user.click(generateButton());
    expect(generateRoutes).toHaveBeenCalledTimes(1);
    expect(outcomeSection()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("alert")).not.toHaveTextContent("直前の理由");
  });

  it("生成前の「ルート結果」は、押せば候補が並ぶことを案内する", () => {
    renderPage();
    expect(screen.getByText("「生成」を押すと候補がここに並びます")).toBeInTheDocument();
  });

  it("backendが目的地を補正したら、ピンを補正後の地点へ動かして知らせ、条件が変わったとは扱わない", async () => {
    const corrected = { latitude: 35.1001, longitude: 139.0005 };
    const user = renderPage();
    await chooseDestinationMode(user);
    act(() => map().onPinPlace("destination", NEAR));
    respond([route("route-0")], { corrected_destination: corrected });
    await generate(user);
    expect(map().destination).toEqual(corrected);
    expect(
      screen.getByText("指定した地点は自転車で行けない場所だったため、近くのアクセス可能な地点へ補正しました。"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "生成条件が変更されています" })).not.toBeInTheDocument();
  });
});

describe("候補の一覧", () => {
  it("候補は所要時間の短い順に並び、行には順位・距離、最も早く着く候補にその所要時間と「最速」の印、他の候補に余計にかかる時間を添える", async () => {
    respond([
      route("route-0", { distance_km: 10, estimated_duration_seconds: 3600 }),
      route("route-1", { distance_km: 12.34, estimated_duration_seconds: 3900 }),
      route("route-2", { distance_km: 8, estimated_duration_seconds: 3620 }),
    ]);
    const user = renderPage();
    await generate(user);
    // 並びは所要時間の短い順（backendの並びとは別）。番号は並びどおりに振り直す。
    const [first, second, third] = resultTabs();
    expect(first).toHaveTextContent(/^1 10\.0km1時間0分—$/);
    expect(within(first).getByRole("img", { name: "最速" })).toBeInTheDocument();
    expect(within(second).queryByRole("img", { name: "最速" })).not.toBeInTheDocument();
    expect(second).toHaveTextContent(/^2 8\.0km—$/);
    expect(third).toHaveTextContent(/^3 12\.3km\+5分—$/);
  });

  it("経由地を通るルートは順位の代わりに名前を出す", async () => {
    respond([route("route-waypoints", { direction_label: "経由地を通る", distance_km: 8 })]);
    const user = renderPage();
    await generate(user);
    expect(resultTabs()[0]).toHaveTextContent(/^経由地を通る 8\.0km—$/);
  });

  it("総合難易度は数値と帯の長さで出し、算出できなかった候補は「—」だけにする", async () => {
    respond([route("route-0", { overall_difficulty: 42.4 }), route("route-1", { overall_difficulty: null })]);
    const user = renderPage();
    await generate(user);
    const fillOf = (tab: HTMLElement) =>
      Array.from(tab.querySelectorAll<HTMLElement>("span")).find((span) => span.style.width !== "");
    const [scored, unscored] = resultTabs();
    expect(scored).toHaveTextContent(/42$/);
    expect(fillOf(scored)?.style.width).toBe("42.4%");
    expect(unscored).toHaveTextContent(/—$/);
    expect(fillOf(unscored)).toBeUndefined();
  });

  it("一覧の行の負荷の帯の高さは、一覧の最短の候補を基準にする", async () => {
    respond([route("route-0", { distance_km: 10 }), route("route-1", { distance_km: 15 })]);
    const user = renderPage();
    await generate(user);
    const ratioOf = (tab: HTMLElement) =>
      Array.from(tab.querySelectorAll<HTMLElement>("span"))
        .map((span) => span.style.getPropertyValue("--load-bar-height-ratio"))
        .find((value) => value !== "");
    const [shorter, longer] = resultTabs();
    expect(ratioOf(shorter)).toBe("1");
    expect(ratioOf(longer)).toBe("1.5");
  });

  it("選んだ候補の中身には、その候補の値と生成に使われた重みを渡し、あとで重みを変えても変えない", async () => {
    const shown = route("route-0", {
      distance_km: 10,
      overall_difficulty: 40,
      difficulty_load: 400,
      estimated_duration_seconds: 1800,
      axis_difficulties: { axis_a: 50 },
      axis_contributions: { axis_a: 40 },
      axis_raw_values: { axis_a: 3 },
      material_values: { mat: 1 },
      material_category_shares: { cat: { x: 1 } },
    });
    respond([shown], { route_preference: { axis_a: 0.7 } });
    const user = renderPage();
    await generate(user);
    act(() => weightsPanel().onRoutePreferenceChange({ axis_a: 0.1 }));
    expect(profile()).toEqual({
      axes: catalog().axes,
      weights: { axis_a: 0.7 },
      axisDifficulties: shown.axis_difficulties,
      axisContributions: shown.axis_contributions,
      axisRawValues: shown.axis_raw_values,
      materialValues: shown.material_values,
      materialCategoryShares: shown.material_category_shares,
      distanceKm: 10,
      overallDifficulty: 40,
      difficultyLoad: 400,
      estimatedDurationSeconds: 1800,
      windUnavailable: false,
      missingTravelDataShare: null,
      axisColors: catalog().axisColors,
    });
  });

  it("地図の見え方へは、候補を選んだか・区間まで確定したか・生成に使われた重みを渡す", async () => {
    const user = renderPage();
    expect(mapViewInputs()).toMatchObject({ hasSelectedRoute: false, hasDetail: false, usedWeights: null });

    respond([route("route-0", { segments: [] })], { route_preference: { axis_a: 0.7 } });
    await generate(user);
    expect(mapViewInputs()).toMatchObject({ hasSelectedRoute: true, hasDetail: false, usedWeights: { axis_a: 0.7 } });

    respond([route("route-0", { segments: [segment()] })]);
    await generate(user);
    expect(mapViewInputs().hasDetail).toBe(true);
  });

  it("「GPX出力」は選んでいる候補を書き出し、「全消去」は候補を消して生成前の案内へ戻す", async () => {
    const first = route("route-0");
    const second = route("route-1");
    respond([first, second]);
    const user = renderPage();
    await generate(user);
    await user.click(resultTabs()[1]);
    await user.click(screen.getByRole("button", { name: "GPX出力" }));
    expect(downloadGpx).toHaveBeenCalledWith(second);

    await user.click(screen.getByRole("button", { name: "候補を全消去" }));
    expect(map()).toMatchObject({ routes: [], selectedRouteId: null });
    expect(screen.getByText("「生成」を押すと候補がここに並びます")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "GPX出力" })).not.toBeInTheDocument();
  });

  it("「全消去」は、パネルを閉じる✕と見分けられるよう、✕の字ではなくアイコンで出す", async () => {
    respond([route("route-0")]);
    const user = renderPage();
    await generate(user);
    const clear = screen.getByRole("button", { name: "候補を全消去" });
    expect(clear.querySelector("svg")).not.toBeNull();
    expect(clear).not.toHaveTextContent("✕");
  });

  it("候補を作った後に条件を変えると、「ルート生成」の隣と一覧に知らせ、作り直すと消す", async () => {
    const user = renderPage();
    await generate(user);
    expect(screen.queryByRole("img", { name: "生成条件が変更されています" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("距離"), { target: { value: "45" } });
    expect(screen.getByRole("img", { name: "生成条件が変更されています" })).toBeInTheDocument();
    expect(screen.getByText("生成条件が変更されています")).toBeInTheDocument();

    await generate(user);
    expect(screen.queryByRole("img", { name: "生成条件が変更されています" })).not.toBeInTheDocument();
  });

  it("出発時刻を選ぶと、それも生成の条件として比べる", async () => {
    const user = renderPage();
    await generate(user);
    act(() => rideBar().onDepartureTimeChange(PINNED));
    expect(screen.getByRole("img", { name: "生成条件が変更されています" })).toBeInTheDocument();
  });

  it("候補0件の後は、条件を変えても変わったとは知らせない（比べる候補が無い）", async () => {
    respond([]);
    const user = renderPage();
    await generate(user);
    fireEvent.change(screen.getByLabelText("距離"), { target: { value: "45" } });
    expect(screen.queryByRole("img", { name: "生成条件が変更されています" })).not.toBeInTheDocument();
  });
});

describe("地図で押した区間", () => {
  const SEGMENT = segment({
    cumulative_distance_km: 3.24,
    estimated_arrival_time: "2026-09-25T03:04:00Z",
    axis_contributions: { axis_a: 12 },
    material_values: { mat_named: 1.5, mat_unnamed: 2 },
  });
  const pick = (picked: RouteSegmentDetail = SEGMENT) =>
    act(() => map().onRouteSegmentSelect({ segment: picked, latitude: 0, longitude: 0 }));

  it("押した区間がある間は、候補の中身の代わりにその地点・到着予想・内訳を出し、×で戻す", async () => {
    respond([route("route-0", { segments: [SEGMENT] })]);
    const user = renderPage();
    await generate(user);
    pick();
    expect(screen.getByText("3.2 km地点")).toBeInTheDocument();
    expect(screen.getByText("到達予想 12:04")).toBeInTheDocument();
    expect(propsOf<typeof AxisContributionBar>("AxisContributionBar")).toEqual({
      axes: catalog().axes,
      contributions: SEGMENT.axis_contributions,
      axisColors: catalog().axisColors,
    });
    expect(stubs.mounted.has("RouteAxisProfile")).toBe(false);
    expect(screen.queryByRole("list")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "区間の選択を解除" }));
    expect(stubs.mounted.has("RouteAxisProfile")).toBe(true);
  });

  it("到着予想が無い区間は「不明」と出す", async () => {
    respond([route("route-0", { segments: [SEGMENT] })]);
    const user = renderPage();
    await generate(user);
    pick({ ...SEGMENT, estimated_arrival_time: null });
    expect(screen.getByText("到達予想 不明")).toBeInTheDocument();
  });

  it("研究モードでは区間の材料の値を名前付きで並べ、名前を引けない材料は出さない", async () => {
    setResearchEnabled(true);
    stubs.materials = [{ id: "mat_named", label: "", name: "材料A", description: "", dtype: "numeric", unit: "m" }];
    respond([route("route-0", { segments: [SEGMENT] })]);
    const user = renderPage();
    await generate(user);
    pick();
    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(["材料A: 1.50 m"]);

    pick({ ...SEGMENT, material_values: {} });
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("「ルート結果」を見ていない間は、地図で区間を押しても選ばない", async () => {
    respond([route("route-0", { segments: [SEGMENT] })]);
    const user = renderPage();
    await generate(user);
    await user.click(outcomeSection());
    pick();
    await user.click(outcomeSection());
    expect(screen.queryByRole("button", { name: "区間の選択を解除" })).not.toBeInTheDocument();
  });

  it.each([
    [
      "候補のタブを切り替える",
      async (user: UserEvent) => {
        await user.click(resultTabs()[1]);
        await user.click(resultTabs()[0]);
      },
    ],
    [
      "作り直す",
      async (user: UserEvent) => {
        respond([route("route-0", { segments: [SEGMENT] }), route("route-1")]);
        await generate(user);
      },
    ],
    [
      "消してから作り直す",
      async (user: UserEvent) => {
        await user.click(screen.getByRole("button", { name: "候補を全消去" }));
        respond([route("route-0", { segments: [SEGMENT] }), route("route-1")]);
        await generate(user);
      },
    ],
    [
      "編集を始めてやめる",
      async (user: UserEvent) => {
        await user.click(screen.getByRole("button", { name: "ルートを合成" }));
        await user.click(screen.getByRole("button", { name: "編集をやめて候補へ戻る" }));
      },
    ],
  ])("区間の選択は、%sと外れる", async (_action, act_) => {
    const user = renderPage();
    await generateToDestination(user, [route("route-0", { segments: [SEGMENT] }), route("route-1")]);
    pick();
    expect(screen.getByRole("button", { name: "区間の選択を解除" })).toBeInTheDocument();
    await act_(user);
    expect(screen.queryByRole("button", { name: "区間の選択を解除" })).not.toBeInTheDocument();
  });
});

describe("研究モードの比較", () => {
  it("研究モードの生成だけを実験スロットへ新しい順に残し、並びの位置で色を振り直す", async () => {
    setResearchEnabled(true);
    const user = renderPage();
    const tops: RouteCandidate[] = [];
    for (let i = 0; i <= MAX_EXPERIMENT_SLOTS; i += 1) {
      const top = route(`route-${i}-0`);
      tops.push(top);
      respond([top, route(`route-${i}-1`)], { generated_at: `t${i}` });
      await generate(user);
    }
    expect(screen.getByRole("tab", { name: "比較" })).toHaveAttribute("aria-selected", "false");
    const { slots } = comparison();
    expect(slots.map((slot) => slot.conditions.generated_at)).toEqual(
      tops
        .map((_, i) => `t${i}`)
        .reverse()
        .slice(0, MAX_EXPERIMENT_SLOTS),
    );
    expect(slots.map((slot) => slot.topCandidate)).toEqual(tops.slice().reverse().slice(0, MAX_EXPERIMENT_SLOTS));
    expect(slots.map((slot) => slot.color)).toEqual(EXPERIMENT_SLOT_COLORS.slice(0, MAX_EXPERIMENT_SLOTS));
  });

  it("「全消去」は実験スロットも空にする（地図に比較の線が残らない）", async () => {
    setResearchEnabled(true);
    const user = renderPage();
    respond([route("route-a")], { generated_at: "ta" });
    await generate(user);
    await user.click(screen.getByRole("button", { name: "候補を全消去" }));
    respond([route("route-b")], { generated_at: "tb" });
    await generate(user);
    expect(comparison().slots.map((slot) => slot.topCandidate.id)).toEqual(["route-b"]);
  });

  it("候補0件の生成は実験スロットに残さない", async () => {
    setResearchEnabled(true);
    const user = renderPage();
    respond([route("route-0")], { generated_at: "t0" });
    await generate(user);
    respond([]);
    await generate(user);
    respond([route("route-0")], { generated_at: "t2" });
    await generate(user);
    expect(comparison().slots.map((slot) => slot.conditions.generated_at)).toEqual(["t2", "t0"]);
  });

  it("研究モードでない間は「比較」タブを出さず、その間の生成は後で研究モードにしても比較に並ばない", async () => {
    const user = renderPage();
    await generate(user);
    expect(screen.queryByRole("tab", { name: "比較" })).not.toBeInTheDocument();
    act(() => setResearchEnabled(true));
    expect(screen.getByRole("tab", { name: "比較" })).toBeInTheDocument();
    expect(comparison().slots).toEqual([]);
  });

  it("比較表の軸は、いずれかのスロットを作ったときの重みが正だった軸に絞る", async () => {
    setResearchEnabled(true);
    const user = renderPage();
    respond([route("route-0")], { route_preference: { axis_a: 1, axis_b: 0 } });
    await generate(user);
    respond([route("route-0")], { route_preference: { axis_b: 0.5 } });
    await generate(user);
    expect(comparison().axes.map((axis) => axis.axisId)).toEqual(["axis_a", "axis_b"]);
    expect(comparison()).toMatchObject({ axisLabels: catalog().axisLabels, materials: stubs.materials });
  });

  it("実験スロットは「比較」を見ている間だけ地図へ重ね、比較を見ている間も選んだ候補を保つ", async () => {
    setResearchEnabled(true);
    respond([route("route-0"), route("route-1")]);
    const user = renderPage();
    await generate(user);
    await user.click(resultTabs()[1]);
    expect(map().experimentSlots).toEqual([]);

    await user.click(screen.getByRole("tab", { name: "比較" }));
    expect(map().experimentSlots).toEqual(comparison().slots);
    expect(map().selectedRouteId).toBe("route-1");

    await user.click(resultTabs()[0]);
    expect(map().experimentSlots).toEqual([]);
    expect(map().selectedRouteId).toBe("route-0");
  });

  it("「比較」を開いたまま作り直すと、新しい候補のタブへ戻す", async () => {
    setResearchEnabled(true);
    const user = renderPage();
    await generate(user);
    await user.click(screen.getByRole("tab", { name: "比較" }));
    await generate(user);
    expect(screen.getByRole("tab", { name: "比較" })).toHaveAttribute("aria-selected", "false");
    expect(resultTabs()[0]).toHaveAttribute("aria-selected", "true");
    expect(map().experimentSlots).toEqual([]);
  });
});

describe("区間の乗り換え", () => {
  const editButton = () => screen.queryByRole("button", { name: "ルートを合成" });

  it.each([
    ["周回で作った2件", "loop", 2, false],
    ["目的地で作った1件", "destination", 1, false],
    ["目的地で作った2件", "destination", 2, true],
  ] as const)("編集の入口を出すか（%s）", async (_case, mode, count, shown) => {
    const routes = [ROUTE_A, ROUTE_B].slice(0, count);
    const user = renderPage();
    if (mode === "destination") {
      await generateToDestination(user, routes);
    } else {
      respond(routes);
      await generate(user);
    }
    expect(editButton() !== null).toBe(shown);
  });

  it("編集の入口は、作った後に周回へ切り替えても出し続け、編集中は出さない", async () => {
    const user = renderPage();
    await generateToDestination(user, [ROUTE_A, ROUTE_B]);
    await user.click(screen.getByRole("radio", { name: "周回" }));
    await user.click(screen.getByRole("button", { name: "ルートを合成" }));
    expect(editButton()).not.toBeInTheDocument();
  });

  it("編集を始めると、地図に元のルートと乗り換え先を渡し、地点の操作と候補の選択を止める", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    expect(map().splicedRoute).toEqual(ROUTE_A.geometry.coordinates);
    expect(spliceStretches().map((stretch) => stretch.coordinates)).toEqual(
      expect.arrayContaining([
        pointsOf([1, 0, ...B_FIRST, 2, 0]),
        pointsOf([1, 0, ...C_FIRST, 2, 0]),
        pointsOf([3, 0, ...B_SECOND, 4, 0]),
      ]),
    );
    expect(spliceStretches()).toHaveLength(3);
    expect(map().pointEditingEnabled).toBe(false);
  });

  it("編集中は、地図で区間を押しても区間を選ばない（区間の詳細の置き場が編集面に替わっている）", async () => {
    const user = renderPage();
    await startSpliceEditing(user, [{ ...ROUTE_A, segments: [segment()] }, ROUTE_B, ROUTE_C]);
    act(() => map().onRouteSegmentSelect({ segment: segment(), latitude: 0, longitude: 0 }));
    expect(screen.queryByRole("button", { name: "区間の選択を解除" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "編集をやめて候補へ戻る" })).toBeInTheDocument();
  });

  it("区間を割る下限を軸カタログから引けない間は、乗り換え先を作らない", async () => {
    stubs.catalog = catalogWith({});
    const user = renderPage();
    await startSpliceEditing(user);
    expect(spliceStretches()).toEqual([]);
  });

  it("地図で乗り換え先を押すとその道へ乗り換え、乗り換えた経路から次の乗り換え先を出す。1つ戻す・全部戻すで戻る", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(C_FIRST);
    expect(map().splicedRoute).toEqual(ROUTE_C.geometry.coordinates);
    chooseStretchThrough(B_SECOND);
    expect(map().splicedRoute).toEqual(pointsOf([0, 0, 1, 0, ...C_FIRST, 2, 0, 3, 0, ...B_SECOND, 4, 0, 5, 0]));
    expect(screen.getByText("2回")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "1つ戻す" }));
    expect(map().splicedRoute).toEqual(ROUTE_C.geometry.coordinates);
    await user.click(screen.getByRole("button", { name: "全部戻す" }));
    expect(map().splicedRoute).toEqual(ROUTE_A.geometry.coordinates);
  });

  it("「差分を見る」は、表示中の候補を作った条件へ乗り換えた経路を載せて評価し、同じ組み合わせは投げ直さない", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    const generated = lastRequest();
    act(() => rideBar().onSpeedKmhChange(30));
    chooseStretchThrough(C_FIRST);
    respond([route("route-spliced", { distance_km: 11.5 })]);
    await user.click(screen.getByRole("button", { name: "差分を見る" }));
    expect(lastRequest()).toEqual({ ...generated, spliced_edge_ids: ROUTE_C.edge_ids });
    expect(await screen.findByText("11.5km")).toBeInTheDocument();
    const requests = vi.mocked(generateRoutes).mock.calls.length;

    await user.click(screen.getByRole("button", { name: "1つ戻す" }));
    expect(screen.queryByText("11.5km")).not.toBeInTheDocument();
    chooseStretchThrough(C_FIRST);
    expect(screen.getByText("11.5km")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "差分を見る" }));
    expect(generateRoutes).toHaveBeenCalledTimes(requests);
  });

  it.each([
    ["評価の結果が空", () => respond([]), "組み合わせたルートを評価できませんでした"],
    ["Errorで失敗", () => vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("評価に失敗")), "評価に失敗"],
    [
      "Error以外で失敗",
      () => vi.mocked(generateRoutes).mockRejectedValueOnce("x"),
      "組み合わせたルートの評価に失敗しました",
    ],
  ])("「差分を見る」で%sなら編集の中に理由を出し、次に乗り換え先を選ぶと消す", async (_case, fail, shown) => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(C_FIRST);
    fail();
    await user.click(screen.getByRole("button", { name: "差分を見る" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(shown);
    chooseStretchThrough(B_SECOND);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("評価を待っている間に乗り換え先を選んでも、待っている表示は続ける", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(C_FIRST);
    const pending = deferred();
    vi.mocked(generateRoutes).mockReturnValueOnce(pending.promise);
    await user.click(screen.getByRole("button", { name: "差分を見る" }));
    chooseStretchThrough(B_SECOND);
    expect(screen.getByRole("button", { name: "差分を見る" })).toHaveAttribute("aria-busy", "true");
    await act(async () => pending.resolve({ routes: [], conditions: conditionsOf() }));
  });

  it("評価を待っている間に編集をやめたら、あとから届いた評価で編集へ戻さず、次の編集へも持ち込まない", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(C_FIRST);
    const pending = deferred();
    vi.mocked(generateRoutes).mockReturnValueOnce(pending.promise);
    await user.click(screen.getByRole("button", { name: "差分を見る" }));
    await user.click(screen.getByRole("button", { name: "編集をやめて候補へ戻る" }));
    await act(async () =>
      pending.resolve({ routes: [route("route-spliced", { distance_km: 11.5 })], conditions: conditionsOf() }),
    );
    expect(screen.queryByRole("button", { name: "編集をやめて候補へ戻る" })).not.toBeInTheDocument();
    expect(resultTabs()).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: "ルートを合成" }));
    chooseStretchThrough(C_FIRST);
    expect(screen.queryByText("11.5km")).not.toBeInTheDocument();
  });

  it("「作成」は、評価した経路を候補の一覧へ合成として加えて選び、編集を終える", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(B_FIRST);
    respond([route("route-spliced", { edge_ids: ["e1", "b1", "e2", "a2", "e3"] })]);
    await user.click(screen.getByRole("button", { name: "新しいルートを作成" }));
    const added = `${SPLICED_ROUTE_ID_PREFIX}-3`;
    await waitFor(() => expect(map().selectedRouteId).toBe(added));
    expect(map().routes.map((candidate) => candidate.id)).toHaveLength(4);
    expect(map().routes.map((candidate) => candidate.id)).toContain(added);
    expect(screen.queryByRole("button", { name: "編集をやめて候補へ戻る" })).not.toBeInTheDocument();
    const selected = resultTabs().find((tab) => tab.getAttribute("aria-selected") === "true");
    expect(selected).toHaveTextContent("合成");
  });

  it("「作成」を続けて2回押しても、候補は1本だけ増える", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(B_FIRST);
    respond([
      route("route-spliced", {
        edge_ids: ["e1", "b1", "e2", "a2", "e3"],
        node_ids: NODES,
        edge_point_offsets: [0, 1, 3, 4, 5, 6],
        geometry: lineOf([0, 0, 1, 0, 1.5, 1, 2, 0, 3, 0, 4, 0, 5, 0]),
      }),
    ]);
    const create = screen.getByRole("button", { name: "新しいルートを作成" });
    fireEvent.click(create);
    fireEvent.click(create);
    await waitFor(() => expect(map().routes).toHaveLength(4));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "編集をやめて候補へ戻る" })).not.toBeInTheDocument(),
    );
    expect(map().routes).toHaveLength(4);
  });

  it("作った合成のルートから、もう一度編集して別の候補の道へ乗り継げる", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(B_FIRST);
    respond([
      route("route-spliced", {
        edge_ids: ["e1", "b1", "e2", "a2", "e3"],
        node_ids: NODES,
        edge_point_offsets: [0, 1, 3, 4, 5, 6],
        geometry: lineOf([0, 0, 1, 0, 1.5, 1, 2, 0, 3, 0, 4, 0, 5, 0]),
      }),
    ]);
    await user.click(screen.getByRole("button", { name: "新しいルートを作成" }));
    await user.click(await screen.findByRole("button", { name: "ルートを合成" }));
    chooseStretchThrough(B_SECOND);
    expect(screen.getByText("1回")).toBeInTheDocument();
  });

  it("評価済みの組み合わせは、作るときに投げ直さない", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(B_FIRST);
    respond([route("route-spliced", { edge_ids: ["e1", "b1", "e2", "a2", "e3"] })]);
    await user.click(screen.getByRole("button", { name: "差分を見る" }));
    await screen.findByText("0.0km");
    const requests = vi.mocked(generateRoutes).mock.calls.length;
    await user.click(screen.getByRole("button", { name: "新しいルートを作成" }));
    await waitFor(() => expect(map().routes).toHaveLength(4));
    expect(generateRoutes).toHaveBeenCalledTimes(requests);
  });

  it("作った経路が既にある候補と同じ道なら、並べずにその候補を選ぶ", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(C_FIRST);
    respond([route("route-spliced", { edge_ids: ROUTE_C.edge_ids })]);
    await user.click(screen.getByRole("button", { name: "新しいルートを作成" }));
    await waitFor(() => expect(map().selectedRouteId).toBe(ROUTE_C.id));
    expect(map().routes).toHaveLength(3);
  });

  it.each([
    ["評価の結果が空", () => respond([]), "組み合わせたルートを評価できませんでした"],
    ["Errorで失敗", () => vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("評価に失敗")), "評価に失敗"],
  ])("作るときの評価が%sなら、編集を続けたまま理由を出す", async (_case, fail, shown) => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(B_FIRST);
    fail();
    await user.click(screen.getByRole("button", { name: "新しいルートを作成" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(shown);
    expect(screen.getByRole("button", { name: "編集をやめて候補へ戻る" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新しいルートを作成" })).toBeEnabled();
  });

  it("作ると、直前の生成の失敗の文言を残さない", async () => {
    const user = renderPage();
    await generateToDestination(user, [ROUTE_A, ROUTE_B, ROUTE_C]);
    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("直前の失敗"));
    await generate(user);
    await user.click(screen.getByRole("button", { name: "ルートを合成" }));
    chooseStretchThrough(B_FIRST);
    respond([route("route-spliced", { edge_ids: ["e1", "b1", "e2", "a2", "e3"] })]);
    await user.click(screen.getByRole("button", { name: "新しいルートを作成" }));
    await waitFor(() => expect(map().routes).toHaveLength(4));
    await user.click(screen.getByRole("button", { name: "候補を全消去" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("生成の実行中に作っても、生成は実行中のまま表示する", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(B_FIRST);
    const regeneration = deferred();
    vi.mocked(generateRoutes).mockReturnValueOnce(regeneration.promise);
    await user.click(generateButton());
    respond([route("route-spliced", { edge_ids: ["e1", "b1", "e2", "a2", "e3"] })]);
    await user.click(screen.getByRole("button", { name: "新しいルートを作成" }));
    await waitFor(() => expect(map().routes).toHaveLength(4));
    expect(screen.getByRole("button", { name: "生成中..." })).toBeDisabled();
    await act(async () => regeneration.resolve({ routes: [route("route-0")], conditions: conditionsOf() }));
    expect(generateButton()).toBeEnabled();
  });

  it("編集をやめると候補の一覧へ戻り、次に始めた編集は元のルートから始まる", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    chooseStretchThrough(C_FIRST);
    await user.click(screen.getByRole("button", { name: "編集をやめて候補へ戻る" }));
    expect(resultTabs()).toHaveLength(3);
    expect(map().splicedRoute).toBeNull();
    await user.click(screen.getByRole("button", { name: "ルートを合成" }));
    expect(map().splicedRoute).toEqual(ROUTE_A.geometry.coordinates);
  });

  it("作り直すと編集を終える", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    respond([ROUTE_A, ROUTE_B]);
    await generate(user);
    expect(map().splicedRoute).toBeNull();
    expect(resultTabs()).toHaveLength(2);
  });

  it("編集中に「全消去」を押すと編集も終わり、地点の操作が戻り、作り直せばまた編集に入れる", async () => {
    const user = renderPage();
    await startSpliceEditing(user);
    await user.click(screen.getByRole("button", { name: "候補を全消去" }));
    expect(screen.queryByRole("button", { name: "編集をやめて候補へ戻る" })).not.toBeInTheDocument();
    expect(map()).toMatchObject({ splicedRoute: null, pointEditingEnabled: true });
    respond([ROUTE_A, ROUTE_B, ROUTE_C]);
    await generate(user);
    expect(screen.getByRole("button", { name: "ルートを合成" })).toBeInTheDocument();
  });
});

describe("モバイルの下部タブとシート", () => {
  const nav = () => screen.getByRole("navigation", { name: "パネル切り替え" });
  const navButton = (label: string) => within(nav()).getByRole("button", { name: label });
  const hasOutcomeDot = () => navButton("ルート結果").querySelector("span[aria-hidden='true']") !== null;
  const mapPaneSheetHeight = () =>
    document.querySelector<HTMLElement>(".app-map-pane")?.style.getPropertyValue("--mobile-sheet-height");

  beforeEach(() => {
    stubs.isMobile = true;
  });

  it("タブを押すとそのシートを開き、同じタブをもう一度押すと閉じる。シートは1枚ずつ開く", async () => {
    const user = renderPage();
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
    await user.click(navButton("ルート設定"));
    expect(navButton("ルート設定")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("region", { name: "ルート設定" })).toBeInTheDocument();

    await user.click(navButton("ルート結果"));
    expect(screen.queryByRole("region", { name: "ルート設定" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "ルート結果" })).toBeInTheDocument();
    await user.click(navButton("ルート結果"));
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it.each(["ルート設定", "ルート結果"])("「%s」シートの側から閉じると、タブも閉じた状態へ戻す", async (title) => {
    const user = renderPage();
    await user.click(navButton(title));
    act(() => sheet(title).onClose());
    expect(screen.queryByRole("region", { name: title })).not.toBeInTheDocument();
    expect(navButton(title)).toHaveAttribute("aria-expanded", "false");
  });

  it("「ルート設定」シートは見出しの行にタブと「ルート生成」を置き、「ルート結果」シートは候補がある間だけ操作を置く", async () => {
    const user = renderPage();
    await user.click(navButton("ルート設定"));
    const settings = screen.getByRole("region", { name: "ルート設定" });
    expect(within(settings).getByRole("tablist", { name: "ルート設定" })).toBeInTheDocument();
    await generate(user);

    await user.click(navButton("ルート結果"));
    const outcome = screen.getByRole("region", { name: "ルート結果" });
    expect(within(outcome).getByRole("button", { name: "候補を全消去" })).toBeInTheDocument();
    await user.click(within(outcome).getByRole("button", { name: "候補を全消去" }));
    expect(within(outcome).queryByRole("button", { name: "GPX出力" })).not.toBeInTheDocument();
    expect(within(outcome).getByText("「生成」を押すと候補がここに並びます")).toBeInTheDocument();
  });

  it.each([
    ["候補が出た", () => respond([route("route-0")]), "新しい結果があります"],
    ["候補0件だった", () => respond([]), "新しい結果があります"],
    ["失敗した", () => vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("失敗")), "生成に失敗しました"],
  ])("生成して%sら「ルート結果」タブに印を付け、シートは開かず、タブを開くと消す", async (_case, prepare, meaning) => {
    const user = renderPage();
    await user.click(navButton("ルート設定"));
    prepare();
    await generate(user);
    expect(hasOutcomeDot()).toBe(true);
    expect(navButton("ルート結果")).toHaveAccessibleDescription(meaning);
    expect(screen.queryByRole("region", { name: "ルート結果" })).not.toBeInTheDocument();
    await user.click(navButton("ルート結果"));
    expect(hasOutcomeDot()).toBe(false);
  });

  it("候補がある間に作り直しが失敗したら、タブの印で失敗と分かり、「ルート結果」シートに前の候補と失敗を出す", async () => {
    const user = renderPage();
    await user.click(navButton("ルート設定"));
    await generate(user);
    await user.click(navButton("ルート結果"));
    await user.click(navButton("ルート設定"));
    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("混み合っています"));
    await generate(user);
    expect(navButton("ルート結果")).toHaveAccessibleDescription("生成に失敗しました");
    await user.click(navButton("ルート結果"));
    const outcome = screen.getByRole("region", { name: "ルート結果" });
    expect(within(outcome).getAllByRole("tab")).toHaveLength(1);
    expect(within(outcome).getByRole("alert")).toHaveTextContent("混み合っています");
  });

  it("候補を作った後に条件を変えると、「ルート結果」タブに印を付ける", async () => {
    const user = renderPage();
    await user.click(navButton("ルート設定"));
    await generate(user);
    await user.click(navButton("ルート結果"));
    await user.click(navButton("ルート設定"));
    expect(hasOutcomeDot()).toBe(false);
    fireEvent.change(screen.getByLabelText("距離"), { target: { value: "45" } });
    expect(hasOutcomeDot()).toBe(true);
    expect(navButton("ルート結果")).toHaveAccessibleDescription("生成条件が変更されています");
  });

  it("シートの高さは2枚で共有し、操作中の高さはすぐ反映し、確定した高さだけを保存して自動の調整をやめる", async () => {
    let user = renderPage();
    await user.click(navButton("ルート設定"));
    expect(sheet("ルート設定")).toMatchObject({ heightVh: DEFAULT_SHEET_HEIGHT_VH, autoFitHeight: true });
    expect(mapPaneSheetHeight()).toBe(`${DEFAULT_SHEET_HEIGHT_VH}vh`);

    act(() => sheet("ルート設定").onHeightChange(33));
    expect(sheet("ルート設定")).toMatchObject({ heightVh: 33, autoFitHeight: true });
    expect(mapPaneSheetHeight()).toBe("33vh");
    act(() => sheet("ルート設定").onHeightCommit(40));
    expect(sheet("ルート設定")).toMatchObject({ heightVh: 40, autoFitHeight: false });
    await user.click(navButton("ルート結果"));
    expect(sheet("ルート結果")).toMatchObject({ heightVh: 40, autoFitHeight: false });
    await user.click(navButton("ルート結果"));
    expect(mapPaneSheetHeight()).toBe("0px");
    cleanup();

    user = renderPage();
    await user.click(navButton("ルート結果"));
    expect(sheet("ルート結果")).toMatchObject({ heightVh: 40, autoFitHeight: false });
  });

  it.each([
    ["数でない", '"40"'],
    ["有限でない", "1e999"],
    ["JSONとして読めない", "{"],
  ])("保存した高さが%sなら捨て、既定の高さで自動の調整を続ける", async (_case, raw) => {
    localStorage.setItem("ridecompass:mobile-sheet-height-vh", raw);
    const user = renderPage();
    await user.click(navButton("ルート設定"));
    expect(sheet("ルート設定")).toMatchObject({ heightVh: DEFAULT_SHEET_HEIGHT_VH, autoFitHeight: true });
  });

  it("「ルート設定」シートは、タブかモードが変わると中身が別物になったとして高さを合わせ直す", async () => {
    const user = renderPage();
    await user.click(navButton("ルート設定"));
    const keys = [sheet("ルート設定").fitKey];
    await chooseDestinationMode(user);
    keys.push(sheet("ルート設定").fitKey);
    await user.click(screen.getByRole("tab", { name: "重み" }));
    keys.push(sheet("ルート設定").fitKey);
    expect(new Set(keys).size).toBe(3);
  });

  it("ルートを地図へ収めるときは、下部タブとシートが覆う高さを地図へ渡す", async () => {
    const original = Object.getOwnPropertyDescriptor(window, "innerHeight");
    Object.defineProperty(window, "innerHeight", { value: 1000, configurable: true });
    try {
      const user = renderPage();
      nav().getBoundingClientRect = () => ({ height: 56 }) as DOMRect;
      expect(measureObscured()).toEqual({ bottom: 56 });
      await user.click(navButton("ルート設定"));
      act(() => sheet("ルート設定").onHeightCommit(40));
      expect(measureObscured()).toEqual({ bottom: 56 + 400 });
    } finally {
      if (original) Object.defineProperty(window, "innerHeight", original);
      else Reflect.deleteProperty(window, "innerHeight");
    }
  });

  it("地図で地点を扱えるのは「ルート設定」シートの「条件」タブを開いている間、区間を選べるのは「ルート結果」シートを開いている間", async () => {
    const user = renderPage();
    await user.click(navButton("ルート設定"));
    await chooseDestinationMode(user);
    expect(map()).toMatchObject({ pointEditingEnabled: true, armedPinRole: "destination" });
    act(() => map().onPinPlace("destination", NEAR));
    respond([route("route-0", { segments: [segment()] }), route("route-1")]);
    await generate(user);
    act(() => map().onRouteSegmentSelect({ segment: segment(), latitude: 0, longitude: 0 }));

    await user.click(navButton("ルート結果"));
    expect(map().pointEditingEnabled).toBe(false);
    expect(screen.queryByRole("button", { name: "区間の選択を解除" })).not.toBeInTheDocument();
    act(() => map().onRouteSegmentSelect({ segment: segment(), latitude: 0, longitude: 0 }));
    expect(screen.getByRole("button", { name: "区間の選択を解除" })).toBeInTheDocument();
  });
});

describe("画面の枠と地図の周り", () => {
  it("デスクトップでは、ルートを地図へ収めるときに覆われた高さを渡さない", () => {
    renderPage();
    expect(measureObscured()).toBeUndefined();
  });

  it("サイドバーは閉じると区分を隠し、開き直すと戻す", async () => {
    const user = renderPage();
    await user.click(screen.getByRole("button", { name: "パネルを閉じる" }));
    expect(screen.queryByRole("button", { name: "ルート設定" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "パネルを開く" }));
    expect(settingsSection()).toBeInTheDocument();
  });

  it("サイドバーを閉じている間は、区分が開いていても地図で地点も区間も扱わず、開き直すと戻す", async () => {
    respond([route("route-0", { segments: [segment()] }), route("route-1")]);
    const user = renderPage();
    await generate(user);
    expect(map().pointEditingEnabled).toBe(true);

    await user.click(screen.getByRole("button", { name: "パネルを閉じる" }));
    expect(map().pointEditingEnabled).toBe(false);
    act(() => map().onRouteSegmentSelect({ segment: segment(), latitude: 0, longitude: 0 }));

    await user.click(screen.getByRole("button", { name: "パネルを開く" }));
    expect(map().pointEditingEnabled).toBe(true);
    expect(screen.queryByRole("button", { name: "区間の選択を解除" })).not.toBeInTheDocument();
    act(() => map().onRouteSegmentSelect({ segment: segment(), latitude: 0, longitude: 0 }));
    expect(screen.getByRole("button", { name: "区間の選択を解除" })).toBeInTheDocument();
  });

  it("地図の見え方の値を地図・レンズ・地図上チップへそのまま渡す", () => {
    renderPage();
    const view = stubs.mapView as ReturnType<typeof useMapView>;
    expect(map().look).toBe(view.look);
    expect(propsOf<typeof LensControl>("LensControl")).toEqual(view.lensControl);
    expect(propsOf<typeof MapOverlayControls>("MapOverlayControls")).toEqual(view.overlayControls);
  });

  it("表示中のレイヤーも隠した段も無い間は、まとめて消す・解除するを押せない", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "表示中のレイヤーをすべて非表示にする" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "絞り込みをすべて解除する" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "地図の表示を再描画する" })).toBeEnabled();
  });

  it("表示中のレイヤー・隠した段があれば、まとめて消す・解除する・描き直すを地図の見え方へ伝える", async () => {
    const view = stubs.mapView as ReturnType<typeof useMapView>;
    view.bulk.anyLayerOn = true;
    view.bulk.anyLegendHidden = true;
    const user = renderPage();
    await user.click(screen.getByRole("button", { name: "表示中のレイヤーをすべて非表示にする" }));
    await user.click(screen.getByRole("button", { name: "絞り込みをすべて解除する" }));
    await user.click(screen.getByRole("button", { name: "地図の表示を再描画する" }));
    expect(view.bulk.hideAllLayers).toHaveBeenCalledTimes(1);
    expect(view.bulk.showAllLegendRows).toHaveBeenCalledTimes(1);
    expect(view.bulk.redraw).toHaveBeenCalledTimes(1);
  });

  it("ヘッダーの天気・実測・警報は、位置が決まってからその位置で取り、取れた値をそのまま渡す", () => {
    const weather = {
      weather: { marker: "今日の見通し" },
      weatherLoading: true,
      weatherError: "見通しの誤り",
      amedas: { marker: "実測" },
      amedasLoading: false,
      amedasError: "実測の誤り",
      warningBadgeItems: [{ marker: "警報" }],
      warningFetchFailures: [{ marker: "未取得" }],
    } as unknown as ReturnType<typeof useWeatherConditions>;
    vi.mocked(useWeatherConditions).mockReturnValue(weather);
    renderPage();
    expect(useWeatherConditions).toHaveBeenLastCalledWith(HERE, true);
    expect(propsOf<typeof WeatherPanel>("WeatherPanel")).toEqual({
      amedas: weather.amedas,
      loading: weather.amedasLoading,
      error: weather.amedasError,
    });
    expect(propsOf<typeof TodayOutlook>("TodayOutlook")).toEqual({
      weather: weather.weather,
      loading: weather.weatherLoading,
      error: weather.weatherError,
    });
    expect(propsOf<typeof WarningBadgeList>("WarningBadgeList")).toEqual({
      items: weather.warningBadgeItems,
      failures: weather.warningFetchFailures,
    });
  });

  it("メニューからデバッグログを開閉し、コンソールの側からも閉じられる", () => {
    renderPage();
    const menu = () => propsOf<typeof HeaderMenu>("HeaderMenu");
    const console_ = () => propsOf<typeof DebugConsole>("DebugConsole");
    expect(console_().open).toBe(false);
    act(() => menu().onToggleDebugConsole());
    expect(console_().open).toBe(true);
    expect(menu().debugConsoleOpen).toBe(true);
    act(() => console_().onClose());
    expect(console_().open).toBe(false);
  });

  it("現在地の取り直しは、待つ間は押せず、失敗したら理由を地図の上に出す", async () => {
    const user = renderPage();
    let fail: PositionErrorCallback | null | undefined;
    geolocation.getCurrentPosition.mockImplementation((_onSuccess, onError) => {
      fail = onError;
    });
    const locate = () => screen.getByRole("button", { name: "現在地に移動" });
    await user.click(locate());
    expect(locate()).toBeDisabled();
    expect(locate()).toHaveTextContent("…");
    act(() => fail?.({} as GeolocationPositionError));
    expect(locate()).toBeEnabled();
    expect(screen.getByText(/現在地を取得できませんでした/)).toBeInTheDocument();
  });
});
