import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AxisCatalogResponse } from "@/types/route";

// デッドコード監査（2026-08-25）回帰テスト: layerVisibility永続化ホワイトリストの静的固定
// バグ修正。以前はuseStoredStateのdeserializeが常にDEFAULT_LAYER_VISIBILITY（ビルド時
// 静的7軸ぶんのキー）だけを走査していたため、軸スタジオで新規公開されたGUI作成軸
// （axis:xxx）のON/OFF保存値が復元時に黙って捨てられていた。ここでは、GUI作成軸を含む
// カタログをGET /api/axis-catalogのモックで返し、localStorageにその軸をONにした保存値を
// 仕込んだ状態でHomeをマウントし、カタログ取得完了後にON状態が復元されることを確認する。
//
// page.tsxは地図・位置情報・天候等の重いコンポーネント/フックを多数使うため、本テストの
// 関心事（layerVisibilityの永続化・復元）に無関係なものはすべて軽量スタブへ差し替える。
// MapOverlayControlsだけは、実際に組み立てられたlayers（id・on）をそのまま可視化する
// スタブにして、テストからlayerVisibilityの実効値を検証できるようにする。

vi.mock("@/components/Map/MapView", () => ({ default: () => null }));
vi.mock("@/components/MapLayersPanel/MapLayersPanel", () => ({ default: () => null }));
vi.mock("@/components/RouteForm/RouteForm", () => ({ default: () => null }));
vi.mock("@/components/RouteList/RouteList", () => ({ default: () => null }));
vi.mock("@/components/WeatherPanel/WeatherPanel", () => ({ default: () => null }));
vi.mock("@/components/WarningBadge/WarningBadge", () => ({ default: () => null }));
vi.mock("@/components/DynamicLayerTimeSlider/DynamicLayerTimeSlider", () => ({ default: () => null }));
vi.mock("@/components/ComparisonPanel/ComparisonPanel", () => ({ default: () => null }));
vi.mock("@/components/DebugConsole/DebugConsole", () => ({ default: () => null }));

vi.mock("@/components/RouteSettingsPanel/RouteSettingsPanel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/RouteSettingsPanel/RouteSettingsPanel")>();
  return { ...actual, default: () => null };
});

// 実際に組み立てられたoverlayLayers（id・on）をテストから読み取れるようにするスタブ。
vi.mock("@/components/MapOverlayControls/MapOverlayControls", () => ({
  default: (props: { layers: Array<{ id: string; on: boolean }> }) => (
    <div data-testid="overlay-layers">{JSON.stringify(props.layers.map((l) => [l.id, l.on]))}</div>
  ),
}));

