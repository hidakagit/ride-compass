import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
// 改善計画T406: 排他ドメイン（道路/評価軸/環境/スポット）のON/OFF実装はpage.tsx:
// handleLayerToggle側にあるため、そのハンドラをテストから直接クリックで駆動できるよう
// レイヤーごとの切り替えボタンも描画する（onToggle(id, !on)を呼ぶだけの薄いスタブ）。
vi.mock("@/components/MapOverlayControls/MapOverlayControls", () => ({
  default: (props: {
    layers: Array<{ id: string; on: boolean; title?: string }>;
    onToggle: (id: string, on: boolean) => void;
  }) => (
    <>
      {/* JSON文字列の要素自体はbutton群を子に含めない（既存テストがtextContentを丸ごと
          JSON.parseするため、button群を同じ要素の子にするとテキストが混ざって壊れる）。 */}
      <div data-testid="overlay-layers">{JSON.stringify(props.layers.map((l) => [l.id, l.on]))}</div>
      {/* titleは既存の"overlay-layers"（[id, on]の2要素固定を前提にした既存の
          exact-substring/new Map()アサーションが複数ある）とは別の独立したtestidへ出す
          （改善計画T478、T468のisDynamicGroupLayer回帰テスト用）。 */}
      <div data-testid="overlay-layer-titles">{JSON.stringify(props.layers.map((l) => [l.id, l.title]))}</div>
      {props.layers.map((l) => (
        <button key={l.id} type="button" onClick={() => props.onToggle(l.id, !l.on)}>
          {`toggle:${l.id}`}
        </button>
      ))}
    </>
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
  getAmedasObservation: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
  getFloodForecasts: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
  getWbgtStatus: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
  getWeatherWarnings: vi.fn().mockRejectedValue(new Error("mock: unused in this test")),
}));

vi.mock("@/services/axisCatalogApi", () => ({
  getAxisCatalog: vi.fn(),
}));

import { getAxisCatalog } from "@/services/axisCatalogApi";
import { __resetAxisCatalogStoreForTests } from "@/hooks/useAxisCatalog";
import Home from "./page";

// 改善計画T527: useAxisCatalogのフェッチ結果はモジュールレベルの共有ストアのため、
// 前のテストで解決したカタログが次のテストの初期表示へ持ち越されないようリセットする。
beforeEach(() => {
  __resetAxisCatalogStoreForTests();
});

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
        shape: { kind: "breakpoint_linear", terms: [{ material: "lanes_count", weight: 1.0, required: true }], preprocess: "identity", breakpoints: [[0, 0], [10, 100]] },
        display_thresholds_override: null,
        display_band_labels_override: null,
        dedicated_way_value_layer: false,
      },
    ],
    // 改善計画T404: material_runtime_scalesはAxisCatalogResponseの必須フィールド
    // （既定{}だがopenapi-typescriptはdefault付きフィールドをoptionalにしない）。
    material_runtime_scales: {},
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

  it("route:false（T518以前の意味で保存された値）は移行後trueとしてlocalStorageへも" +
    "書き戻される（実バグ修正の回帰テスト、2026-09-03ユーザー指摘「進行方向の矢印が" +
    "以前は出てたのに消えている」）。reloadKey（axisCatalog.loaded）によりdeserializeが" +
    "マウント直後・カタログ取得完了後の2回走るが、1回目の移行結果をlocalStorageへ" +
    "書き戻さないと2回目が古いroute:falseを読み直して巻き戻る不具合があった", async () => {
    vi.mocked(getAxisCatalog).mockResolvedValue(catalogWithGuiCreatedAxis());
    window.localStorage.setItem(LAYER_VISIBILITY_STORAGE_KEY, JSON.stringify({ route: false }));

    render(<Home />);

    await waitFor(() => {
      const stored = window.localStorage.getItem(LAYER_VISIBILITY_STORAGE_KEY);
      expect(stored).not.toBeNull();
      expect((JSON.parse(stored ?? "{}") as { route?: boolean }).route).toBe(true);
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
// 改善計画T406/T418: パネル構成再編（道路/環境/スポットの3チップ・3排他ドメイン、
// docs/tasks/T400.md「1. パネルの最上位グルーピング」節）。T406時点は「道路」と
// 「評価軸」が排他ドメイン(line)を共有していたが、T418で評価軸チップ自体を地図UIから
// 撤去したため道路は単独ドメインになった。軸スタジオ由来のレイヤー（ramp軸・windAxis）は
// 地図上チップの3ドメインとは独立に、同士だけで1つだけ選べる排他制御を維持する
// （同じ道路ジオメトリへ線を重ねて見にくくなることを防ぐという元々の目的は変わらない
// ため、docs/tasks/T418.md参照）。排他ドメイン判定自体（mapOverlayGroupFor/
// mapOverlayExclusiveDomainFor、mapLayers.ts）はMapOverlayControls.test.tsxで検証済みだが、
// 実際にONにした際の排他ロジック本体はpage.tsx: handleLayerToggleにあるため、ここでは
// 上のdescribeブロックと同じくMapOverlayControlsを軽量スタブに差し替え、スタブが呼ぶ
// onToggleが実際のhandleLayerToggleへ届くことを利用して検証する（スタブはlayers.idごとに
// toggle:${id}という名前のボタンを描画し、押すとonToggle(id, !on)を呼ぶ）。
// getAxisCatalogは解決させない（実行時カタログが未取得の間の静的フォールバックRAMP_AXESの
// ままレイヤーカタログを固定するため。解決させるとテストの axes: [] が実カタログとして
// 上書きされ、axis:car_stress等の二次軸レイヤー自体が消えてしまう）。
describe("Home（app/page.tsx） レイヤー排他ドメイン（改善計画T406/T418）", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
    vi.mocked(getAxisCatalog).mockReset();
  });

  function overlayLayersOnMap(): Map<string, boolean> {
    const text = screen.getByTestId("overlay-layers").textContent ?? "[]";
    const layers = JSON.parse(text) as Array<[string, boolean]>;
    return new Map(layers);
  }

  it("道路は単独ドメイン: 道路をONにしても評価軸（ramp軸）はOFFにならない", async () => {
    vi.mocked(getAxisCatalog).mockReturnValue(new Promise(() => {})); // 解決させない（静的フォールバックのまま固定）
    render(<Home />);

    fireEvent.click(await screen.findByRole("button", { name: "toggle:axis:car_stress" }));
    expect(overlayLayersOnMap().get("axis:car_stress")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "toggle:roadType" }));
    const afterRoadOn = overlayLayersOnMap();
    expect(afterRoadOn.get("roadType")).toBe(true);
    // T418で道路と評価軸の排他ドメイン共有を廃止したため、両方ONのまま保たれる
    expect(afterRoadOn.get("axis:car_stress")).toBe(true);
  });

  it("軸スタジオ由来のレイヤー同士は排他: 別の評価軸をONにすると前の評価軸はOFFになるが、道路には影響しない", async () => {
    vi.mocked(getAxisCatalog).mockReturnValue(new Promise(() => {}));
    render(<Home />);

    fireEvent.click(await screen.findByRole("button", { name: "toggle:roadType" }));
    fireEvent.click(screen.getByRole("button", { name: "toggle:axis:car_stress" }));
    const afterCarStressOn = overlayLayersOnMap();
    expect(afterCarStressOn.get("roadType")).toBe(true); // 道路は影響を受けない
    expect(afterCarStressOn.get("axis:car_stress")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "toggle:windAxis" }));
    const afterWindAxisOn = overlayLayersOnMap();
    expect(afterWindAxisOn.get("axis:car_stress")).toBe(false); // 軸スタジオ由来同士は排他
    expect(afterWindAxisOn.get("windAxis")).toBe(true);
    expect(afterWindAxisOn.get("roadType")).toBe(true); // 道路ドメインは引き続き無関係
  });

  it("環境ドメインは道路/評価軸と独立: 環境内では排他だが、道路/評価軸には影響しない", async () => {
    vi.mocked(getAxisCatalog).mockReturnValue(new Promise(() => {}));
    render(<Home />);

    fireEvent.click(await screen.findByRole("button", { name: "toggle:roadType" }));
    fireEvent.click(screen.getByRole("button", { name: "toggle:elevation" }));
    const afterElevationOn = overlayLayersOnMap();
    expect(afterElevationOn.get("roadType")).toBe(true); // 別ドメインのため影響なし
    expect(afterElevationOn.get("elevation")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "toggle:precipitationNowcast" }));
    const afterPrecipOn = overlayLayersOnMap();
    expect(afterPrecipOn.get("elevation")).toBe(false); // 環境ドメイン内は排他
    expect(afterPrecipOn.get("precipitationNowcast")).toBe(true);
    expect(afterPrecipOn.get("roadType")).toBe(true); // 道路ドメインは引き続き無関係
  });

  it("スポットドメインは他ドメインと独立: スポット内では排他だが、道路/環境には影響しない", async () => {
    vi.mocked(getAxisCatalog).mockReturnValue(new Promise(() => {}));
    render(<Home />);

    fireEvent.click(await screen.findByRole("button", { name: "toggle:roadType" }));
    fireEvent.click(screen.getByRole("button", { name: "toggle:stopPoi" }));
    const afterStopPoiOn = overlayLayersOnMap();
    expect(afterStopPoiOn.get("stopPoi")).toBe(true);
    expect(afterStopPoiOn.get("roadType")).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "toggle:accidents" }));
    const afterAccidentsOn = overlayLayersOnMap();
    expect(afterAccidentsOn.get("stopPoi")).toBe(false); // スポットドメイン内は排他
    expect(afterAccidentsOn.get("accidents")).toBe(true);
    expect(afterAccidentsOn.get("roadType")).toBe(true); // 道路ドメインは引き続き無関係
  });

  it("ルートはどの排他ドメインにも属さない: 道路/評価軸のON操作と無関係にON/OFFできる", async () => {
    vi.mocked(getAxisCatalog).mockReturnValue(new Promise(() => {}));
    render(<Home />);

    // routeは既定でON（DEFAULT_LAYER_VISIBILITY参照）
    expect(overlayLayersOnMap().get("route")).toBe(true);

    fireEvent.click(await screen.findByRole("button", { name: "toggle:roadType" }));
    fireEvent.click(screen.getByRole("button", { name: "toggle:axis:car_stress" }));
    const afterBothToggled = overlayLayersOnMap();
    // route自体はどちらの操作の影響も受けずONのまま
    expect(afterBothToggled.get("route")).toBe(true);
  });
});

