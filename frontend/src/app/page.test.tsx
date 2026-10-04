/**
 * `app/page.tsx`——トップページ。機能（地図・ルートの設定と結果・走行条件・天候）を1つの画面に束ね、機能の間の値を受け渡す。
 *
 * 見ること（利用者の操作の流れで、ある機能の変化が別の機能の振る舞いを変える受け渡し）:
 * - ルートを作る: 「ルート生成」が地図の色分けを添えて送ること・実行中は押せないこと、結果が出たら閉じていた「ルート結果」を
 *   開くこと、候補が「ルート結果」と地図の両方へ出て、選んだ候補が地図でも選ばれ、区間を持つかで周りの塗りが決まること、
 *   全消去で両方から消えること、候補がある間だけ条件のずれの印が点き全消去で消えること、走行条件の想定速度・出発時刻が
 *   生成と地図の道の詳細へ同じ値で渡ること、「地図の色分け」の未使用を分ける重み（生成の前はいまの重み・後は使われた重み）、
 *   保存した条件が地図で置いた出発地を持ち、呼び出すとその出発地（無ければ現在地）から生成すること
 * - 地図で扱えること: 地点を置けるのは「ルート設定」の条件タブを見ている間だけで、周回の間は目的地を地図へ出さないこと、
 *   区間を押して詳細を出せるのは「ルート結果」を見ている間だけのこと、編集の間は地図で地点も区間も扱わず全部の候補を重ね、
 *   作り直すと編集が終わること、作ると直前の作り直しの失敗の文言を消し、合成ルートを選んでいる間は元のルートだけを重ねること、
 *   研究モードの実験スロットは「比較」を見ている間だけ重ねること、地図の下のまとめて元に戻す操作
 * - 画面の枠: スマホの下部タブとシート（1枚ずつ開く・地点を扱える間・結果の合図・入力の誤り・出発地・覆う高さ・高さの保存と
 *   保存値の検査）、区分の開閉の保存、ヘッダーの「未取得」に並ぶ出所と「現在地に移動」の失敗、メニューから入る使い方の説明と
 *   デバッグログ
 *
 * ここで見ないもの: 子の部品は地図を除いて本物を描き、子が値をどう描くか（一覧の書式・印の色・天候の値）は各部品のテストが
 * 見る。機能の状態の移り変わり（生成の検証と要求の形・候補の並び・地点の置き方・レイヤーと凡例の状態）は各フックのテストが
 * 見る。子へ渡す受け口へフックの関数や値をそのまま渡す所（重み・除外の入力・経由地を地図で動かす・消す・「現在地に戻す」・
 * 取り直している間の「現在地に移動」）は1行の委譲なので見ない。中身に合わせたシートの高さと、シートの高さに合わせて地図の
 * 操作部品を持ち上げることは、レイアウトの実寸が要るので見ない（テスト環境は実寸を0で返し、シートは合わせない）。
 *
 * 差し替えたもの: backend の応答（網の層）、位置情報の取得（`navigator.geolocation`。テスト環境に無いブラウザの機能）、
 * 地図（`features/map/MapView/MapView`）。地図は WebGL（`maplibre-gl`）を要するので、受け取った値を記録する代役にし、
 * 地図から上がる操作（地点を置く・区間を押す・乗り換え先を押す）は代役が受け取った関数を呼んで起こす。地図の代役は、
 * `maplibre-gl` の側に代役を作ったら外す。
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clampSheetHeightVh, DEFAULT_SHEET_HEIGHT_VH } from "@/components/BottomSheet/BottomSheet";
import type MapView from "@/features/map/MapView/MapView";
import { CLIENT_TUNING_IDS } from "@/lib/axisCatalog";
import { setDebugEnabled } from "@/lib/debugLog";
import { setResearchEnabled } from "@/lib/researchMode";
import { heldReplies, onBackend, onSameOrigin, serveAxisCatalog } from "@/testing/backendServer";
import { catalogEntry, catalogResponse } from "@/testing/catalogAxes";
import { serveGenerationJobs } from "@/testing/generationJobs";
import { makeGenerationConditions, makeRouteCandidate, makeRouteSegment } from "@/testing/routeFixtures";
import type { Coordinates, RouteCandidate } from "@/types/route";
import type { AmedasObservation, WeatherConditions } from "@/types/weather";

const { stubModule, stubProps } = await vi.hoisted(() => import("@/testing/componentStubs"));
vi.mock("@/features/map/MapView/MapView", stubModule("MapView"));

const { default: Home } = await import("./page");

const HERE: Coordinates = { latitude: 35.7, longitude: 139.7 };
const DESTINATION: Coordinates = { latitude: 35.6, longitude: 139.73 };

const CATALOG = catalogResponse([catalogEntry({ axis_id: "axis_a", label: "軸A", default_weight: 1 })], {
  client_tuning: { [CLIENT_TUNING_IDS.minStretchKm]: 0.1 },
});

// 予報と実測（ここでは中身を見ない）。
const FORECAST: WeatherConditions = {
  temperature_c: null,
  wind_speed_ms: 0,
  wind_direction_deg: 0,
  wind_direction_label: "北",
  precipitation_mm: null,
  observed_at: "2026-10-04T09:00:00+09:00",
  twilight: null,
  precipitation_max_mm: null,
  wind_speed_max_ms: null,
  temperature_range: null,
  today_periods: [],
  today_period_interval_hours: 2,
};
const OBSERVATION: AmedasObservation = {
  station_id: "station",
  station_name: "観測所",
  ...HERE,
  observed_at: "2026-10-04T09:00:00+09:00",
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
  onBackend("GET", "/api/weather", () => Response.json(FORECAST));
  onBackend("GET", "/api/weather/amedas", () => Response.json(OBSERVATION));
  onBackend("GET", "/api/weather/warnings", () => Response.json({ warnings: [] }));
  onBackend("GET", "/api/weather/wbgt", () => Response.json({ reading: null }));
  onBackend("GET", "/api/weather/flood-forecast", () => Response.json({ forecasts: [] }));
});

afterEach(() => {
  document.documentElement.style.removeProperty("--is-mobile");
  setResearchEnabled(false);
  setDebugEnabled(false);
});

type MapProps = ComponentProps<typeof MapView>;

function mapView(): MapProps {
  return stubProps<MapProps>("MapView");
}

function route(id: string, overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return makeRouteCandidate({ id, direction_label: id, ...overrides });
}

const SEGMENT = makeRouteSegment({ start_latitude: 35.7, start_longitude: 139.7, distance_km: 1 });
const FIRST = route("first", { estimated_duration_seconds: 1800, segments: [SEGMENT] });
const SECOND = route("second", { estimated_duration_seconds: 2400 });

const LOOP_CONDITIONS = makeGenerationConditions({ latitude: HERE.latitude, longitude: HERE.longitude });

function renderHome() {
  const user = userEvent.setup();
  return { user, ...render(<Home />) };
}

/** 「ルート生成」を押し、出した要求を返す。 */
async function generate(user: ReturnType<typeof userEvent.setup>) {
  const before = jobs.submitted.length;
  await user.click(screen.getByRole("button", { name: "ルート生成" }));
  await waitFor(() => expect(jobs.submitted).toHaveLength(before + 1));
  return jobs.submitted[before].body as Record<string, unknown>;
}

