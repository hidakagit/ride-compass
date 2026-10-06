/**
 * `RoadInspectorPopup.tsx`——押した道の評価を取りに行き、軸ごとの効き方を出すこと。
 *
 * ここで見ないもの:
 * - 評価を利用者のいまの重みで取りに行くこと → 受けた重みをそのまま取得の口へ渡す1行の委譲（testing.md「そのテストは
 *   要るか」の1問目）。重みを要求の項目へ載せることは`features/map/regionApi.test.ts`が見る
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { setDebugEnabled } from "@/lib/debugLog";
import { catalogAxisFromEntry, type CatalogAxis } from "@/lib/catalogAxis";
import { onBackend } from "@/testing/backendServer";
import { catalogEntry } from "@/testing/catalogAxes";
import materialCatalog from "@/types/generated/material-catalog.json";
import type { AxisInspectorResult } from "@/types/traffic";
import RoadInspectorPopup from "./RoadInspectorPopup";

const INSPECTOR = "/api/region/axis-inspector";
const serveInspector = (result: AxisInspectorResult) => onBackend("POST", INSPECTOR, () => Response.json(result));

const axis = (axisId: string, label: string, description: string): CatalogAxis =>
  catalogAxisFromEntry(catalogEntry({ axis_id: axisId, label, description }));
const AXES = [axis("axis_sample", "見本の軸", "車の通行量の説明"), axis("night", "夜間", "夜間の暗さの説明")];
const AXIS_COLORS: Record<string, string> = { axis_sample: "#111111", night: "#222222" };
/** 地図がいつも渡す走行の条件（押した点のタイル込み）と重み（nullは既定の重み）。 */
const RIDE = {
  conditions: { bearingDeg: 0, at: new Date("2026-09-24T00:00:00Z"), speedKmh: 20, z: 14, x: 1, y: 2 },
  routePreference: null,
};
/** 路面の区分の項目名と、呼び名を持つ値の1つ（書き写さず材料カタログから引く）。 */
const SURFACE_CLASS = materialCatalog.find((material) => material.material_id === "surface_class")!;
const [SURFACE_CLASS_VALUE] = Object.entries(SURFACE_CLASS.value_labels ?? {}).find(
  (entry): entry is [string, string] => typeof entry[1] === "string",
)!;

function inspectorResult(): AxisInspectorResult {
  return {
    highway: "residential",
    tags: { lit: "yes", name: "明治通り" },
    axes: [
      { axis_id: "axis_sample", difficulty: 60, contribution: 30 },
      { axis_id: "night", difficulty: 20, contribution: 10 },
      { axis_id: "gradient", difficulty: null, contribution: null },
    ],
    composite_difficulty: { value: 40, covered_weight_fraction: 0.8 },
    landcover: {
      water_percent: 0,
      trees_percent: 20,
      flooded_veg_percent: 0,
      crops_percent: 30,
      built_percent: 50,
      bare_percent: 0,
      snow_ice_percent: 0,
      rangeland_percent: 0,
    },
  };
}