// 改善計画T468回帰テスト（2026-08-31 T478で追加）: overlayLayers組み立ての
// isDynamicGroupLayer判定が、以前はlayer.idのハードコード列挙で「動的グループ」を
// 再判定しており、mapLayers.ts側の単一ソースdataNature==="dynamic"とズレていた
// （gradientFillが列挙漏れで「[設定はサイドバー]」が誤って付与される実害があった）。
// dataNature自体を見る形へ修正済みであることを、titleの実際の値で確認する。
describe("Home（app/page.tsx） 地図上チップのtitle（改善計画T468: dataNature単一ソース化）", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
    vi.mocked(getAxisCatalog).mockReset();
  });

  function overlayLayerTitles(): Map<string, string | undefined> {
    const text = screen.getByTestId("overlay-layer-titles").textContent ?? "[]";
    const layers = JSON.parse(text) as Array<[string, string | undefined]>;
    return new Map(layers);
  }

  it("dataNature=dynamicのgradientFillは「[設定はサイドバー]」を付けずlayer.descriptionそのままをtitleにする", async () => {
    vi.mocked(getAxisCatalog).mockReturnValue(new Promise(() => {}));
    render(<Home />);

    await screen.findByTestId("overlay-layer-titles");
    const title = overlayLayerTitles().get("gradientFill");
    expect(title).toBe(
      "指定した走行方位で進んだ場合の実効勾配を、周辺道路網の平均としてタイル単位の面塗りで表示"
    );
    expect(title).not.toMatch(/\[設定はサイドバー\]/);
  });

  it("dataNature=static（既定）のroadTypeは「[設定はサイドバー]」付きのtitleになる", async () => {
    vi.mocked(getAxisCatalog).mockReturnValue(new Promise(() => {}));
    render(<Home />);

    await screen.findByTestId("overlay-layer-titles");
    const title = overlayLayerTitles().get("roadType");
    expect(title).toMatch(/\[設定はサイドバー\]$/);
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
import { getAmedasObservation, getCurrentWeather, getWeatherWarnings, getWbgtStatus, getFloodForecasts } from "@/services/weatherApi";
import type { RouteCandidate, GenerationConditions } from "@/types/route";
import type { AmedasObservation, WeatherConditions, WeatherWarnings, WbgtStatus, FloodForecasts } from "@/types/weather";

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
    segments: null,
    overall_difficulty: null,
    axis_difficulties: {},
    axis_contributions: {},
    ...overrides,
  };
}