function candidateTabs() {
  return within(screen.getByRole("tablist", { name: "ルート結果" })).getAllByRole("tab");
}

function section(name: "ルート設定" | "ルート結果") {
  return screen.getByRole("button", { name });
}

describe("ルートを作る", () => {
  it("生成は地図の色分けを添えて送り、結果が出たら閉じていた「ルート結果」を開く。候補は一覧と地図に出て、選んだ候補が区間を持つかで周りの塗りが決まる。全消去で両方から消える", async () => {
    const { user } = renderHome();
    await user.click(section("ルート結果"));
    expect(section("ルート結果")).toHaveAttribute("aria-expanded", "false");

    await user.click(screen.getByRole("button", { name: /^地図の色分け: / }));
    await user.click(await screen.findByRole("radio", { name: /軸A/ }));
    await user.click(screen.getByRole("button", { name: /^地図の色分け: / }));
    await user.click(await screen.findByRole("checkbox", { name: "ルート後も周囲の道路を薄く塗る" }));
    await user.keyboard("{Escape}");
    expect(mapView().look.paintedAxisId).toBe("axis_a");

    const job = heldReplies();
    jobs.answerWith(job.reply);
    expect((await generate(user)).lens_axis_id).toBe("axis_a");
    expect(screen.getByRole("button", { name: "生成中..." })).toBeDisabled();

    await job.answer(
      0,
      Response.json({ status: "done", result: { routes: [FIRST, SECOND], conditions: LOOP_CONDITIONS } }),
    );
    await waitFor(() => expect(section("ルート結果")).toHaveAttribute("aria-expanded", "true"));
    expect(candidateTabs()).toHaveLength(2);
    expect(mapView().routes.map((candidate) => candidate.id)).toEqual(["first", "second"]);
    expect(mapView().selectedRouteId).toBe("first");
    expect(mapView().look.paintedAxisId).toBeNull();

    await user.click(candidateTabs()[1]);
    expect(mapView().selectedRouteId).toBe("second");
    expect(mapView().look.paintedAxisId).toBe("axis_a");

    await user.click(screen.getByRole("button", { name: "候補を全消去" }));
    expect(screen.queryByRole("tablist", { name: "ルート結果" })).toBeNull();
    expect(mapView().routes).toEqual([]);
    expect(screen.queryByRole("button", { name: "候補を全消去" })).toBeNull();
  });

  it("条件を変えたことの印は、候補がある間だけ「ルート生成」の隣に点き、全消去で消える", async () => {
    const { user } = renderHome();
    const distance = screen.getByLabelText("距離");
    const changedMark = () => screen.queryByRole("img", { name: "生成条件が変更されています" });

    fireEvent.change(distance, { target: { value: "40" } });
    expect(changedMark()).toBeNull();

    jobs.respond([FIRST], LOOP_CONDITIONS);
    await generate(user);
    await waitFor(() => expect(candidateTabs()).toHaveLength(1));
    expect(changedMark()).toBeNull();

    fireEvent.change(distance, { target: { value: "50" } });
    expect(changedMark()).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "候補を全消去" }));
    expect(changedMark()).toBeNull();
  });

  it("走行条件の想定速度と出発時刻を変えると、生成の要求と地図の道の詳細へ同じ値が渡る", async () => {
    const { user } = renderHome();
    await user.click(screen.getByRole("button", { name: /^想定速度: / }));
    const speed = await screen.findByRole("spinbutton", { name: "想定速度（km/h）" });
    await user.clear(speed);
    await user.type(speed, "25");
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: /^出発時刻.*（タップで変更）$/ }));
    // 出発日時の入力は日本時間で読む。
    fireEvent.change(await screen.findByLabelText("出発日時を直接指定"), { target: { value: "2026-10-05T09:00" } });
    const departure = new Date("2026-10-05T09:00:00+09:00");

    expect(mapView().rideConditions).toMatchObject({ speedKmh: 25, at: departure });
    jobs.respond([FIRST], LOOP_CONDITIONS);
    expect(await generate(user)).toMatchObject({ assumed_speed_kmh: 25, start_time: departure.toISOString() });
  });

  it("保存した条件は地図で置いた出発地を持ち、呼び出すとその出発地から生成する。現在地のまま保存した条件を呼び出すと現在地へ戻る", async () => {
    const PLACED: Coordinates = { latitude: 35.65, longitude: 139.75 };
    const { user } = renderHome();
    const saveAs = async (name: string) => {
      await user.click(screen.getByRole("tab", { name: "保存" }));
      const nameInput = screen.getByRole("textbox", { name: "保存する名前" });
      await user.clear(nameInput);
      await user.type(nameInput, name);
      await user.click(screen.getByRole("button", { name: "保存" }));
    };
    const recall = async (name: string) => {
      await user.click(screen.getByRole("tab", { name: "保存" }));
      await user.click(screen.getByRole("button", { name: `「${name}」を呼び出す` }));
    };
    const origin = (body: Record<string, unknown>) => ({ latitude: body.latitude, longitude: body.longitude });

    await user.click(screen.getByRole("button", { name: "出発地を地図で選ぶ" }));
    act(() => mapView().onPinPlace("origin", PLACED));
    await saveAs("置いた所");
    await user.click(screen.getByRole("tab", { name: "条件" }));
    await user.click(screen.getByRole("button", { name: "出発地を現在地に戻す" }));
    await saveAs("現在地");

    jobs.respond([FIRST], LOOP_CONDITIONS);
    await recall("置いた所");
    expect(origin(await generate(user))).toEqual(PLACED);
    jobs.respond([FIRST], LOOP_CONDITIONS);
    await recall("現在地");
    expect(origin(await generate(user))).toEqual(HERE);
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
  it("地点を置けるのは「ルート設定」の条件タブを見ている間だけ（パネルを畳むと区分ごと隠れる）で、周回の間は目的地を地図へ出さない", async () => {
    const { user } = renderHome();
    await user.click(screen.getByRole("radio", { name: "目的地" }));
    expect(mapView().armedPinRole).toBe("destination");
    expect(mapView().pointEditingEnabled).toBe(true);

    act(() => mapView().onPinPlace("destination", DESTINATION));
    expect(mapView().destination).toEqual(DESTINATION);
    expect(screen.getByRole("button", { name: "目的地をクリア" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "経由地を追加" }));
    await user.click(screen.getByRole("tab", { name: "重み" }));
    expect(mapView().armedPinRole).toBeNull();
    expect(mapView().pointEditingEnabled).toBe(false);

    await user.click(screen.getByRole("tab", { name: "条件" }));
    expect(mapView().armedPinRole).toBe("waypoint");
    await user.click(screen.getByRole("button", { name: "パネルを閉じる" }));
    expect(screen.queryByRole("button", { name: "ルート設定" })).toBeNull();
    expect(mapView().armedPinRole).toBeNull();
    expect(mapView().pointEditingEnabled).toBe(false);

    await user.click(screen.getByRole("button", { name: "パネルを開く" }));
    await user.click(screen.getByRole("radio", { name: "周回" }));
    expect(mapView().destination).toBeNull();
    await user.click(screen.getByRole("radio", { name: "目的地" }));
    expect(mapView().destination).toEqual(DESTINATION);
  });

  it("地図で区間を押して詳細を出せるのは「ルート結果」を見ている間だけ", async () => {
    const { user } = renderHome();
    jobs.respond([FIRST], LOOP_CONDITIONS);
    await generate(user);
    await waitFor(() => expect(candidateTabs()).toHaveLength(1));
    const selection = { segment: SEGMENT, latitude: 35.7, longitude: 139.7 };

    await user.click(screen.getByRole("button", { name: "ルート結果" }));
    act(() => mapView().onRouteSegmentSelect(selection));
    await user.click(screen.getByRole("button", { name: "ルート結果" }));
    expect(screen.queryByRole("button", { name: "区間の選択を解除" })).toBeNull();

    act(() => mapView().onRouteSegmentSelect(selection));
    expect(screen.getByRole("button", { name: "区間の選択を解除" })).toBeInTheDocument();
    expect(mapView().selectedRouteSegment).toEqual(selection);
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
        edge_ids: edgeIds,
        node_ids: points.map((point) => point.join(",")),
        edge_point_offsets: points.map((_, index) => index),
        geometry: { type: "LineString", coordinates: points },
        ...overrides,
      });
    }

    const BASE = through("base", ["e1", "e2", "e3", "e4"], [P0, P1, P2, P3, P4], { estimated_duration_seconds: 1800 });
    const OTHER = through("other", ["e1", "q1", "q2", "e3", "r1", "r2"], [P0, P1, Q, P2, P3, R, P4], {
      estimated_duration_seconds: 2400,
    });
    const DESTINATION_CONDITIONS = makeGenerationConditions({
      latitude: HERE.latitude,
      longitude: HERE.longitude,
      destination: DESTINATION,
    });

    /** 目的地を置いて2本の候補を作る。 */
    async function generateTwo(user: ReturnType<typeof userEvent.setup>) {
      await user.click(screen.getByRole("radio", { name: "目的地" }));
      act(() => mapView().onPinPlace("destination", DESTINATION));
      jobs.respond([BASE, OTHER], DESTINATION_CONDITIONS);
      await generate(user);
    }

    /** 先頭の候補で編集を始める。 */
    async function startEditing(user: ReturnType<typeof userEvent.setup>) {
      await user.click(await screen.findByRole("button", { name: "ルートを合成" }));
      await waitFor(() => expect(mapView().spliceStretches.length).toBeGreaterThan(0));
    }

    it("編集している間は地図で地点も区間も扱わず、全部の候補を重ねる。作り直すと編集が終わる", async () => {
      const { user } = renderHome();
      await generateTwo(user);
      await startEditing(user);
      expect(mapView().routes.map((candidate) => candidate.id)).toEqual(["base", "other"]);
      expect(mapView().armedPinRole).toBeNull();
      expect(mapView().pointEditingEnabled).toBe(false);

      act(() => mapView().onRouteSegmentSelect({ segment: SEGMENT, latitude: 35.6, longitude: 139.7 }));
      await user.click(screen.getByRole("button", { name: "編集をやめて候補へ戻る" }));
      expect(screen.queryByRole("button", { name: "区間の選択を解除" })).toBeNull();

      await user.click(screen.getByRole("button", { name: "ルートを合成" }));
      jobs.respond([BASE, OTHER], DESTINATION_CONDITIONS);
      await generate(user);
      await waitFor(() => expect(mapView().spliceStretches).toEqual([]));
      expect(mapView().splicedRoute).toBeNull();
      expect(screen.queryByRole("button", { name: "編集をやめて候補へ戻る" })).toBeNull();
    });

    it("作ると直前の作り直しの失敗の文言を消し、作った合成ルートを選んでいる間は、地図に元のルートだけを重ねる", async () => {
      const { user } = renderHome();
      await generateTwo(user);
      jobs.fail("混雑しています");
      await generate(user);
      expect(await screen.findByText(/作り直せませんでした/)).toBeInTheDocument();
      await startEditing(user);
      act(() => mapView().onSpliceStretchSelect(mapView().spliceStretches[0].index));
      jobs.respond([route("evaluated", { edge_ids: ["e1", "q1", "q2", "e3", "e4"] })], DESTINATION_CONDITIONS);
      await user.click(await screen.findByRole("button", { name: "新しいルートを作成" }));

      await waitFor(() => expect(mapView().routes).toHaveLength(2));
      const [origin, created] = mapView().routes;
      expect(origin.id).toBe("base");
      expect(mapView().selectedRouteId).toBe(created.id);
      expect(created.id).not.toBe("other");
      expect(screen.queryByText(/作り直せませんでした/)).toBeNull();
    });
  });

  it("研究モードの実験スロットは、「比較」を見ている間だけ地図へ重ねる", async () => {
    const { user } = renderHome();
    await user.click(screen.getByRole("button", { name: "メニュー" }));
    await user.click(screen.getByRole("checkbox", { name: "研究モード[実験スロット・比較・材料値]" }));
    await user.keyboard("{Escape}");
    jobs.respond([FIRST], LOOP_CONDITIONS);
    await generate(user);
    await waitFor(() => expect(candidateTabs().length).toBeGreaterThan(1));
    expect(mapView().experimentSlots).toEqual([]);

    await user.click(screen.getByRole("tab", { name: /比較/ }));
    expect(mapView().experimentSlots).toHaveLength(1);
    await user.click(candidateTabs()[0]);
    expect(mapView().experimentSlots).toEqual([]);
  });

  it("まとめて元に戻す操作: レイヤーを消すのはどれかを表示している間、絞り込みを解くのは凡例で隠している間だけ押せる。再描画は地図の描き直しを求める", async () => {
    const { user } = renderHome();
    const hideAll = screen.getByRole("button", { name: "表示中のレイヤーをすべて非表示にする" });
    expect(Object.values(mapView().look.layerVisibility)).toContain(true);
    await user.click(hideAll);
    expect(Object.values(mapView().look.layerVisibility)).not.toContain(true);
    expect(hideAll).toBeDisabled();

    const showAll = screen.getByRole("button", { name: "絞り込みをすべて解除する" });
    expect(showAll).toBeDisabled();
    jobs.respond([FIRST], LOOP_CONDITIONS);
    await generate(user);
    await user.click(await screen.findByRole("button", { name: /^地図の色分け: / }));
    const legendAll = await screen.findByRole("checkbox", { name: "凡例の全段階をまとめて表示/非表示" });
    await user.click(legendAll);
    await user.keyboard("{Escape}");
    expect(showAll).toBeEnabled();
    await user.click(showAll);
    expect(showAll).toBeDisabled();

    const before = mapView().look.refreshToken;
    await user.click(screen.getByRole("button", { name: "地図の表示を再描画する" }));
    expect(mapView().look.refreshToken).toBe(before + 1);
  });
});