describe("RoadInspectorPopup", () => {
  it("周囲の土地被覆は畳んでおき、閉じている間は最も多いクラスだけを見せる", async () => {
    const user = userEvent.setup();
    serveInspector(inspectorResult());
    render(
      <RoadInspectorPopup
        properties={{ osm_way_id: 1, surface_class: SURFACE_CLASS_VALUE }}
        axes={AXES}
        axisColors={AXIS_COLORS}
        {...RIDE}
      />,
    );

    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));

    // 閉じている間は要約だけを見せる。走行中のスマホが主用途のため、既定で行を並べない
    // （`details`は閉じていても子をDOMへ残すため、存在ではなく見えるかで確かめる）。
    const summary = await screen.findByText("周囲の土地被覆: 建物 50%");
    expect(screen.getByText("農地")).not.toBeVisible();

    await user.click(summary);

    // 開くと割合の大きい順。0%のクラス（水面・湿地・裸地・雪氷・草地）は行自体を作らない。
    expect(screen.getByText("農地")).toBeVisible();
    expect(screen.getByText("樹木")).toBeVisible();
    expect(screen.queryByText("水面")).not.toBeInTheDocument();
  });

  it("事実だけを先に出し、評価は押したときに取りに行く（クリックのたびに引かない）", () => {
    render(
      <RoadInspectorPopup
        properties={{ osm_way_id: 1, name: "明治通り", surface_class: SURFACE_CLASS_VALUE }}
        axes={AXES}
        axisColors={AXIS_COLORS}
        {...RIDE}
      />,
    );

    expect(screen.getByText("明治通り")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "この道の評価を見る" })).toBeInTheDocument();
  });

  it("評価はルート結果と同じ寄与度で出し、算出できない軸は並べない", async () => {
    const user = userEvent.setup();
    serveInspector(inspectorResult());
    render(
      <RoadInspectorPopup
        properties={{ osm_way_id: 1, surface_class: SURFACE_CLASS_VALUE }}
        axes={AXES}
        axisColors={AXIS_COLORS}
        {...RIDE}
      />,
    );

    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));

    // 寄与度バーの凡例は軸アイコン＋値（ルート結果と同じ部品）。
    expect(await screen.findByText("30.0")).toBeInTheDocument();
    expect(screen.getByText("10.0")).toBeInTheDocument();
    // この道に値の出ない軸（勾配）はそもそも並ばない。
    expect(screen.queryByLabelText("勾配の詳細を表示")).not.toBeInTheDocument();
  });

  it("合成は注記として出す（実際の探索コストとは一致しないため主役にしない）", async () => {
    const user = userEvent.setup();
    serveInspector(inspectorResult());
    render(
      <RoadInspectorPopup
        properties={{ osm_way_id: 1, surface_class: SURFACE_CLASS_VALUE }}
        axes={AXES}
        axisColors={AXIS_COLORS}
        {...RIDE}
      />,
    );

    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));

    expect(await screen.findByText(/この道だけで見た合成: 40\.0\/100/)).toBeInTheDocument();
    expect(screen.getByText(/重みの約80%/)).toBeInTheDocument();
  });

  it("出す割合が100%に丸まるなら、一部の軸だけだという注記を添えない", async () => {
    const user = userEvent.setup();
    serveInspector({ ...inspectorResult(), composite_difficulty: { value: 40, covered_weight_fraction: 0.996 } });
    render(
      <RoadInspectorPopup
        properties={{ osm_way_id: 1, surface_class: SURFACE_CLASS_VALUE }}
        axes={AXES}
        axisColors={AXIS_COLORS}
        {...RIDE}
      />,
    );

    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));

    expect(await screen.findByText(/この道だけで見た合成: 40\.0\/100/)).toBeInTheDocument();
    expect(screen.queryByText(/重みの約/)).not.toBeInTheDocument();
  });

  it("カタログ外の生タグは畳んで置く（数が読めないため、開いたときだけ縦に伸ばす）", async () => {
    const user = userEvent.setup();
    serveInspector(inspectorResult());
    render(
      <RoadInspectorPopup
        properties={{ osm_way_id: 1, surface_class: SURFACE_CLASS_VALUE }}
        axes={AXES}
        axisColors={AXIS_COLORS}
        {...RIDE}
      />,
    );

    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));

    await waitFor(() => expect(screen.getByText("その他のタグ")).toBeInTheDocument());
    // 生タグは属性の中でさらに畳む。登録済みの属性（lit）は属性の畳みの中に直接並ぶ。
    const others = screen.getByText("その他のタグ").closest("details");
    expect(others?.textContent).toContain("明治通り");
    expect(others?.textContent).not.toContain("yes");
  });

  it("属性は畳んでおき、タイルとタグの両方が持つ項目は1度だけ出す", async () => {
    const user = userEvent.setup();
    serveInspector({ ...inspectorResult(), tags: { highway: "residential", lit: "yes" } });
    render(
      <RoadInspectorPopup
        properties={{ osm_way_id: 1, surface_class: SURFACE_CLASS_VALUE }}
        axes={AXES}
        axisColors={AXIS_COLORS}
        {...RIDE}
      />,
    );

    const attributes = screen.getByText("この道の属性").closest("details");
    expect(screen.getByText(SURFACE_CLASS.name)).not.toBeVisible();
    // 畳みを開くと、評価を取る前からタイルの事実が読める。
    await user.click(screen.getByText("この道の属性"));
    expect(screen.getByText(SURFACE_CLASS.name)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));

    await waitFor(() => expect(screen.getByText("residential")).toBeInTheDocument());
    const labels = Array.from(attributes?.querySelectorAll("dt") ?? []).map((dt) => dt.textContent);
    expect(labels.length).toBeGreaterThan(1);
    expect(new Set(labels).size).toBe(labels.length);
  });
});

