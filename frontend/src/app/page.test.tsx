/**
 * `app/page.tsx`——トップページ。機能（地図・ルートの設定と結果・走行条件・天候）を1つの画面に束ね、機能の間の値を受け渡す。
 *
 * 見ること（利用者の操作の流れで、ある機能の変化が別の機能の振る舞いを変える受け渡し）:
 * - ルートを作る: 「ルート生成」が地図の色分けを添えて送ること、結果が出たら閉じていた「ルート結果」を
 *   開くこと、候補が「ルート結果」と地図の両方へ出て、選んだ候補が地図でも選ばれ、区間を持つかで周りの塗りが決まること、
 *   全消去は確認の窓で「消す」を押してから両方から消えること、候補がある間だけ条件のずれの印が点き全消去で消えること、走行条件の想定速度・出発時刻が
 *   生成と地図の道の詳細へ同じ値で渡ること、「地図の色分け」の未使用を分ける重み（生成の前はいまの重み・後は使われた重み）、
 *   保存した条件が地図で置いた出発地を持ち、呼び出すとその出発地から生成すること、前に保存した条件が「保存」の「設定」に出ること
 * - 地図で扱えること: 地点を置けるのは「ルート設定」の条件タブを見ている間だけで、目的地の行で探して置いた地点と、
 *   名前のある点の小窓から置いた地点が地図に立ち、行にその名前が出ること、
 *   名前を付けて保存した地点を打つ欄から選び直せ、「保存」の「地点」に並ぶこと、
 *   区間を押して詳細を出せるのは「ルート結果」を見ている間だけのこと、編集の間は地図で地点も区間も扱わず全部の候補を重ね、
 *   作り直すと編集が終わること、作ると直前の作り直しの失敗の文言を消し、合成ルートを選んでいる間は元のルートだけを重ねること、
 *   地図の表示をまとめて戻す操作（「表示」の一覧の末尾と右上のメニュー）
 * - 画面の枠: スマホの下部タブとシート（1枚ずつ開く・地点を扱える間・結果の合図・候補を出せなかった理由の1行・ルートを収めるときに避ける
 *   シートの高さ・高さの保存と保存値の検査）、区分の開閉の保存、ヘッダーの「未取得」に並ぶ出所と「現在地に移動」の失敗、
 *   メニューから入る使い方の説明とデバッグログ
 *
 * ここで見ないもの: 子の部品は本物を描き、子が値をどう描くか（一覧の書式・印の色・天候の値）は各部品のテストが見る。
 * 地図の見え方の中身（どのレイヤーをどの色・重なりで描くか・レンズの選択肢・凡例）は地図の側（`features/map/scene/`）の
 * テストが見て、ここでは地図に何が載ったか（線のソースの地物・レイヤーの表示・印）と、地図の操作で何が起きるかだけを見る。
 * 機能の状態の移り変わり（生成の検証と要求の形・候補の並び・地点の置き方・レイヤーと凡例の状態）は各フックのテストが
 * 見る。子へ渡す受け口へフックの関数や値をそのまま渡す所（重み・除外の入力・経由地を地図で動かす・消す・「現在地に戻す」・
 * 保存した条件を呼び出して現在地へ戻す・実行中の「ルート生成」・取り直している間の「現在地に移動」・まとめてレイヤーを消す
 * 操作を押せるか）は1行の委譲なので見ない。中身に合わせたシートの高さは、レイアウトの実寸が要るので見ない
 * （テスト環境は実寸を0で返し、シートは合わせない）。
 *
 * 差し替えたもの: backend の応答（網の層）、位置情報の取得（`navigator.geolocation`）、地図の描画（`maplibre-gl`）。
 * どれもテスト環境に無いものか、その手前の境界。地図は `@/testing/maplibre` の代役が受けたものを記録し、地図の操作
 * （押す・押した所に描かれている地物）はテストが代役から起こす。
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import { CLIENT_TUNING_IDS } from "@/lib/axisCatalog";
import { setDebugEnabled } from "@/lib/debugLog";
import { heldReplies, onBackend, onSameOrigin, serveAxisCatalog } from "@/testing/backendServer";
import { catalogEntry, catalogResponse, rampEntry } from "@/testing/catalogAxes";
import { serveGenerationJobs } from "@/testing/generationJobs";
import { mapOnScreen, type PointedFeature } from "@/testing/maplibre";
import { POINT_TILE_SOURCES } from "@/features/map/scene/groups/points";
import { sceneLayerId } from "@/features/map/scene/sceneBuilders";
import { makeGenerationConditions, makeRouteCandidate, makeRouteSegment } from "@/testing/routeFixtures";
import type { Coordinates, RouteCandidate } from "@/types/route";
import type { AxisInspectorResult } from "@/features/map/regionApi";
import regionTileConfig from "@/types/generated/region-tile-config.json";
import type { AmedasObservation, WeatherConditions } from "@/types/weather";

import Home from "./page";

vi.mock("maplibre-gl", () => import("@/testing/maplibre"));

const HERE: Coordinates = { latitude: 35.7, longitude: 139.7 };
const DESTINATION: Coordinates = { latitude: 35.6, longitude: 139.73 };
const ELSEWHERE: Coordinates = { latitude: 35.65, longitude: 139.72 };

// 地図が道路のタイルを載せる（軸で塗れる）のは、タイルの世代が全部の系統で揃ってから。
const CATALOG = catalogResponse([rampEntry("axis_a", [25, 50, 75], { label: "軸A", default_weight: 1 })], {
  client_tuning: { [CLIENT_TUNING_IDS.minStretchKm]: 0.1 },
  tile_versions: Object.fromEntries(regionTileConfig.tile_version_kinds.map((kind) => [kind, "1-test"])),
});

// 予報と実測（ここでは中身を見ない）。
const FORECAST: WeatherConditions = {
  precipitation_mm: null,
  twilight: null,
  precipitation_max_mm: null,
  wind_speed_max_ms: null,
  temperature_range: null,
  today_periods: [],
  today_period_interval_hours: 2,
};
const OBSERVATION: AmedasObservation = {
  station_name: "観測所",
  observed_at: "2026-01-01T12:00:00+09:00",
  temperature_c: null,
  apparent_temperature_c: null,
  wind_speed_ms: null,
  wind_direction: null,
  precipitation_10min_mm: null,
  twilight: null,
  weather_code: null,
};

let jobs: ReturnType<typeof serveGenerationJobs>;

/** 位置情報の取得。`point`が無ければ断る。 */
function installGeolocation(point: Coordinates | null) {
  const getCurrentPosition = (onSuccess: PositionCallback, onError: PositionErrorCallback) => {
    if (point) onSuccess({ coords: point } as GeolocationPosition);
    else onError({ code: 1 } as GeolocationPositionError);
  };
  Object.defineProperty(navigator, "geolocation", { value: { getCurrentPosition }, configurable: true });
}