vi.mock("@/hooks/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("@/hooks/useResearchMode", () => ({ useResearchEnabled: () => false }));
vi.mock("@/hooks/useDebugLog", () => ({ useDebugEnabled: () => false }));

vi.mock("@/hooks/useLocation", () => ({
  useLocation: () => ({
    location: { latitude: 35.7597, longitude: 139.7387 },
    locationSource: "default",
    locationReady: true,
    locating: false,
    locateError: null,
    handleLocateMe: vi.fn(),
  }),
}));

vi.mock("@/services/weatherApi", () => ({
  getCurrentWeather: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
  getFloodForecasts: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
  getWbgtStatus: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
  getWeatherWarnings: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
}));

vi.mock("@/services/axisCatalogApi", () => ({
  getAxisCatalog: vi.fn(),
}));

import { getAxisCatalog } from "@/services/axisCatalogApi";
import Home from "./page";

const LAYER_VISIBILITY_STORAGE_KEY = "ridecompass:layer-visibility";

// 軸スタジオで新規公開されたGUI作成軸を1つだけ含むカタログ（kind="ramp"なので
// mapLayers.ts: buildMapLayersが二次軸rampレイヤーとして拾い、axis:gui_created_axisという
// レイヤーIDになる、axisLayers.ts: axisMapLayerId参照）。
function catalogWithGuiCreatedAxis(): AxisCatalogResponse {
  return {
    axes: [
      {
        axis_id: "gui_created_axis",
        label: "GUI作成軸",
        description: "",
        category: "動的",
        default_weight: 0.1,
        display: {
          kind: "ramp",
          label: "GUI作成軸",
          category: "trafficSafety",
          tile_inputs: [],
          thresholds: [1, 2, 3],
          unit: "",
          note: "",
        },
        primary_attribute_ids: [],
        icon_id: null,
        chip_label: null,
        panel_hint: null,
        show_map_icon: true,
      },
    ],
  };
}

describe("Home（app/page.tsx） layerVisibilityの永続化", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
    vi.mocked(getAxisCatalog).mockReset();
  });

  it("GUI作成軸をONにした保存値は、カタログ取得完了後に復元される（実バグ修正の回帰テスト）", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogWithGuiCreatedAxis());
    // 「GUI作成軸をONにしてリロードした」状態を模した保存値。
    window.localStorage.setItem(
      LAYER_VISIBILITY_STORAGE_KEY,
      JSON.stringify({ route: true, "axis:gui_created_axis": true }),
    );

    render(<Home />);

    // カタログ取得（axisCatalog.loaded===true）完了後、layerVisibilityの復元effectが
    // 実行時カタログ由来のキー集合で再実行され、axis:gui_created_axisがONとして
    // 復元される（このJSONに現れる時点でmapLayersにも含まれていることが分かる）。
    await waitFor(() => {
      const text = screen.getByTestId("overlay-layers").textContent ?? "";
      expect(text).toContain('["axis:gui_created_axis",true]');
    });
  });

  it("保存値が無ければGUI作成軸は既定でOFFのまま", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogWithGuiCreatedAxis());

    render(<Home />);

    // 保存値が無い場合、layerVisibilityは初期値（DEFAULT_LAYER_VISIBILITY）のまま変わらない
    // ため、ビルド時静的集合に含まれないaxis:gui_created_axisはキー自体が無い
    // （JSON.stringifyでnullになる=truthyではない）。少なくとも「ONとして復元される」
    // という誤りは起きないことを確認する。
    await waitFor(() => {
      const text = screen.getByTestId("overlay-layers").textContent ?? "";
      expect(text).toContain('"axis:gui_created_axis"');
    });
    const text = screen.getByTestId("overlay-layers").textContent ?? "";
    const layers = JSON.parse(text) as Array<[string, boolean | null]>;
    const guiAxisEntry = layers.find(([id]) => id === "axis:gui_created_axis");
    expect(guiAxisEntry?.[1]).not.toBe(true);
  });
});

// ============================================================================
// 改善計画T331: handleGenerateハンドラ・4並列fetch（天候・警報・WBGT・氾濫予報）の競合
// 対策ロジックのテスト追加。上のdescribeブロックはlayerVisibilityの永続化のみを検証して
// おり、page.tsxが持つ15個以上のハンドラのうち直接検証されているものが実質0個だった。
// 特に無防備だった以下2点をここで追加する。実装（page.tsx）自体は変更しない。
//   1. handleGenerate（ルート生成ボタンのハンドラ）の「0件成功」「例外による失敗」
//      「研究モードでのスロット記録」の3分岐。
//   2. fetchWeatherFor/fetchWarningsFor/fetchWbgtFor/fetchFloodForecastsForが持つ
//      「リクエストIDで古い応答を捨てる」競合対策（page.tsx冒頭のlatestXxxRequestId ref参照）。
//
// 上のdescribeブロックのvi.mock群はファイル全体（このファイルの静的`import Home from
// "./page"`）に効くため、RouteFormは常にnull・useLocationは常に固定値のままである。
// ここで必要な「実際のRouteFormを操作する」「locationを連続変更する」「researchEnabledを
// trueにする」といった、上とは異なる振る舞いは、vi.doMock + vi.resetModules() +
// 動的import("./page")で1テストごとに独立したHomeを組み立てて実現する（静的importの
// Homeや上の2テストには一切影響しない。doMockは非hoistedのため、上のvi.mock群と衝突
// しない別レジストリ操作として扱われる）。
// ============================================================================