describe("画面の枠", () => {
  it("スマホでは下部タブでシートを1枚ずつ開き、地図で地点を扱えるのは「ルート設定」の条件タブを開いている間だけ。結果の合図は「ルート結果」を開くまで残り、入力の誤りは「ルート設定」にも出す", async () => {
    installGeolocation(null);
    useMobileLayout();
    const { user } = renderHome();
    const settingsTab = () => screen.getByRole("button", { name: "ルート設定", expanded: false });
    const outcomeTab = screen.getByRole("button", { name: "ルート結果" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mapView().measureRouteFitObscuredPx?.()).toEqual({ bottom: 0 });

    await user.click(settingsTab());
    const settingsSheet = screen.getByRole("dialog", { name: "ルート設定" });
    expect(mapView().measureRouteFitObscuredPx?.()).toEqual({ bottom: window.innerHeight * 0.5 });
    await user.click(within(settingsSheet).getByRole("button", { name: "ルート生成" }));
    expect(within(settingsSheet).getByText(/^現在地が分かりません/)).toBeInTheDocument();
    expect(outcomeTab).toHaveAccessibleDescription("生成に失敗しました");

    await user.click(within(settingsSheet).getByRole("button", { name: "出発地を地図で選ぶ" }));
    expect(mapView().armedPinRole).toBe("origin");
    expect(mapView().pointEditingEnabled).toBe(true);
    await user.click(within(settingsSheet).getByRole("tab", { name: "重み" }));
    expect(mapView().pointEditingEnabled).toBe(false);
    await user.click(within(settingsSheet).getByRole("tab", { name: "条件" }));
    act(() => mapView().onPinPlace("origin", HERE));
    jobs.respond([FIRST], LOOP_CONDITIONS);
    expect(await generate(user)).toMatchObject({ latitude: HERE.latitude, longitude: HERE.longitude });
    await waitFor(() => expect(outcomeTab).toHaveAccessibleDescription("新しい結果があります"));

    await user.click(outcomeTab);
    expect(screen.queryByRole("dialog", { name: "ルート設定" })).toBeNull();
    const outcomeSheet = screen.getByRole("dialog", { name: "ルート結果" });
    expect(within(outcomeSheet).getByRole("button", { name: "候補を全消去" })).toBeInTheDocument();
    expect(outcomeTab).not.toHaveAccessibleDescription();
    await user.click(within(outcomeSheet).getByRole("button", { name: "閉じる" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(settingsTab());
    fireEvent.change(screen.getByLabelText("距離"), { target: { value: "50" } });
    expect(outcomeTab).toHaveAccessibleDescription("生成条件が変更されています");
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
    expect(mapView().measureRouteFitObscuredPx?.()).toBeUndefined();
  });

  it("ヘッダーの「未取得」に、現在地・軸の一覧・警報の取れないものが並ぶ。「現在地に移動」が取れなければ地図の上に理由を出す", async () => {
    installGeolocation(null);
    onBackend("GET", "/api/axis-catalog", () => Response.json({ detail: "失敗" }, { status: 502 }));
    onBackend("GET", "/api/weather/warnings", () => Response.json({ detail: "失敗" }, { status: 502 }));
    const { user } = renderHome();
    const missing = () => screen.getByRole("button", { name: /を取得できていません/ });
    await waitFor(() => expect(missing()).toHaveAccessibleName(/現在地.*軸一覧|軸一覧.*現在地/));
    expect(missing()).not.toHaveAccessibleName(/警報/);

    await user.click(screen.getByRole("button", { name: "現在地に移動" }));
    expect(screen.getByText(/現在地を取得できませんでした/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "出発地を地図で選ぶ" }));
    act(() => mapView().onPinPlace("origin", HERE));
    await waitFor(() => expect(missing()).toHaveAccessibleName(/警報/));
    expect(missing()).not.toHaveAccessibleName(/現在地/);
  });

  it("メニューから使い方の説明に入って「やめる」で抜け、デバッグログをメニューから開いてログの側から閉じられる", async () => {
    setDebugEnabled(true);
    const { user } = renderHome();
    await user.click(screen.getByRole("button", { name: "メニュー" }));
    await user.click(screen.getByRole("button", { name: "使い方を見る" }));
    expect(screen.getByText("説明を見たい部品を押してください")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "やめる" }));
    expect(screen.queryByText("説明を見たい部品を押してください")).toBeNull();

    await user.click(screen.getByRole("button", { name: "メニュー" }));
    await user.click(screen.getByRole("button", { name: "デバッグログを表示" }));
    expect(screen.getByText(/^デバッグログ\[/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^デバッグログ\[.*を閉じる$/ }));
    expect(screen.queryByText(/^デバッグログ\[/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "メニュー" }));
    expect(screen.getByRole("button", { name: "デバッグログを表示" })).toBeInTheDocument();
  });
});