function useMobileLayout() {
  document.documentElement.style.setProperty("--is-mobile", "1");
}

beforeEach(() => {
  window.localStorage.clear();
  installGeolocation(HERE);
  jobs = serveGenerationJobs();
  serveAxisCatalog(CATALOG);
  onSameOrigin("GET", "/api/jma-tile/*", () => Response.json([]));
  onBackend("GET", "/api/jma-tile-index", () => Response.json({ available: false, coverage: null, elements: {} }));
  onBackend("GET", "/api/weather", () => Response.json(FORECAST));
  onBackend("GET", "/api/weather/amedas", () => Response.json(OBSERVATION));
  onBackend("GET", "/api/weather/warnings", () => Response.json({ warnings: [] }));
  onBackend("GET", "/api/weather/wbgt", () => Response.json({ reading: null }));
  onBackend("GET", "/api/weather/flood-forecast", () => Response.json({ forecasts: [] }));
  onBackend("GET", "/api/place-area", () => Response.json({ area: null }));
});

afterEach(() => {
  document.documentElement.style.removeProperty("--is-mobile");
  setDebugEnabled(false);
});

function route(id: string, overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return makeRouteCandidate({ id, direction_label: id, ...overrides });
}

const SEGMENT = makeRouteSegment({ start_latitude: 35.7, start_longitude: 139.7, distance_km: 1 });
const FIRST = route("first", {
  estimated_duration_seconds: 1800,
  segments: [SEGMENT],
  geometry: {
    type: "LineString",
    coordinates: [
      [139.7, 35.7],
      [139.71, 35.7],
    ],
  },
});
const SECOND = route("second", {
  estimated_duration_seconds: 2400,
  geometry: {
    type: "LineString",
    coordinates: [
      [139.7, 35.7],
      [139.7, 35.71],
    ],
  },
});

/** 道の評価の応答（ここでは中身を見ない）。 */
const INSPECTED_ROAD: AxisInspectorResult = {
  highway: "residential",
  tags: {},
  axes: [],
  composite_difficulty: { value: 40, covered_weight_fraction: 1 },
  landcover: null,
};

/** 地図のソースに載った線の座標。 */
function linesOn(sourceId: string): unknown[] {
  return mapOnScreen()
    .sourceFeatures(sourceId)
    .map((feature) => (feature.geometry as GeoJSON.LineString).coordinates);
}

/** 地図に引いたルートの線（候補と、選んだ候補）。 */
function routeLinesOnMap(): unknown[] {
  const lines = [...linesOn("route-candidates"), ...linesOn("route-selected")];
  return lines.filter(
    (line, index) => lines.findIndex((other) => JSON.stringify(other) === JSON.stringify(line)) === index,
  );
}

/** 全部の道路をその軸で塗っているか。 */
function paints(axisId: string): boolean {
  return mapOnScreen().visibleLayerIds().includes(`road-tiles-${axisId}`);
}

/** 地図のその地点に置いた印。 */
function marksAt(point: Coordinates) {
  return mapOnScreen()
    .markers()
    .filter((mark) => mark.coordinates.latitude === point.latitude && mark.coordinates.longitude === point.longitude);
}

/** 地点の並びで目的地を押し、地図で選ぶ状態にする（押さなければ地図のタップは地点を置かない）。 */
async function armDestination(user: User) {
  await user.click(screen.getByRole("button", { name: "目的地: 未設定" }));
  await user.click(screen.getByRole("button", { name: "目的地を地図で選ぶ" }));
}

/** 地図を押す。`features`はそこに描かれている地物。 */
function clickMap(at: Coordinates, features: PointedFeature[] = []) {
  act(() => mapOnScreen().click(at, features));
}