import { useEffect, useState } from "react";
import { act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { generateRoutes } from "@/services/routeApi";
import { getCurrentWeather, getWeatherWarnings, getWbgtStatus, getFloodForecasts } from "@/services/weatherApi";
import type { RouteCandidate, GenerationConditions } from "@/types/route";
import type { WeatherConditions, WeatherWarnings, WbgtStatus, FloodForecasts } from "@/types/weather";

// "@/services/routeApi"はこれまでどのテストもモックしていなかった新規モジュール。
// generateRoutesは実I/O（fetch）を伴うため、既存の他サービスモックと同じくvi.fn()化する。
vi.mock("@/services/routeApi", () => ({
  generateRoutes: vi.fn(),
  previewRoute: vi.fn(),
}));

// ComparisonPanel.test.tsxのmakeCandidate/makeSlotと同じ形の最小フィクスチャ
// （RouteCandidate/GenerationConditionsは必須フィールドが多いOpenAPI生成型のため、
// 呼び出し側で上書きしたいフィールドだけ渡せるヘルパーにする）。
function makeCandidate(overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return {
    id: "route-1",
    direction_label: "北",
    distance_km: 30,
    geometry: { type: "LineString", coordinates: [] },
    elevation_gain_m: null,
    min_elevation_m: null,
    max_elevation_m: null,
    max_gradient_percent: null,
    wind_score: null,
    road_score: null,
    stop_density: null,
    car_stress_score: null,
    bicycle_infra_score: null,
    intersection_density: null,
    accident_density: null,
    total_score: 88,
    score_breakdown: null,
    segments: null,
    overall_difficulty: null,
    ...overrides,
  };
}

function makeConditions(overrides: Partial<GenerationConditions> = {}): GenerationConditions {
  return {
    latitude: 35.7597,
    longitude: 139.7387,
    distance_km: 30,
    distance_tolerance_km: 5,
    scoring_weights: { distance_weight: 0.3, elevation_weight: 0.15, wind_weight: 0.3, road_weight: 0.25 },
    route_preference: {},
    penalty_strength: 1.0,
    max_average_grade_percent: null,
    hard_filters: { no_bicycle: true, motorway: true, trunk: true },
    waypoints: null,
    destination: null,
    generated_at: "2026-08-25T12:00:00+09:00",
    ...overrides,
  };
}

// 既定のuseLocation（上のdescribeブロックの固定値と同じ内容）。
function defaultUseLocationDouble() {
  return {
    location: { latitude: 35.7597, longitude: 139.7387 },
    locationSource: "default" as const,
    locationReady: true,
    locating: false,
    locateError: null,
    handleLocateMe: vi.fn(),
  };
}

// 「地点を連続変更する」系の競合対策テスト専用のuseLocation二重体。内部でuseStateを
// 持ち、コミット後にeffect経由で最新のsetterをモジュール変数latestLocationSetterへ記録する
// （レンダー中の代入はReactの純粋性ルールに反するため、必ずuseEffect内で行う）。
// テスト側はact()経由でこのsetterを呼び、location変更→依存effect再実行を発火させる
// （これによりfetchWeatherFor等が2回目の呼び出しを行う状況を再現する）。
let latestLocationSetter: ((next: { latitude: number; longitude: number }) => void) | null = null;
function useStatefulLocationDouble() {
  const [location, setLocation] = useState({ latitude: 35.0, longitude: 139.0 });
  useEffect(() => {
    latestLocationSetter = setLocation;
    // setLocationの参照はReactが再レンダー間で安定させることを保証しているため、
    // マウント時に一度記録すれば十分（依存配列は空でよい）。
  }, []);
  return {
    location,
    locationSource: "default" as const,
    locationReady: true,
    locating: false,
    locateError: null,
    handleLocateMe: vi.fn(),
  };
}

interface RenderFreshHomeOptions {
  /** trueなら実際のRouteFormを使う（生成ボタンをクリックするため）。既定は上と同じnullモック。 */
  realRouteForm?: boolean;
  /** trueなら地点を連続変更できるstateful二重体、falseならdefaultUseLocationDoubleの固定値。 */
  statefulLocation?: boolean;
  researchEnabled?: boolean;
  exposeComparisonSlots?: boolean;
  exposeWeatherPanel?: boolean;
  exposeWarningBadges?: boolean;
}

// 1テストごとに独立した振る舞いのHomeを組み立てる。vi.resetModules()でモジュール
// キャッシュを空にした上で、必要なモジュールだけvi.doMock/vi.doUnmockし直してから
// 動的importする（実験的に確認済み: vi.mockの対象になっていないモジュール
// [例: 上の"@/hooks/useIsMobile"のような既存の固定モック]はresetModules()後も同じ
// モックオブジェクトを指し続けるため、ここで明示的に触らないモジュールは上の
// describeブロックと同じ既存モックのまま動く）。
async function renderFreshHome(options: RenderFreshHomeOptions = {}) {
  vi.resetModules();

  if (options.realRouteForm) {
    vi.doUnmock("@/components/RouteForm/RouteForm");
  } else {
    vi.doMock("@/components/RouteForm/RouteForm", () => ({ default: () => null }));
  }

  vi.doMock("@/hooks/useLocation", () => ({
    useLocation: options.statefulLocation ? useStatefulLocationDouble : defaultUseLocationDouble,
  }));

  vi.doMock("@/hooks/useResearchMode", () => ({
    useResearchEnabled: () => options.researchEnabled ?? false,
  }));

  vi.doMock("@/components/ComparisonPanel/ComparisonPanel", () => ({
    // slot.id自体は`slot-${generated_at}-${random}`という生成条件由来の識別子であり
    // 候補を区別できないため、実際に記録された候補（topCandidate.id）の並びを見る。
    default: options.exposeComparisonSlots
      ? (props: { slots: Array<{ topCandidate: { id: string } }> }) => (
          <div data-testid="comparison-slots">{JSON.stringify(props.slots.map((s) => s.topCandidate.id))}</div>
        )
      : () => null,
  }));

  vi.doMock("@/components/WeatherPanel/WeatherPanel", () => ({
    default: options.exposeWeatherPanel
      ? (props: { weather: { temperature_c: number } | null }) => (
          <div data-testid="weather-panel">{JSON.stringify({ temp: props.weather?.temperature_c ?? null })}</div>
        )
      : () => null,
  }));

  vi.doMock("@/components/WarningBadge/WarningBadge", () => ({
    default: options.exposeWarningBadges
      ? (props: { items: Array<{ id: string; source: string; label: string }> }) => (
          <div data-testid="warning-badges">
            {JSON.stringify(props.items.map((i) => [i.source, i.id, i.label]))}
          </div>
        )
      : () => null,
  }));

  const { default: HomeFresh } = await import("./page");
  return HomeFresh;
}

// Promiseの解決タイミングをテストから制御するためのヘルパー（応答順序の入れ替え検証に使う）。
function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("Home（app/page.tsx） handleGenerateハンドラ", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(getAxisCatalog).mockRejectedValue(new Error("mock: unused in this test"));
  });
  afterEach(() => {
    window.localStorage.clear();
    vi.mocked(generateRoutes).mockReset();
    vi.mocked(getAxisCatalog).mockReset();
    // このdescribeブロックのHomeマウントもfetchWeatherFor等（4並列fetch）を必ず1回ずつ
    // 発火させる（renderFreshHomeがexposeWeatherPanel等を指定していないため未使用の
    // レスポンスとして握りつぶされるだけだが、getCurrentWeather等は下の
    // 「並列fetchの競合対策」describeブロックとvi.fn()インスタンスを共有している。
    // 呼び出し回数をクリアしておかないと、そちらのtoHaveBeenCalledTimes(1)が
    // このブロックぶんの呼び出しを含んでしまい失敗する）。
    vi.mocked(getCurrentWeather).mockClear();
    vi.mocked(getWeatherWarnings).mockClear();
    vi.mocked(getWbgtStatus).mockClear();
    vi.mocked(getFloodForecasts).mockClear();
    latestLocationSetter = null;
  });

  it("候補0件で成功したとき、専用のエラーメッセージを表示する", async () => {
    const user = userEvent.setup();
    vi.mocked(generateRoutes).mockResolvedValueOnce({
      routes: [],
      conditions: makeConditions(),
      engine: "road_graph",
    });
    const HomeFresh = await renderFreshHome({ realRouteForm: true });
    render(<HomeFresh />);

    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "条件に合うルート候補が見つかりませんでした。距離を変えて試してください。",
      );
    });
    // 候補0件はエラー表示であって例外ではないため、次に条件を変えて再試行できるよう
    // loading状態も解除されている（ボタンが再び押せる）ことを合わせて確認する。
    expect(screen.getByRole("button", { name: "ルート生成" })).not.toBeDisabled();
  });

  it("改善計画T365: 「ルートをクリア」ボタンで生成済みの候補一覧をリセットできる", async () => {
    // RouteList自体はこのファイル全体でモック済み（21行目のvi.mock、内容表示は
    // RouteList.test.tsxが別途検証済み）のため、ここではpage.tsx側の状態
    // （routes.length > 0で出す「ルートをクリア」ボタン自体の表示/非表示）で
    // handleRoutesClearの配線を検証する。
    const user = userEvent.setup();
    vi.mocked(generateRoutes).mockResolvedValueOnce({
      routes: [makeCandidate()],
      conditions: makeConditions(),
      engine: "road_graph",
    });
    const HomeFresh = await renderFreshHome({ realRouteForm: true });
    render(<HomeFresh />);

    expect(screen.queryByRole("button", { name: "ルートをクリア" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "ルートをクリア" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "ルートをクリア" }));

    expect(screen.queryByRole("button", { name: "ルートをクリア" })).not.toBeInTheDocument();
  });

  it("生成中に例外が投げられたとき、そのメッセージをエラー表示する", async () => {
    const user = userEvent.setup();
    vi.mocked(generateRoutes).mockRejectedValueOnce(new Error("バックエンドに到達できませんでした"));
    const HomeFresh = await renderFreshHome({ realRouteForm: true });
    render(<HomeFresh />);

    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("バックエンドに到達できませんでした");
    });
  });

  it("研究モード中に生成が成功すると実験スロットへ記録され、新しい生成が先頭に積まれる", async () => {
    const user = userEvent.setup();
    vi.mocked(generateRoutes)
      .mockResolvedValueOnce({
        routes: [makeCandidate({ id: "route-a" })],
        conditions: makeConditions(),
        engine: "road_graph",
      })
      .mockResolvedValueOnce({
        routes: [makeCandidate({ id: "route-b" })],
        conditions: makeConditions(),
        engine: "road_graph",
      });
    const HomeFresh = await renderFreshHome({
      realRouteForm: true,
      researchEnabled: true,
      exposeComparisonSlots: true,
    });
    render(<HomeFresh />);

    const generateButton = screen.getByRole("button", { name: "ルート生成" });
    await user.click(generateButton);
    await waitFor(() => {
      expect(screen.getByTestId("comparison-slots")).toHaveTextContent('["route-a"]');
    });

    await user.click(generateButton);
    await waitFor(() => {
      // 新しいスロットが先頭に積まれる（page.tsx: handleGenerate内のsetExperimentSlots参照）。
      expect(screen.getByTestId("comparison-slots")).toHaveTextContent('["route-b","route-a"]');
    });
  });
});