function makeConditions(overrides: Partial<GenerationConditions> = {}): GenerationConditions {
  return {
    latitude: 35.7597,
    longitude: 139.7387,
    distance_km: 30,
    distance_tolerance_km: 5,
    route_preference: {},
    penalty_strength: 1.0,
    max_average_grade_percent: null,
    hard_filters: { no_bicycle: true, motorway: true, trunk: true },
    max_routes: 8,
    assumed_speed_kmh: 20,
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
  /** trueならMapViewをonDestinationSet/onWaypointAddを呼べるボタン付きスタブへ差し替える
   * （改善計画T557: 目的地モードの生成テストは実際に地図をタップできないため、この
   * スタブ経由で座標を確定する）。既定は上と同じnullモック。 */
  exposeMapClickHandlers?: boolean;
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

  if (options.exposeMapClickHandlers) {
    vi.doMock("@/components/Map/MapView", () => ({
      default: (props: {
        onDestinationSet: (c: { latitude: number; longitude: number }) => void;
        onWaypointAdd: (c: { latitude: number; longitude: number }) => void;
      }) => (
        <>
          <button onClick={() => props.onDestinationSet({ latitude: 35.681, longitude: 139.767 })}>
            テスト用に目的地を設定
          </button>
          <button onClick={() => props.onWaypointAdd({ latitude: 35.682, longitude: 139.768 })}>
            テスト用に経由地を追加
          </button>
        </>
      ),
    }));
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
      ? (props: { amedas: { temperature_c: number } | null }) => (
          <div data-testid="weather-panel">{JSON.stringify({ temp: props.amedas?.temperature_c ?? null })}</div>
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
    // このdescribeブロックのHomeマウントもfetchWeatherFor等（5並列fetch、改善計画T387
    // フォローアップでamedasが独立フェッチに加わった）を必ず1回ずつ発火させる
    // （renderFreshHomeがexposeWeatherPanel等を指定していないため未使用のレスポンスとして
    // 握りつぶされるだけだが、getCurrentWeather等は下の「並列fetchの競合対策」
    // describeブロックとvi.fn()インスタンスを共有している。呼び出し回数をクリアしておかないと、
    // そちらのtoHaveBeenCalledTimes(1)がこのブロックぶんの呼び出しを含んでしまい失敗する）。
    vi.mocked(getCurrentWeather).mockClear();
    vi.mocked(getAmedasObservation).mockClear();
    vi.mocked(getWeatherWarnings).mockClear();
    vi.mocked(getWbgtStatus).mockClear();
    vi.mocked(getFloodForecasts).mockClear();
    latestLocationSetter = null;
  });

  it("改善計画T531: 生成リクエストに候補件数(max_routes)の既定値を含める", async () => {
    const user = userEvent.setup();
    vi.mocked(generateRoutes).mockResolvedValueOnce({
      routes: [makeCandidate()],
      conditions: makeConditions(),
      engine: "road_graph",
    });
    const HomeFresh = await renderFreshHome({ realRouteForm: true });
    render(<HomeFresh />);

    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    await waitFor(() => {
      expect(generateRoutes).toHaveBeenCalledWith(
        expect.objectContaining({ max_routes: 8 }),
        expect.anything(),
      );
    });
  });

  it("生成リクエストに巡航速度(assumed_speed_kmh)の既定値を含め、入力変更が反映される", async () => {
    const user = userEvent.setup();
    vi.mocked(generateRoutes).mockResolvedValue({
      routes: [makeCandidate()],
      conditions: makeConditions(),
      engine: "road_graph",
    });
    const HomeFresh = await renderFreshHome({ realRouteForm: true });
    render(<HomeFresh />);

    await user.click(screen.getByRole("button", { name: "ルート生成" }));
    await waitFor(() => {
      expect(generateRoutes).toHaveBeenCalledWith(
        expect.objectContaining({ assumed_speed_kmh: 20 }),
        expect.anything(),
      );
    });

    // RouteForm（周回モード）の数値入力は距離・候補件数・巡航速度の順。
    const speedInput = screen.getAllByRole("spinbutton")[2];
    await user.clear(speedInput);
    await user.type(speedInput, "25");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));
    await waitFor(() => {
      expect(generateRoutes).toHaveBeenLastCalledWith(
        expect.objectContaining({ assumed_speed_kmh: 25 }),
        expect.anything(),
      );
    });
  });

  it("改善計画T531: 候補件数入力を変更すると生成リクエストのmax_routesへ反映される", async () => {
    const user = userEvent.setup();
    vi.mocked(generateRoutes).mockResolvedValueOnce({
      routes: [makeCandidate()],
      conditions: makeConditions(),
      engine: "road_graph",
    });
    const HomeFresh = await renderFreshHome({ realRouteForm: true });
    render(<HomeFresh />);

    // RouteForm（周回モード）は距離・候補件数の2つの数値入力を持つ（距離が先）。
    const maxRoutesInput = screen.getAllByRole("spinbutton")[1];
    await user.clear(maxRoutesInput);
    await user.type(maxRoutesInput, "3");
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    await waitFor(() => {
      expect(generateRoutes).toHaveBeenCalledWith(
        expect.objectContaining({ max_routes: 3 }),
        expect.anything(),
      );
    });
  });

  it("目的地モード（経由地なし）で候補件数欄が空のまま生成しようとすると送信されずエラーが表示される", async () => {
    const user = userEvent.setup();
    const HomeFresh = await renderFreshHome({ realRouteForm: true, exposeMapClickHandlers: true });
    render(<HomeFresh />);

    // 周回モードのまま候補件数欄を空にする。経由地の無い目的地モードでも同じ入力欄が
    // 引き続き表示・検証されるため（RouteForm.tsx: maxRoutesRelevant）、モード切替後も
    // 空のままなら送信はRouteForm側でブロックされる。
    const maxRoutesInput = screen.getAllByRole("spinbutton")[1];
    await user.clear(maxRoutesInput);

    await user.click(screen.getByRole("button", { name: "目的地" }));
    await user.click(screen.getByRole("button", { name: "テスト用に目的地を設定" }));
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    expect(generateRoutes).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent("候補件数は整数で入力してください。");
  });

  it("改善計画T557（P1）: 経由地を伴う目的地モードで候補件数欄が空のまま生成しても422にならない値を送る", async () => {
    const user = userEvent.setup();
    vi.mocked(generateRoutes).mockResolvedValueOnce({
      routes: [makeCandidate()],
      conditions: makeConditions(),
      engine: "road_graph",
    });
    const HomeFresh = await renderFreshHome({ realRouteForm: true, exposeMapClickHandlers: true });
    render(<HomeFresh />);

    // 周回モードのまま候補件数欄を空にする。
    const maxRoutesInput = screen.getAllByRole("spinbutton")[1];
    await user.clear(maxRoutesInput);

    // 経由地を伴う目的地モードへ切替（候補件数入力欄はここで非表示になり検証されなくなるが、
    // 空文字のままのstateはpage.tsx側に残り続ける）。
    await user.click(screen.getByRole("button", { name: "目的地" }));
    await user.click(screen.getByRole("button", { name: "テスト用に経由地を追加" }));
    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    await waitFor(() => {
      expect(generateRoutes).toHaveBeenCalled();
    });
    const sentRequest = vi.mocked(generateRoutes).mock.calls[0][0];
    // backend RouteGenerateRequest.max_routesはField(ge=1, le=15)——0や NaN は422になる。
    expect(Number.isInteger(sentRequest.max_routes)).toBe(true);
    expect(sentRequest.max_routes).toBeGreaterThanOrEqual(1);
  });

  it("改善計画T531: 候補タブに順位番号を表示し、同じ方位の候補を区別できる", async () => {
    const user = userEvent.setup();
    vi.mocked(generateRoutes).mockResolvedValueOnce({
      routes: [
        makeCandidate({ id: "route-00", direction_label: "北", distance_km: 30.1 }),
        makeCandidate({ id: "route-01", direction_label: "北", distance_km: 31.4 }),
      ],
      conditions: makeConditions(),
      engine: "road_graph",
    });
    const HomeFresh = await renderFreshHome({ realRouteForm: true });
    render(<HomeFresh />);

    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "1. 北方向 30.1 km" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "2. 北方向 31.4 km" })).toBeInTheDocument();
    });
  });

  it("改善計画T551: 目的地ルート候補タブは順位番号を付けるが「方向」は付けない", async () => {
    const user = userEvent.setup();
    vi.mocked(generateRoutes).mockResolvedValueOnce({
      routes: [
        makeCandidate({ id: "route-destination-00", direction_label: "目的地ルート", distance_km: 20.3 }),
        makeCandidate({ id: "route-destination-01", direction_label: "目的地ルート", distance_km: 22.1 }),
      ],
      conditions: makeConditions(),
      engine: "road_graph",
    });
    const HomeFresh = await renderFreshHome({ realRouteForm: true });
    render(<HomeFresh />);

    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "1. 目的地ルート 20.3 km" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "2. 目的地ルート 22.1 km" })).toBeInTheDocument();
    });
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

  it("改善計画T441: バックエンドがno_candidates_reasonを返した場合、汎用文言ではなくそちらを表示する", async () => {
    const user = userEvent.setup();
    vi.mocked(generateRoutes).mockResolvedValueOnce({
      routes: [],
      conditions: makeConditions(),
      engine: "road_graph",
      noCandidatesReason: "5件の折返し候補で復路の探索に失敗しました。除外設定をご確認ください。",
    });
    const HomeFresh = await renderFreshHome({ realRouteForm: true });
    render(<HomeFresh />);

    await user.click(screen.getByRole("button", { name: "ルート生成" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "5件の折返し候補で復路の探索に失敗しました。除外設定をご確認ください。",
      );
    });
  });

  it("改善計画T365: 「ルートをクリア」ボタンで生成済みの候補一覧をリセットできる", async () => {
    // ここではpage.tsx側の状態（routes.length > 0で出す「ルートをクリア」ボタン自体の
    // 表示/非表示）でhandleRoutesClearの配線を検証する（候補タブ・内訳の中身自体は
    // RouteAxisProfile.test.tsxが別途検証済み）。
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

  it("改善計画T535: 「ルートをクリア」は実験スロットも空にする（地図に残る色付き線の原因だった）", async () => {
    // ユーザー報告「ルートをクリアしても地図に緑の線が残る」の再発防止。研究モード中の
    // 生成はexperimentSlotsへ記録され地図へ重ね描きされるが、以前はhandleRoutesClearが
    // experimentSlotsに触れていなかった（リポジトリ全体でも空にする経路が他に無かった）。
    //
    // routes=[]になるとrenderRouteOutcomeSectionBody自体がnullを返し比較タブ
    // （comparison-slots testid）ごと一時的にアンマウントされるため、クリア直後に
    // 直接「[]」を検証することはできない。代わりに、クリア後にもう一度生成して
    // 新しいスロットだけが積まれる（クリア前のroute-aが残っていれば2件になるはず）
    // ことで、experimentSlots状態が実際に空へ戻ったことを間接的に確認する。
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

    await user.click(screen.getByRole("button", { name: "ルートをクリア" }));
    // 比較タブごと一時的に消える（routes=[]でrenderRouteOutcomeSectionBodyがnullを返す）。
    expect(screen.queryByTestId("comparison-slots")).not.toBeInTheDocument();

    await user.click(generateButton);
    await waitFor(() => {
      // route-aが残っていれば'["route-b","route-a"]'になるはずだが、クリアで
      // experimentSlotsが空になっているためroute-bだけになる。
      expect(screen.getByTestId("comparison-slots")).toHaveTextContent('["route-b"]');
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
      weather_code: null,
      is_day: null,
      sunrise: null,
      sunset: null,
      precipitation_probability_max_percent: null,
      wind_speed_max_ms: null,
      temperature_max_c: null,
      temperature_min_c: null,
      uv_index_max: null,
      today_periods: [],
    };
  }
  function makeAmedas(temperature_c: number): AmedasObservation {
    return {
      station_id: "44132",
      station_name: "東京",
      latitude: 35.69,
      longitude: 139.76,
      observed_at: "2026-08-25T12:00:00+09:00",
      temperature_c,
      apparent_temperature_c: null,
      wind_speed_ms: 3,
      wind_direction_deg: 90,
      wind_direction_label: "東",
      precipitation_10min_mm: null,
      sunshine_10min_minutes: null,
      sunrise: null,
      sunset: null,
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
    vi.mocked(getAmedasObservation).mockReset();
    vi.mocked(getWeatherWarnings).mockReset();
    vi.mocked(getWbgtStatus).mockReset();
    vi.mocked(getFloodForecasts).mockReset();
    vi.mocked(getAxisCatalog).mockReset();
    latestLocationSetter = null;
  });

  it("地点を連続変更したとき、アメダス・警報・WBGT・氾濫予報の4つとも古い応答が新しい応答を上書きしない", async () => {
    vi.mocked(getAxisCatalog).mockRejectedValue(new Error("mock: unused in this test"));
    // WeatherPanel（本テストの対象）はgetAmedasObservationのみを参照する
    // （getCurrentWeatherはTodayOutlook向けで本テストでは未検証のため単純に解決するだけ）。
    vi.mocked(getCurrentWeather).mockResolvedValue(makeWeather(0));

    // それぞれ「1回目(古い方)」「2回目(新しい方)」のリクエストに対応するdeferredを用意し、
    // あとで意図的に2回目→1回目の順で解決する(応答順序の入れ替え、テスト方針#5)。
    const amedasOld = createDeferred<AmedasObservation>();
    const amedasNew = createDeferred<AmedasObservation>();
    vi.mocked(getAmedasObservation)
      .mockImplementationOnce(() => amedasOld.promise)
      .mockImplementationOnce(() => amedasNew.promise);

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
      expect(getAmedasObservation).toHaveBeenCalledTimes(1);
      expect(getWeatherWarnings).toHaveBeenCalledTimes(1);
      expect(getWbgtStatus).toHaveBeenCalledTimes(1);
      expect(getFloodForecasts).toHaveBeenCalledTimes(1);
    });

    // 地点を変更し、2件目(新しい方)のリクエストを発火させる。
    await act(async () => {
      latestLocationSetter?.({ latitude: 36.0, longitude: 140.0 });
    });
    await waitFor(() => {
      expect(getAmedasObservation).toHaveBeenCalledTimes(2);
      expect(getWeatherWarnings).toHaveBeenCalledTimes(2);
      expect(getWbgtStatus).toHaveBeenCalledTimes(2);
      expect(getFloodForecasts).toHaveBeenCalledTimes(2);
    });

    // 後から投げた(新しい)リクエストを先に解決する。
    await act(async () => {
      amedasNew.resolve(makeAmedas(20));
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
      amedasOld.resolve(makeAmedas(10));
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

  it("アメダスfetch単体でも、2回目に投げたリクエストが先に解決すれば古い1回目の応答は無視される", async () => {
    vi.mocked(getAxisCatalog).mockRejectedValue(new Error("mock: unused in this test"));
    vi.mocked(getCurrentWeather).mockResolvedValue(makeWeather(0));
    vi.mocked(getWeatherWarnings).mockResolvedValue({ area_name: null, report_datetime: null, warnings: [] });
    vi.mocked(getWbgtStatus).mockResolvedValue({ level: null, label: null, value: null, observed_at: null });
    vi.mocked(getFloodForecasts).mockResolvedValue({ forecasts: [] });

    const first = createDeferred<AmedasObservation>();
    const second = createDeferred<AmedasObservation>();
    vi.mocked(getAmedasObservation)
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);

    const HomeFresh = await renderFreshHome({ statefulLocation: true, exposeWeatherPanel: true });
    render(<HomeFresh />);

    await waitFor(() => expect(getAmedasObservation).toHaveBeenCalledTimes(1));
    await act(async () => {
      latestLocationSetter?.({ latitude: 36.0, longitude: 140.0 });
    });
    await waitFor(() => expect(getAmedasObservation).toHaveBeenCalledTimes(2));

    // 2回目(新しい方)を先に解決する(テスト方針#5: 応答順序の意図的な入れ替え)。
    await act(async () => {
      second.resolve(makeAmedas(25));
    });
    await waitFor(() => expect(screen.getByTestId("weather-panel")).toHaveTextContent('"temp":25'));

    // 1回目(古い方)が後から解決しても上書きされない。
    await act(async () => {
      first.resolve(makeAmedas(5));
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByTestId("weather-panel")).toHaveTextContent('"temp":25');
    expect(screen.getByTestId("weather-panel")).not.toHaveTextContent('"temp":5');
  });
});