/** 地図に描いた区間を押す。 */
function clickSegment(segment: GeoJSON.Feature, at: Coordinates) {
  clickMap(at, [
    { layer: "route-segments-detailHit", properties: segment.properties ?? {}, geometry: segment.geometry },
  ]);
}

const LOOP_CONDITIONS = makeGenerationConditions({ latitude: HERE.latitude, longitude: HERE.longitude });

function renderHome() {
  const user = userEvent.setup();
  const rendered = render(<Home />);
  act(() => mapOnScreen().emit("load"));
  return { user, ...rendered };
}

type User = ReturnType<typeof userEvent.setup>;

/** 「地図に出す情報」の一覧で道路のレイヤー（路面の種類）を出す。 */
async function showRoadSurface(user: User) {
  await user.click(screen.getByRole("button", { name: "地図に出す情報" }));
  await user.click(screen.getByRole("checkbox", { name: "路面の種類" }));
  await user.keyboard("{Escape}");
}

/** 「ルート生成」を押し、出した要求を返す。 */
async function generate(user: User) {
  const before = jobs.submitted.length;
  await user.click(screen.getByRole("button", { name: "ルート生成" }));
  await waitFor(() => expect(jobs.submitted).toHaveLength(before + 1));
  return jobs.submitted[before].body as Record<string, unknown>;
}

function candidateTabs() {
  return within(screen.getByRole("tablist", { name: "ルート結果" })).getAllByRole("tab");
}

/** 全消去の確認の窓で「消す」を押す。 */
async function confirmClear(user: User) {
  const dialog = screen.getByRole("dialog", { name: "候補をすべて消します" });
  await user.click(within(dialog).getByRole("button", { name: "消す" }));
}

function section(name: "ルート設定" | "ルート結果") {
  return screen.getByRole("button", { name });
}