describe("Home（app/page.tsx） 天候・警報・WBGT・氾濫予報の並列fetchの競合対策", () => {
  function makeWeather(temperature_c: number): WeatherConditions {
    return {
      temperature_c,
      apparent_temperature_c: null,
      wind_speed_ms: 3,
      wind_direction_deg: 90,
      wind_direction_label: "東",
      wind_gusts_ms: null,
      precipitation_probability_percent: null,
      precipitation_mm: null,
      uv_index: null,
      observed_at: "2026-08-25T12:00:00+09:00",
    };
  }
  function makeWarnings(name: string): WeatherWarnings {
    return {
      area_name: null,
      report_datetime: null,
      warnings: [{ code: name, name, level: "warning", additions: [] }],
    };
  }
  function makeWbgt(label: string, value: number): WbgtStatus {
    return { level: "warning", label, value, observed_at: null };
  }
  function makeFlood(label: string): FloodForecasts {
    return {
      forecasts: [
        {
          river_code: label,
          river_name: label,
          level: 1,
          badge_level: "warning",
          label,
          condition: "氾濫注意情報",
          report_datetime: "2026-08-25T12:00:00+09:00",
        },
      ],
    };
  }

  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
    vi.mocked(getCurrentWeather).mockReset();
    vi.mocked(getWeatherWarnings).mockReset();
    vi.mocked(getWbgtStatus).mockReset();
    vi.mocked(getFloodForecasts).mockReset();
    vi.mocked(getAxisCatalog).mockReset();
    latestLocationSetter = null;
  });

  it("地点を連続変更したとき、天候・警報・WBGT・氾濫予報の4つとも古い応答が新しい応答を上書きしない", async () => {
    vi.mocked(getAxisCatalog).mockRejectedValue(new Error("mock: unused in this test"));

    // それぞれ「1回目(古い方)」「2回目(新しい方)」のリクエストに対応するdeferredを用意し、
    // あとで意図的に2回目→1回目の順で解決する(応答順序の入れ替え、テスト方針#5)。
    const weatherOld = createDeferred<WeatherConditions>();
    const weatherNew = createDeferred<WeatherConditions>();
    vi.mocked(getCurrentWeather)
      .mockImplementationOnce(() => weatherOld.promise)
      .mockImplementationOnce(() => weatherNew.promise);

    const warningsOld = createDeferred<WeatherWarnings>();
    const warningsNew = createDeferred<WeatherWarnings>();
    vi.mocked(getWeatherWarnings)
      .mockImplementationOnce(() => warningsOld.promise)
      .mockImplementationOnce(() => warningsNew.promise);

    const wbgtOld = createDeferred<WbgtStatus>();
    const wbgtNew = createDeferred<WbgtStatus>();
    vi.mocked(getWbgtStatus)
      .mockImplementationOnce(() => wbgtOld.promise)
      .mockImplementationOnce(() => wbgtNew.promise);

    const floodOld = createDeferred<FloodForecasts>();
    const floodNew = createDeferred<FloodForecasts>();
    vi.mocked(getFloodForecasts)
      .mockImplementationOnce(() => floodOld.promise)
      .mockImplementationOnce(() => floodNew.promise);

    const HomeFresh = await renderFreshHome({
      statefulLocation: true,
      exposeWeatherPanel: true,
      exposeWarningBadges: true,
    });
    render(<HomeFresh />);

    // マウント直後の1回目のfetch(古い方のリクエスト)が発火するまで待つ。
    await waitFor(() => {
      expect(getCurrentWeather).toHaveBeenCalledTimes(1);
      expect(getWeatherWarnings).toHaveBeenCalledTimes(1);
      expect(getWbgtStatus).toHaveBeenCalledTimes(1);
      expect(getFloodForecasts).toHaveBeenCalledTimes(1);
    });

    // 地点を変更し、2件目(新しい方)のリクエストを発火させる。
    await act(async () => {
      latestLocationSetter?.({ latitude: 36.0, longitude: 140.0 });
    });
    await waitFor(() => {
      expect(getCurrentWeather).toHaveBeenCalledTimes(2);
      expect(getWeatherWarnings).toHaveBeenCalledTimes(2);
      expect(getWbgtStatus).toHaveBeenCalledTimes(2);
      expect(getFloodForecasts).toHaveBeenCalledTimes(2);
    });

    // 後から投げた(新しい)リクエストを先に解決する。
    await act(async () => {
      weatherNew.resolve(makeWeather(20));
      warningsNew.resolve(makeWarnings("新警報"));
      wbgtNew.resolve(makeWbgt("危険", 32));
      floodNew.resolve(makeFlood("新氾濫予報"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("weather-panel")).toHaveTextContent('"temp":20');
      const badgesText = screen.getByTestId("warning-badges").textContent ?? "";
      expect(badgesText).toContain("新警報");
      expect(badgesText).toContain("危険");
      expect(badgesText).toContain("新氾濫予報");
    });

    // 先に投げた(古い)リクエストが後から解決しても、新しい応答を上書きしない。
    await act(async () => {
      weatherOld.resolve(makeWeather(10));
      warningsOld.resolve(makeWarnings("旧警報"));
      wbgtOld.resolve(makeWbgt("警戒", 28));
      floodOld.resolve(makeFlood("旧氾濫予報"));
    });
    // .then内のrequestId比較チェック(マイクロタスク経由)が確実に走るのを待つ。
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByTestId("weather-panel")).toHaveTextContent('"temp":20');
    expect(screen.getByTestId("weather-panel")).not.toHaveTextContent('"temp":10');
    const badgesText = screen.getByTestId("warning-badges").textContent ?? "";
    expect(badgesText).toContain("新警報");
    expect(badgesText).not.toContain("旧警報");
    expect(badgesText).toContain("危険");
    expect(badgesText).not.toContain("警戒");
    expect(badgesText).toContain("新氾濫予報");
    expect(badgesText).not.toContain("旧氾濫予報");
  });

  it("天候fetch単体でも、2回目に投げたリクエストが先に解決すれば古い1回目の応答は無視される", async () => {
    vi.mocked(getAxisCatalog).mockRejectedValue(new Error("mock: unused in this test"));
    vi.mocked(getWeatherWarnings).mockResolvedValue({ area_name: null, report_datetime: null, warnings: [] });
    vi.mocked(getWbgtStatus).mockResolvedValue({ level: null, label: null, value: null, observed_at: null });
    vi.mocked(getFloodForecasts).mockResolvedValue({ forecasts: [] });

    const first = createDeferred<WeatherConditions>();
    const second = createDeferred<WeatherConditions>();
    vi.mocked(getCurrentWeather)
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);

    const HomeFresh = await renderFreshHome({ statefulLocation: true, exposeWeatherPanel: true });
    render(<HomeFresh />);

    await waitFor(() => expect(getCurrentWeather).toHaveBeenCalledTimes(1));
    await act(async () => {
      latestLocationSetter?.({ latitude: 36.0, longitude: 140.0 });
    });
    await waitFor(() => expect(getCurrentWeather).toHaveBeenCalledTimes(2));

    // 2回目(新しい方)を先に解決する(テスト方針#5: 応答順序の意図的な入れ替え)。
    await act(async () => {
      second.resolve(makeWeather(25));
    });
    await waitFor(() => expect(screen.getByTestId("weather-panel")).toHaveTextContent('"temp":25'));

    // 1回目(古い方)が後から解決しても上書きされない。
    await act(async () => {
      first.resolve(makeWeather(5));
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByTestId("weather-panel")).toHaveTextContent('"temp":25');
    expect(screen.getByTestId("weather-panel")).not.toHaveTextContent('"temp":5');
  });
});