describe("評価の重み", () => {
  const WEIGHTS = { axis_sample: 0, night: 1 };

  it("重みを変えたら、前の重みで取った評価を見せずに取り直しへ戻る", async () => {
    const user = userEvent.setup();
    serveInspector(inspectorResult());
    const props = { properties: { osm_way_id: 1 }, axes: AXES, axisColors: AXIS_COLORS, ...RIDE };
    const { rerender } = render(<RoadInspectorPopup {...props} routePreference={WEIGHTS} />);
    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));
    await waitFor(() => expect(screen.getByText(/この道だけで見た合成/)).toBeInTheDocument());

    rerender(<RoadInspectorPopup {...props} routePreference={{ axis_sample: 1, night: 1 }} />);

    expect(screen.queryByText(/この道だけで見た合成/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "この道の評価を見る" })).toBeInTheDocument();
  });
});

describe("評価の走行の条件", () => {
  const CONDITIONS = { bearingDeg: 0, at: new Date("2026-09-24T00:00:00Z"), speedKmh: 20, z: 14, x: 1, y: 2 };
  const props = { properties: { osm_way_id: 1 }, axes: AXES, axisColors: AXIS_COLORS, ...RIDE };

  it("開いている間に出発時刻が進んでも、押したときの条件で取った評価を出し続ける", async () => {
    const user = userEvent.setup();
    serveInspector(inspectorResult());
    const { rerender } = render(<RoadInspectorPopup {...props} conditions={CONDITIONS} />);
    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));
    await screen.findByText(/この道だけで見た合成/);

    rerender(<RoadInspectorPopup {...props} conditions={{ ...CONDITIONS, at: new Date("2026-09-24T00:05:00Z") }} />);

    expect(screen.getByText(/この道だけで見た合成/)).toBeInTheDocument();
  });

  it("同じ道を同じ条件・重みで開き直したときは、取り直さずに前の評価を出す", async () => {
    const user = userEvent.setup();
    serveInspector(inspectorResult());
    const first = render(<RoadInspectorPopup {...props} conditions={CONDITIONS} />);
    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));
    await screen.findByText(/この道だけで見た合成/);
    first.unmount();

    render(<RoadInspectorPopup {...props} conditions={{ ...CONDITIONS }} />);

    expect(screen.getByText(/この道だけで見た合成/)).toBeInTheDocument();
  });
});

describe("OSMの生値", () => {
  it("OSMの生値はタグとして解釈されない（第三者が編集できるデータのため）", () => {
    const attack = '<img src=x onerror="alert(1)">';
    const { container } = render(
      <RoadInspectorPopup
        properties={{ osm_way_id: 1, name: attack }}
        axes={AXES}
        axisColors={AXIS_COLORS}
        {...RIDE}
      />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain(attack);
  });
});

describe("道の識別子", () => {
  // 一般の利用者には読めない値なので既定では出さず、デバッグログONなら地図で押した1本をそのままbackendの調査へ渡せるように出す。
  it.each([
    [false, []],
    [true, ["OSM way id: 4242"]],
  ])("デバッグログが%sなら、出すのは%j", (debug, shown) => {
    setDebugEnabled(debug);
    render(<RoadInspectorPopup properties={{ osm_way_id: 4242 }} axes={AXES} axisColors={AXIS_COLORS} {...RIDE} />);

    expect(screen.queryAllByText(/OSM way id/).map((element) => element.textContent)).toEqual(shown);
    setDebugEnabled(false);
  });
});