describe("ルートを作る", () => {
  it("生成の結果が出たら閉じていた「ルート結果」を開く。候補は一覧と地図に出て、選んだ候補が区間を持つかで周りの塗りが決まる。全消去で両方から消える", async () => {
    const { user } = renderHome();
    await user.click(section("ルート結果"));
    expect(section("ルート結果")).toHaveAttribute("aria-expanded", "false");

    await user.click(screen.getByRole("button", { name: /^地図の色分け: / }));
    await user.click(await screen.findByRole("radio", { name: /軸A/ }));
    await user.click(screen.getByRole("button", { name: /^地図の色分け: / }));
    await user.click(await screen.findByRole("checkbox", { name: "ルート後も周囲の道路を薄く塗る" }));
    await user.keyboard("{Escape}");
    expect(paints("axis_a")).toBe(true);

    const job = heldReplies();
    jobs.answerWith(job.reply);
    await generate(user);
    expect(screen.getByRole("button", { name: "生成中..." })).toBeInTheDocument();

    await job.answer(
      0,
      Response.json({ status: "done", result: { routes: [FIRST, SECOND], conditions: LOOP_CONDITIONS } }),
    );
    await waitFor(() => expect(section("ルート結果")).toHaveAttribute("aria-expanded", "true"));
    expect(candidateTabs()).toHaveLength(2);
    expect(routeLinesOnMap()).toHaveLength(2);
    expect(routeLinesOnMap()).toEqual(
      expect.arrayContaining([FIRST.geometry.coordinates, SECOND.geometry.coordinates]),
    );
    expect(linesOn("route-selected")).toEqual([FIRST.geometry.coordinates]);
    expect(paints("axis_a")).toBe(false);

    await user.click(candidateTabs()[1]);
    expect(linesOn("route-selected")).toEqual([SECOND.geometry.coordinates]);
    expect(paints("axis_a")).toBe(true);

    await user.click(screen.getByRole("button", { name: "候補を全消去" }));
    expect(routeLinesOnMap()).toHaveLength(2);
    await confirmClear(user);
    expect(screen.queryByRole("tablist", { name: "ルート結果" })).toBeNull();
    expect(routeLinesOnMap()).toEqual([]);
    expect(screen.queryByRole("button", { name: "候補を全消去" })).toBeNull();
  });

  it("条件を変えたことの印は、候補がある間だけ「ルート生成」の隣に点き、押すと意味が開き、全消去で消える", async () => {
    const { user } = renderHome();
    const changedMark = () => screen.queryByRole("button", { name: "生成条件の変更を表示" });
    jobs.respond([FIRST], LOOP_CONDITIONS);
    await generate(user);
    await waitFor(() => expect(candidateTabs()).toHaveLength(1));

    fireEvent.change(screen.getByLabelText("全長の目標"), { target: { value: "50" } });
    await user.click(changedMark()!);
    expect(screen.getByRole("dialog")).toHaveTextContent("生成条件が変更されています");
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "候補を全消去" }));
    await confirmClear(user);
    expect(changedMark()).toBeNull();
  });

  it("走行条件の想定速度と出発時刻を変えると、生成の要求と地図の道の詳細へ同じ値が渡る", async () => {
    const departure = new Date("2026-10-05T09:00:00+09:00");
    // 道の評価は、送られた条件が走行条件と同じときだけ返す。
    onBackend("POST", "/api/region/axis-inspector", ({ body }) => {
      const sent = body as { speed_kmh?: number; at?: string };
      return sent.speed_kmh === 25 && sent.at === departure.toISOString()
        ? Response.json(INSPECTED_ROAD)
        : Response.json({ detail: "条件が違う" }, { status: 400 });
    });
    const { user } = renderHome();
    await user.click(screen.getByRole("button", { name: /^想定速度: / }));
    const speed = await screen.findByRole("spinbutton", { name: "想定速度（km/h）" });
    await user.clear(speed);
    await user.type(speed, "25");
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: /^出発時刻.*（タップで変更）$/ }));
    // 出発日時の入力は日本時間で読む。
    fireEvent.change(await screen.findByLabelText("出発日時を直接指定"), { target: { value: "2026-10-05T09:00" } });

    // 道を押せるのは、道路のレイヤーを出している間。
    await showRoadSurface(user);
    clickMap(HERE, [{ layer: "road-tiles-surface", properties: { osm_way_id: 1 } }]);
    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));
    expect(await screen.findByText(/この道だけで見た難易度/)).toBeInTheDocument();
    jobs.respond([FIRST], LOOP_CONDITIONS);
    expect(await generate(user)).toMatchObject({ assumed_speed_kmh: 25, start_time: departure.toISOString() });
  });

  it("保存した条件は地図で置いた出発地を持ち、呼び出すとその出発地から生成する", async () => {
    const PLACED: Coordinates = { latitude: 35.65, longitude: 139.75 };
    const { user } = renderHome();
    // 保存は見出しのアイコンで、どのタブを見ていてもできる。
    const saveAs = async (name: string) => {
      await user.click(screen.getByRole("button", { name: "いまの設定を保存" }));
      const dialog = screen.getByRole("dialog", { name: "いまの設定を保存" });
      const nameInput = within(dialog).getByRole("textbox", { name: "保存する名前" });
      await user.clear(nameInput);
      await user.type(nameInput, name);
      await user.click(within(dialog).getByRole("button", { name: "保存" }));
    };
    const recall = async (name: string) => {
      await user.click(screen.getByRole("tab", { name: "保存" }));
      await user.click(screen.getByRole("tab", { name: "設定" }));
      await user.click(screen.getByRole("button", { name: `「${name}」を呼び出す` }));
      await user.click(
        within(screen.getByRole("dialog", { name: `「${name}」を反映します` })).getByRole("button", {
          name: "反映する",
        }),
      );
    };
    const origin = (body: Record<string, unknown>) => ({ latitude: body.latitude, longitude: body.longitude });

    await user.click(screen.getByRole("button", { name: "出発地を地図で選ぶ" }));
    clickMap(PLACED);
    await saveAs("置いた所");
    await user.click(screen.getByRole("button", { name: "出発地を現在地に戻す" }));

    jobs.respond([FIRST], LOOP_CONDITIONS);
    await recall("置いた所");
    expect(origin(await generate(user))).toEqual(PLACED);
  });

  it("前に保存した設定は、「保存」の「設定」に出る", async () => {
    const stored = {
      name: "いつもの周回",
      routeMode: "loop",
      distance: "40",
      maxRoutes: "3",
      origin: null,
      waypoints: [],
    };
    window.localStorage.setItem(
      "ridecompass:saved-conditions",
      JSON.stringify([{ ...stored, destination: null, routePreference: null, hardFilters: {} }]),
    );
    const { user } = renderHome();

    await user.click(screen.getByRole("tab", { name: "保存" }));
    await user.click(screen.getByRole("tab", { name: "設定" }));

    expect(screen.getByRole("button", { name: "「いつもの周回」を呼び出す" })).toBeInTheDocument();
  });

  it("「地図の色分け」で未使用に分ける軸は、生成の前はいまの重み、生成の後は生成に使われた重みで決まる", async () => {
    serveAxisCatalog(
      catalogResponse([
        catalogEntry({ axis_id: "axis_a", label: "軸A", default_weight: 1 }),
        catalogEntry({ axis_id: "axis_b", label: "軸B", default_weight: 0 }),
      ]),
    );
    const { user } = renderHome();
    /** 「未使用」の見出しより後に並ぶ選択肢の文字。 */
    const unusedAxes = async () => {
      await user.click(screen.getByRole("button", { name: /^地図の色分け: / }));
      const options = await screen.findByRole("radiogroup", { name: "地図の色分け" });
      const unused = options.textContent?.split("未使用")[1] ?? "";
      await user.keyboard("{Escape}");
      return unused;
    };
    const beforeGeneration = await unusedAxes();
    expect(beforeGeneration).toContain("軸B");
    expect(beforeGeneration).not.toContain("軸A");

    jobs.respond([FIRST], { ...LOOP_CONDITIONS, route_preference: { axis_a: 0, axis_b: 1 } });
    await generate(user);
    await waitFor(() => expect(candidateTabs()).toHaveLength(1));
    const afterGeneration = await unusedAxes();
    expect(afterGeneration).toContain("軸A");
    expect(afterGeneration).not.toContain("軸B");
  });
});

describe("地図で扱えること", () => {
  it("地点を置けるのは「ルート設定」の条件タブを見ている間だけ（パネルを畳むと区分ごと隠れる）", async () => {
    const { user } = renderHome();
    await armDestination(user);
    clickMap(DESTINATION);
    expect(marksAt(DESTINATION)).toEqual([expect.objectContaining({ draggable: true })]);
    expect(screen.getByRole("button", { name: "目的地を消す" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "経由地を足す" }));
    await user.click(screen.getByRole("tab", { name: "重み" }));
    clickMap(ELSEWHERE);
    expect(marksAt(ELSEWHERE)).toEqual([]);
    expect(marksAt(DESTINATION)).toEqual([expect.objectContaining({ draggable: false })]);

    await user.click(screen.getByRole("tab", { name: "条件" }));
    await user.click(screen.getByRole("button", { name: "パネルを閉じる" }));
    expect(screen.queryByRole("button", { name: "ルート設定" })).toBeNull();
    clickMap(ELSEWHERE);
    expect(marksAt(ELSEWHERE)).toEqual([]);
    expect(marksAt(DESTINATION)).toEqual([expect.objectContaining({ draggable: false })]);

    await user.click(screen.getByRole("button", { name: "パネルを開く" }));
    clickMap(ELSEWHERE);
    expect(marksAt(ELSEWHERE)).toEqual([expect.objectContaining({ draggable: true })]);
  });

  it("名前のある点の小窓から、経由地に足す・目的地にすると地図と地点の並びにその名前で出し、条件タブを見ていない間は置く操作を出さない", async () => {
    const shop: Coordinates = { latitude: 35.71, longitude: 139.71 };
    const pointed = [
      {
        layer: sceneLayerId(POINT_TILE_SOURCES.poi.sourceId, "supply_poi"),
        properties: { name: "角の店", kind: "convenience" },
        geometry: { type: "Point", coordinates: [shop.longitude, shop.latitude] },
      } satisfies PointedFeature,
    ];
    const { user } = renderHome();
    await user.click(screen.getByRole("button", { name: "地図に出す情報" }));
    await user.click(screen.getByRole("checkbox", { name: "補給・休憩ポイント" }));
    await user.keyboard("{Escape}");

    clickMap(shop, pointed);
    await user.click(screen.getByRole("button", { name: "経由地に足す" }));
    expect(marksAt(shop)).toHaveLength(1);
    expect(screen.getByRole("button", { name: "経由地1: 角の店" })).toBeInTheDocument();

    clickMap(shop, pointed);
    await user.click(screen.getByRole("button", { name: "目的地にする" }));
    expect(marksAt(shop)).toHaveLength(2);
    expect(screen.getByRole("button", { name: "目的地: 角の店" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "重み" }));
    clickMap(shop, pointed);
    expect(screen.queryByRole("button", { name: "経由地に足す" })).toBeNull();
  });

  it("目的地を探して選んだ地点は地図に目的地として立ち、地点の並びにその名前が出る", async () => {
    const candidate = {
      kind: "facility",
      level: "point",
      name: "浅草寺",
      area: "台東区浅草二丁目",
      latitude: 35.7148,
      longitude: 139.7967,
    } as const;
    onBackend("GET", "/api/place-search", () => Response.json({ candidates: [candidate] }));
    const { user } = renderHome();
    await user.click(screen.getByRole("button", { name: "目的地: 未設定" }));
    const searchBox = screen.getByRole("searchbox", { name: "目的地を住所・施設で探す" });

    await user.type(searchBox, "浅草寺{Enter}");
    await user.click(await screen.findByRole("button", { name: new RegExp(candidate.name) }));

    expect(marksAt(candidate)).toHaveLength(1);
    expect(screen.getByRole("button", { name: `目的地: ${candidate.name}` })).toBeInTheDocument();
  });

  it("名前を付けて保存した地点は、目的地を消したあとも打つ欄を押して選び直せ、「保存」の「地点」に並ぶ", async () => {
    const { user } = renderHome();
    await armDestination(user);
    clickMap(DESTINATION);
    await user.click(screen.getByRole("button", { name: "地点を保存" }));
    const dialog = screen.getByRole("dialog", { name: "地点を保存" });
    const nameInput = within(dialog).getByRole("textbox", { name: "保存する地点の名前" });
    await user.clear(nameInput);
    await user.type(nameInput, "いつものカフェ");
    await user.click(within(dialog).getByRole("button", { name: "保存" }));
    await user.click(screen.getByRole("button", { name: "目的地を消す" }));
    expect(marksAt(DESTINATION)).toEqual([]);

    await user.click(screen.getByRole("searchbox", { name: "目的地を住所・施設で探す" }));
    const saved = screen.getByRole("list", { name: "保存した地点" });
    await user.click(within(saved).getByRole("button", { name: /いつものカフェ/ }));

    expect(marksAt(DESTINATION)).toHaveLength(1);
    expect(screen.getByRole("button", { name: "目的地: いつものカフェ" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "保存" }));
    await user.click(screen.getByRole("tab", { name: "地点" }));
    expect(screen.getByRole("button", { name: "「いつものカフェ」を消す" })).toBeInTheDocument();
  });

  it("地図で区間を押して詳細を出せるのは「ルート結果」を見ている間だけ", async () => {
    const { user } = renderHome();
    jobs.respond([FIRST], LOOP_CONDITIONS);
    await generate(user);
    await waitFor(() => expect(candidateTabs()).toHaveLength(1));
    const [drawnSegment] = mapOnScreen().sourceFeatures("route-segments");

    await user.click(section("ルート結果"));
    clickSegment(drawnSegment, HERE);
    await user.click(section("ルート結果"));
    expect(screen.queryByRole("button", { name: "区間の選択を解除" })).toBeNull();

    clickSegment(drawnSegment, HERE);
    expect(screen.getByRole("button", { name: "区間の選択を解除" })).toBeInTheDocument();
  });

  describe("区間の乗り換え", () => {
    // 地点（[経度, 緯度]）。元の候補は P0→P1→P2→P3→P4 を進み、もう1本は P1 と P2 の間を Q、P3 と P4 の間を R を通って進む
    // （片方の分かれ道だけを乗り換えると、どちらの候補とも違う道になる）。
    const P0 = [139.7, 35.6];
    const P1 = [139.71, 35.6];
    const P2 = [139.72, 35.6];
    const P3 = [139.73, 35.6];
    const P4 = [139.74, 35.6];
    const Q = [139.715, 35.61];
    const R = [139.735, 35.61];

    function through(id: string, edgeIds: string[], points: number[][], overrides: Partial<RouteCandidate> = {}) {
      return route(id, {
        kind: "destination",
        spliceable: true,
        edge_ids: edgeIds,
        node_ids: points.map((point) => point.join(",")),
        edge_point_offsets: points.map((_, index) => index),
        geometry: { type: "LineString", coordinates: points },
        ...overrides,
      });
    }

    const BASE = through("base", ["e1", "e2", "e3", "e4"], [P0, P1, P2, P3, P4], {
      estimated_duration_seconds: 1800,
      segments: [SEGMENT],
    });
    const OTHER = through("other", ["e1", "q1", "q2", "e3", "r1", "r2"], [P0, P1, Q, P2, P3, R, P4], {
      estimated_duration_seconds: 2400,
    });
    const DESTINATION_CONDITIONS = makeGenerationConditions({
      latitude: HERE.latitude,
      longitude: HERE.longitude,
      destination: DESTINATION,
    });

    /** 目的地を置いて2本の候補を作る。 */
    async function generateTwo(user: User) {
      await armDestination(user);
      clickMap(DESTINATION);
      jobs.respond([BASE, OTHER], DESTINATION_CONDITIONS);
      await generate(user);
    }

    /** 先頭の候補で編集を始める。 */
    async function startEditing(user: User) {
      await user.click(await screen.findByRole("button", { name: "ルートを合成" }));
      await waitFor(() => expect(mapOnScreen().sourceFeatures("route-splice-bands").length).toBeGreaterThan(0));
    }

    it("編集している間は地図で地点も区間も扱わず、全部の候補を重ねる。作り直すと編集が終わる", async () => {
      const { user } = renderHome();
      await generateTwo(user);
      await startEditing(user);
      expect(routeLinesOnMap()).toHaveLength(2);
      expect(routeLinesOnMap()).toEqual(
        expect.arrayContaining([BASE.geometry.coordinates, OTHER.geometry.coordinates]),
      );
      clickMap(ELSEWHERE);
      expect(marksAt(ELSEWHERE)).toEqual([]);
      expect(marksAt(DESTINATION)).toEqual([expect.objectContaining({ draggable: false })]);

      clickSegment(mapOnScreen().sourceFeatures("route-segments")[0], ELSEWHERE);
      await user.click(screen.getByRole("button", { name: "編集をやめて候補へ戻る" }));
      expect(screen.queryByRole("button", { name: "区間の選択を解除" })).toBeNull();

      await user.click(screen.getByRole("button", { name: "ルートを合成" }));
      jobs.respond([BASE, OTHER], DESTINATION_CONDITIONS);
      await generate(user);
      await waitFor(() => expect(mapOnScreen().sourceFeatures("route-splice-bands")).toEqual([]));
    });

    it("作ると直前の作り直しの失敗の文言を消し、作った合成ルートを選んでいる間は、地図に元のルートだけを重ねる", async () => {
      const { user } = renderHome();
      await generateTwo(user);
      jobs.fail("混雑しています");
      await generate(user);
      expect(await screen.findByText(/作り直せませんでした/)).toBeInTheDocument();
      await startEditing(user);
      const [band] = mapOnScreen().sourceFeatures("route-splice-bands");
      clickMap(HERE, [
        { layer: "route-splice-bands-spliceBandHit", properties: band.properties ?? {}, geometry: band.geometry },
      ]);
      jobs.respond([route("evaluated", { edge_ids: ["e1", "q1", "q2", "e3", "e4"] })], DESTINATION_CONDITIONS);
      await user.click(await screen.findByRole("button", { name: "新しいルートを作成" }));

      await waitFor(() => expect(routeLinesOnMap()).toHaveLength(2));
      const [created] = linesOn("route-selected");
      expect(routeLinesOnMap()).toEqual(expect.arrayContaining([BASE.geometry.coordinates, created]));
      expect(created).not.toEqual(BASE.geometry.coordinates);
      expect(created).not.toEqual(OTHER.geometry.coordinates);
      expect(screen.queryByText(/作り直せませんでした/)).toBeNull();
    });
  });

  it("地図の表示をまとめて戻す: 「表示」の一覧で行を全部消すとルートのほかの地図のレイヤーが消え、絞り込みを解くのは色分けの凡例を含めて凡例で隠している間だけ押せる。右上のメニューの再描画は地図の描き直しを求める", async () => {
    const { user } = renderHome();
    const fromList = async <T,>(name: string, inspect: (button: HTMLButtonElement) => Promise<T> | T) => {
      await user.click(screen.getByRole("button", { name: "地図に出す情報" }));
      const result = await inspect(screen.getByRole("button", { name }) as HTMLButtonElement);
      await user.keyboard("{Escape}");
      return result;
    };
    const canRun = (name: string) => fromList(name, (button) => !button.disabled);
    const run = (name: string) => fromList(name, (button) => user.click(button));
    // ルートの出し入れは色分けが持ち、一覧の操作では消さない。
    const nonRouteLayers = () =>
      mapOnScreen()
        .visibleLayerIds()
        .filter((id) => !id.startsWith("route-"));
    await showRoadSurface(user);
    expect(nonRouteLayers()).not.toEqual([]);
    const routeLayers = mapOnScreen()
      .visibleLayerIds()
      .filter((id) => id.startsWith("route-"));
    await run("表示中のレイヤーをすべて非表示");
    expect(nonRouteLayers()).toEqual([]);
    expect(mapOnScreen().visibleLayerIds()).toEqual(routeLayers);

    expect(await canRun("絞り込みをすべて解除")).toBe(false);
    jobs.respond([FIRST], LOOP_CONDITIONS);
    await generate(user);
    await user.click(await screen.findByRole("button", { name: /^地図の色分け: / }));
    const legendAll = await screen.findByRole("checkbox", { name: "凡例の全段階をまとめて表示/非表示" });
    await user.click(legendAll);
    await user.keyboard("{Escape}");
    expect(await canRun("絞り込みをすべて解除")).toBe(true);
    await run("絞り込みをすべて解除");
    expect(await canRun("絞り込みをすべて解除")).toBe(false);

    const before = mapOnScreen().styles.length;
    await user.click(screen.getByRole("button", { name: "メニュー" }));
    await user.click(screen.getByRole("button", { name: "地図の表示を再描画" }));
    expect(mapOnScreen().styles).toHaveLength(before + 1);
  });
});

describe("画面の枠", () => {
  it("スマホでは下部タブでシートを1枚ずつ開き、地図で地点を扱えるのは「ルート設定」の条件タブを開いている間だけ。結果の合図は「ルート結果」を開くまで残り、押した結果が候補を出せなかった理由（候補0件の理由・入力の誤り）は「ルート設定」にも1行で出す。候補0件の合図は成功と見分ける", async () => {
    installGeolocation(null);
    useMobileLayout();
    const { user } = renderHome();
    const settingsTab = () => screen.getByRole("button", { name: "ルート設定", expanded: false });
    const outcomeTab = screen.getByRole("button", { name: "ルート結果" });
    // 現在地が取れないので、地図の印は出発地の1つだけ。
    const originMark = () => mapOnScreen().markers()[0];
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(originMark().draggable).toBe(false);

    await user.click(settingsTab());
    const settingsSheet = screen.getByRole("dialog", { name: "ルート設定" });
    await user.click(within(settingsSheet).getByRole("button", { name: "ルート生成" }));
    expect(within(settingsSheet).getByText(/^現在地が分かりません/)).toBeInTheDocument();
    expect(outcomeTab).toHaveAccessibleDescription("生成に失敗しました");

    await user.click(within(settingsSheet).getByRole("button", { name: "出発地を地図で選ぶ" }));
    expect(originMark().draggable).toBe(true);
    await user.click(within(settingsSheet).getByRole("tab", { name: "重み" }));
    expect(originMark().draggable).toBe(false);
    await user.click(within(settingsSheet).getByRole("tab", { name: "条件" }));
    clickMap(HERE);
    jobs.respond([FIRST], LOOP_CONDITIONS);
    expect(await generate(user)).toMatchObject({ latitude: HERE.latitude, longitude: HERE.longitude });
    await waitFor(() => expect(outcomeTab).toHaveAccessibleDescription("新しい結果があります"));
    expect(within(settingsSheet).queryByText(/^現在地が分かりません/)).toBeNull();
    // ルートは、開いているシートが覆う高さ（画面の半分）を避けて収める。
    const { padding } = mapOnScreen().fits.at(-1) as { padding: { top: number; bottom: number } };
    expect(padding.bottom - padding.top).toBe(window.innerHeight * 0.5);

    await user.click(outcomeTab);
    expect(screen.queryByRole("dialog", { name: "ルート設定" })).toBeNull();
    const outcomeSheet = screen.getByRole("dialog", { name: "ルート結果" });
    expect(within(outcomeSheet).getByRole("button", { name: "候補を全消去" })).toBeInTheDocument();
    expect(outcomeTab).not.toHaveAccessibleDescription();
    await user.click(within(outcomeSheet).getByRole("button", { name: "閉じる" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(settingsTab());
    fireEvent.change(screen.getByLabelText("全長の目標"), { target: { value: "50" } });
    expect(outcomeTab).toHaveAccessibleDescription("生成条件が変更されています");
    jobs.respond([], LOOP_CONDITIONS, "起点の近くに道路データがありません");
    await generate(user);
    await waitFor(() => expect(outcomeTab).toHaveAccessibleDescription("候補が見つかりませんでした"));
    expect(
      within(screen.getByRole("dialog", { name: "ルート設定" })).getByText("起点の近くに道路データがありません"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "ルート設定", expanded: true }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("スマホのシートの高さは、確定した値を2枚のシートで共有し、次に開いたときも使う", async () => {
    useMobileLayout();
    const { user, unmount } = renderHome();
    await user.click(screen.getByRole("button", { name: "ルート設定" }));
    const handle = screen.getByRole("separator", { name: "パネルの高さを変更" });
    handle.focus();
    await user.keyboard("{ArrowUp}");
    expect(handle).toHaveAttribute("aria-valuenow", "55");
    unmount();

    renderHome();
    await user.click(screen.getByRole("button", { name: "ルート結果" }));
    expect(screen.getByRole("separator", { name: "パネルの高さを変更" })).toHaveAttribute("aria-valuenow", "55");
  });

  it("スマホのシートをつまみで動かしている間の高さは、すぐ使うが保存しない", async () => {
    useMobileLayout();
    const { user, unmount } = renderHome();
    await user.click(screen.getByRole("button", { name: "ルート設定" }));
    const handle = screen.getByRole("separator", { name: "パネルの高さを変更" });
    fireEvent.pointerDown(handle, { pointerId: 1, clientY: window.innerHeight * 0.5 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientY: window.innerHeight * 0.3 });
    expect(handle).toHaveAttribute("aria-valuenow", "70");
    unmount();

    renderHome();
    await user.click(screen.getByRole("button", { name: "ルート設定" }));
    expect(screen.getByRole("separator", { name: "パネルの高さを変更" })).toHaveAttribute(
      "aria-valuenow",
      String(DEFAULT_SHEET_HEIGHT_VH),
    );
  });

  it.each([
    ["数として読めない", "高い", DEFAULT_SHEET_HEIGHT_VH],
    ["数でない値", '"70"', DEFAULT_SHEET_HEIGHT_VH],
    ["シートの範囲の外", "500", clampSheetHeightVh(500)],
  ])("保存されたシートの高さが%sなら、%sから%d%%で開く", async (_, stored, expected) => {
    window.localStorage.setItem("ridecompass:mobile-sheet-height-vh", stored);
    useMobileLayout();
    const { user } = renderHome();
    await user.click(screen.getByRole("button", { name: "ルート設定" }));
    expect(screen.getByRole("separator", { name: "パネルの高さを変更" })).toHaveAttribute(
      "aria-valuenow",
      String(Math.round(expected)),
    );
  });

  it("区分の開閉は、次に開いたときも同じになる", async () => {
    const { user, unmount } = renderHome();
    await user.click(section("ルート設定"));
    unmount();

    renderHome();
    expect(section("ルート設定")).toHaveAttribute("aria-expanded", "false");
    expect(section("ルート結果")).toHaveAttribute("aria-expanded", "true");
  });

  it("ヘッダーの「未取得」に、現在地・軸の一覧・警報の取れないものが並ぶ。「現在地に移動」が取れなければ地図の上に理由を出す", async () => {
    installGeolocation(null);
    onBackend("GET", "/api/axis-catalog", () => Response.json({ detail: "失敗" }, { status: 502 }));
    onBackend("GET", "/api/weather/warnings", () => Response.json({ detail: "失敗" }, { status: 502 }));
    const { user } = renderHome();
    const missing = () => screen.getByRole("button", { name: /を取得できていません。押すと/ });
    await waitFor(() => expect(missing()).toHaveAccessibleName(/現在地.*評価軸の一覧|評価軸の一覧.*現在地/));
    expect(missing()).not.toHaveAccessibleName(/警報/);

    await user.click(screen.getByRole("button", { name: "現在地に移動" }));
    expect(screen.getByText(/現在地を取得できませんでした/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "出発地を地図で選ぶ" }));
    clickMap(HERE);
    await waitFor(() => expect(missing()).toHaveAccessibleName(/警報/));
    expect(missing()).not.toHaveAccessibleName(/現在地/);
  });

  it("メニューから使い方の説明に入って「やめる」で抜け、デバッグログをメニューから開いてログの側から閉じられる", async () => {
    const { user } = renderHome();
    // 地図を開いたあとに入れる（代役の地図は基礎地図の道路を持たず、地図がそのことをデバッグログへ警告する）。
    act(() => setDebugEnabled(true));
    await user.click(screen.getByRole("button", { name: "メニュー" }));
    await user.click(screen.getByRole("button", { name: "使い方を見る" }));
    expect(screen.getByText("説明モード")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "やめる" }));
    expect(screen.queryByText("説明モード")).toBeNull();

    await user.click(screen.getByRole("button", { name: "メニュー" }));
    await user.click(screen.getByRole("button", { name: "デバッグログを表示" }));
    expect(screen.getByText(/^デバッグログ\[/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^デバッグログ\[.*を閉じる$/ }));
    expect(screen.queryByText(/^デバッグログ\[/)).toBeNull();
  });
});
