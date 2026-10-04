/**
 * `RouteSettingsPanel/RouteSettingsPanel.tsx`——「重み」タブ。配分の帯（区間・区切りのドラッグと矢印キー）と軸のチップ。
 *
 * 見るもの: 軸一覧を取れないときの告知と再試行、公開軸ごとのチップ（有効な軸を先に・割合・押して有効/無効・(i)の説明）、
 * 有効に戻したときの重み（帯で動かした値・既定・既定が0なら決まった小さな値、既定が後から変わったときの追い方）、帯の区間の
 * 幅と、区間に書く文字の落とし方（境界ちょうどの割合を含む）、チップの印と帯の区間の色、区切り（隣り合う有効な軸ごと・
 * 累積の割合）を矢印キーとドラッグで動かして上がる2軸の重み、重みを変えると上書きの状態にすること。
 *
 * ここで見ないもの: 区切りを動かした量を範囲へ寄せて刻みへ丸めること → `features/route/routeWeightShare.test.ts`。
 * 受け取る重みを公開軸へ揃えること → `features/route/routePreferenceSync.test.ts`（このパネルは揃った値を受け取る）。
 * 無効な軸のチップを薄くすること（クラスで付ける見た目）。
 *
 * 差し替えた部品: 軸カタログの通信（`services/axisCatalogApi.getAxisCatalog`）は返す値をテストが決め、軸は架空のもの
 * （`testing/catalogAxes.ts`）。帯の実寸はテスト環境に無いので、ドラッグのテストだけ帯の`getBoundingClientRect`を決める。
 * 重みと上書きの状態は親が持つので、テストの包みが上がった値を持ち直して渡す。
 */
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WEIGHT_STEP } from "@/features/route/routeWeightShare";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { getAxisCatalog } from "@/services/axisCatalogApi";
import { catalogEntry, catalogOf, catalogResponse } from "@/testing/catalogAxes";
import type { RoutePreferenceWeights } from "@/types/route";

import RouteSettingsPanel from "./RouteSettingsPanel";

vi.mock("@/services/axisCatalogApi", () => ({ getAxisCatalog: vi.fn() }));

afterEach(() => {
  vi.restoreAllMocks();
});

const WIDTH = catalogEntry({
  axis_id: "width",
  label: "道幅",
  chip_label: "幅",
  description: "道の広さを見ます。",
  default_weight: 0.5,
});
const TRAFFIC = catalogEntry({ axis_id: "traffic", label: "交通", default_weight: 0.3 });
const SLOPE = catalogEntry({ axis_id: "slope", label: "勾配", default_weight: 0.2 });
const LIGHT = catalogEntry({ axis_id: "light", label: "街灯", default_weight: 0 });
const AXES = [WIDTH, TRAFFIC, SLOPE, LIGHT];
/** 本番と同じ導き方で軸カタログが決める、軸ごとの識別色。 */
const COLORS = catalogOf(AXES).axisColors;

function serveCatalog(entries = AXES) {
  vi.mocked(getAxisCatalog).mockResolvedValue(catalogResponse(entries));
}

/** 親の代わりに、上がった重みと上書きの状態を持ち直して渡す包み。 */
function renderPanel(initial: RoutePreferenceWeights, overrideEnabled = true) {
  const onRoutePreferenceChange = vi.fn<(next: RoutePreferenceWeights) => void>();
  const onOverrideEnabledChange = vi.fn<(enabled: boolean) => void>();
  function Parent() {
    const [weights, setWeights] = useState(initial);
    const [override, setOverride] = useState(overrideEnabled);
    return (
      <RouteSettingsPanel
        routePreference={weights}
        onRoutePreferenceChange={(next) => {
          onRoutePreferenceChange(next);
          setWeights(next);
        }}
        overrideEnabled={override}
        onOverrideEnabledChange={(enabled) => {
          onOverrideEnabledChange(enabled);
          setOverride(enabled);
        }}
      />
    );
  }
  render(<Parent />);
  return { onRoutePreferenceChange, onOverrideEnabledChange };
}

/** 軸一覧が届いてチップが出るまで待つ。 */
async function chipsShown() {
  await screen.findByRole("button", { name: /^道幅を(有|無)効にする$/ });
}

function chip(name: string) {
  return screen.getByRole("button", { name });
}

function boundary(name: string) {
  return screen.getByRole("slider", { name });
}

describe("RouteSettingsPanel 軸一覧を取れないとき", () => {
  it("重みが反映されないことと再試行を出し、再試行で取り直して届いたら告知を消す", async () => {
    vi.mocked(getAxisCatalog).mockRejectedValueOnce(new Error("網の失敗"));
    serveCatalog();
    renderPanel({});

    expect(await screen.findByRole("status")).toHaveTextContent(
      "軸一覧を取得できませんでした。地図の道路・POI・事故は表示できず、このまま生成すると重み配分は反映されずサーバー既定の配分で探索します。",
    );

    await userEvent.click(screen.getByRole("button", { name: "再試行" }));

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(getAxisCatalog).toHaveBeenCalledTimes(2);
  });
});

describe("RouteSettingsPanel 軸のチップ", () => {
  it("公開軸ごとに略名のチップを、有効な軸を先に、それぞれカタログの並びのまま出す", async () => {
    serveCatalog();
    renderPanel({ width: 0, traffic: 0.3, slope: 0, light: 0.2 });
    await chipsShown();

    const chips = screen.getAllByRole("button", { name: /を(有|無)効にする$/ });
    expect(chips.map((button) => button.getAttribute("aria-label"))).toEqual([
      "交通を無効にする",
      "街灯を無効にする",
      "道幅を有効にする",
      "勾配を有効にする",
    ]);
    expect(chips.map((button) => button.getAttribute("aria-pressed"))).toEqual(["true", "true", "false", "false"]);
    expect(chip("道幅を有効にする")).toHaveTextContent(/^幅$/);
  });

  it("有効な軸のチップに重みの合計に占める割合を出し、無効な軸には出さない", async () => {
    serveCatalog();
    renderPanel({ width: 0.5, traffic: 0, slope: 0.2, light: 0 });
    await chipsShown();

    expect(chip("道幅を無効にする")).toHaveTextContent("71%");
    expect(chip("勾配を無効にする")).toHaveTextContent("29%");
    expect(chip("交通を有効にする")).not.toHaveTextContent("%");
  });

  it("(i)の奥に軸の説明を置く", async () => {
    serveCatalog();
    renderPanel({ width: 0.5, traffic: 0.3, slope: 0.2, light: 0 });
    await chipsShown();

    await userEvent.click(screen.getByRole("button", { name: "道幅の説明を表示" }));

    expect(screen.getByText("道の広さを見ます。")).toBeInTheDocument();
  });

  it("有効な軸を押すと重みを0にして上げ、上書きしていなければ上書きの状態にする", async () => {
    serveCatalog();
    const { onRoutePreferenceChange, onOverrideEnabledChange } = renderPanel(
      { width: 0.5, traffic: 0.3, slope: 0.2, light: 0 },
      false,
    );
    await chipsShown();

    await userEvent.click(chip("道幅を無効にする"));

    expect(onRoutePreferenceChange).toHaveBeenCalledExactlyOnceWith({ width: 0, traffic: 0.3, slope: 0.2, light: 0 });
    expect(onOverrideEnabledChange).toHaveBeenCalledExactlyOnceWith(true);
  });

  it("上書きしている間は、上書きの状態を上げ直さない", async () => {
    serveCatalog();
    const { onOverrideEnabledChange } = renderPanel({ width: 0.5, traffic: 0.3, slope: 0.2, light: 0 }, true);
    await chipsShown();

    await userEvent.click(chip("道幅を無効にする"));

    expect(onOverrideEnabledChange).not.toHaveBeenCalled();
  });

  it("帯で動かしていない軸を有効にすると、既定の重みにする", async () => {
    serveCatalog();
    const { onRoutePreferenceChange } = renderPanel({ width: 0, traffic: 0.3, slope: 0.2, light: 0 });
    await chipsShown();

    await userEvent.click(chip("道幅を有効にする"));

    expect(onRoutePreferenceChange).toHaveBeenLastCalledWith({ width: 0.5, traffic: 0.3, slope: 0.2, light: 0 });
  });

  it("既定の重みが0の軸を有効にすると、0.1にする", async () => {
    serveCatalog();
    const { onRoutePreferenceChange } = renderPanel({ width: 0.5, traffic: 0.3, slope: 0.2, light: 0 });
    await chipsShown();

    await userEvent.click(chip("街灯を有効にする"));

    expect(onRoutePreferenceChange).toHaveBeenLastCalledWith({ width: 0.5, traffic: 0.3, slope: 0.2, light: 0.1 });
  });

  it("帯で動かした軸は、無効にしてから有効に戻すと動かした重みに戻る", async () => {
    serveCatalog();
    const { onRoutePreferenceChange } = renderPanel({ width: 0.5, traffic: 0.3, slope: 0.2, light: 0 });
    await chipsShown();

    boundary("道幅と交通の配分").focus();
    await userEvent.keyboard("{ArrowRight}");
    const moved = onRoutePreferenceChange.mock.lastCall![0].width;
    await userEvent.click(chip("道幅を無効にする"));
    await userEvent.click(chip("道幅を有効にする"));

    expect(onRoutePreferenceChange.mock.lastCall![0].width).toBe(moved);
    expect(moved).not.toBe(0.5);
  });

  it("既定の重みが後から変わったら、動かしていない軸の戻し先はその値に、動かした軸は動かした値のままにする", async () => {
    serveCatalog();
    const { onRoutePreferenceChange } = renderPanel({ width: 0.5, traffic: 0.3, slope: 0.2, light: 0 });
    await chipsShown();
    boundary("道幅と交通の配分").focus();
    await userEvent.keyboard("{ArrowRight}");
    const moved = onRoutePreferenceChange.mock.lastCall![0];

    // 軸カタログは読み手がマウントするたびに取り直すので、別の読み手を足して新しい既定を届ける。
    serveCatalog([
      { ...WIDTH, default_weight: 0.1 },
      { ...TRAFFIC, default_weight: 0.1 },
      { ...SLOPE, default_weight: 0.4 },
      LIGHT,
    ]);
    const reader = renderHook(() => useAxisCatalog());
    await waitFor(() => expect(reader.result.current.defaultWeights.slope).toBe(0.4));

    for (const name of ["道幅", "交通", "勾配"]) await userEvent.click(chip(`${name}を無効にする`));
    for (const name of ["道幅", "交通", "勾配"]) await userEvent.click(chip(`${name}を有効にする`));

    expect(onRoutePreferenceChange.mock.lastCall![0]).toEqual({
      width: moved.width,
      traffic: moved.traffic,
      slope: 0.4,
      light: 0,
    });
  });
});

describe("RouteSettingsPanel 配分の帯", () => {
  it("有効な軸ごとに、取り分の幅の区間を軸の色で並べる", async () => {
    serveCatalog();
    renderPanel({ width: 0.5, traffic: 0, slope: 0.3, light: 0.2 });
    await chipsShown();

    for (const [title, axisId, width] of [
      ["道幅 50%", "width", "50%"],
      ["勾配 30%", "slope", "30%"],
      ["街灯 20%", "light", "20%"],
    ]) {
      expect(screen.getByTitle(title)).toHaveStyle({ width, background: COLORS[axisId] });
    }
    expect(screen.queryByTitle(/^交通/)).not.toBeInTheDocument();
  });

  it("チップの印を、帯の区間と同じ軸の色で塗る", async () => {
    serveCatalog();
    renderPanel({ width: 0.5, traffic: 0, slope: 0.3, light: 0.2 });
    await chipsShown();

    for (const [name, axisId] of [
      ["道幅を無効にする", "width"],
      ["交通を有効にする", "traffic"],
    ]) {
      expect(chip(name).querySelector("span[aria-hidden='true']")).toHaveStyle({ color: COLORS[axisId] });
    }
  });

  it("広い区間はアイコンと%、やや狭い区間は数だけを書き、狭い区間には書かない", async () => {
    serveCatalog();
    renderPanel({ width: 0.86, traffic: 0.09, slope: 0.05, light: 0 });
    await chipsShown();

    const wide = screen.getByTitle("道幅 86%");
    expect(wide).toHaveTextContent(/^86%$/);
    expect(wide.querySelector("svg")).not.toBeNull();
    const narrow = screen.getByTitle("交通 9%");
    expect(narrow).toHaveTextContent(/^9$/);
    expect(narrow.querySelector("svg")).toBeNull();
    expect(screen.getByTitle("勾配 5%")).toHaveTextContent(/^$/);
  });

  it("ちょうど10%の区間はアイコンと%を、ちょうど6%の区間は数を書く", async () => {
    serveCatalog();
    renderPanel({ width: 0.84, traffic: 0.1, slope: 0.06, light: 0 });
    await chipsShown();

    const ten = screen.getByTitle("交通 10%");
    expect(ten).toHaveTextContent(/^10%$/);
    expect(ten.querySelector("svg")).not.toBeNull();
    expect(screen.getByTitle("勾配 6%")).toHaveTextContent(/^6$/);
  });

  it("隣り合う有効な軸の間ごとに、2軸の配分を動かす区切りを、左からの累積の割合（0〜100）の位置で出す", async () => {
    serveCatalog();
    renderPanel({ width: 0.5, traffic: 0, slope: 0.3, light: 0.2 });
    await chipsShown();

    const sliders = screen.getAllByRole("slider");
    expect(sliders.map((slider) => [slider.getAttribute("aria-label"), slider.getAttribute("aria-valuenow")])).toEqual([
      ["道幅と勾配の配分", "50"],
      ["勾配と街灯の配分", "80"],
    ]);
    for (const slider of sliders) {
      expect(slider).toHaveAttribute("aria-valuemin", "0");
      expect(slider).toHaveAttribute("aria-valuemax", "100");
    }
  });

  it("区切りで右・上の矢印は右の軸から左の軸へ1刻み移し、左・下の矢印は戻す。ほかの軸は変えず、上書きの状態にする", async () => {
    serveCatalog();
    const { onRoutePreferenceChange, onOverrideEnabledChange } = renderPanel(
      { width: 0.4, traffic: 0.3, slope: 0.3, light: 0 },
      false,
    );
    await chipsShown();

    boundary("道幅と交通の配分").focus();
    await userEvent.keyboard("{ArrowRight}{ArrowUp}");
    const forward = onRoutePreferenceChange.mock.lastCall![0];
    await userEvent.keyboard("{ArrowLeft}{ArrowDown}");
    const back = onRoutePreferenceChange.mock.lastCall![0];

    expect(onRoutePreferenceChange).toHaveBeenCalledTimes(4);
    expect(forward).toEqual({
      width: expect.closeTo(0.4 + 2 * WEIGHT_STEP, 5),
      traffic: expect.closeTo(0.3 - 2 * WEIGHT_STEP, 5),
      slope: 0.3,
      light: 0,
    });
    expect(back).toEqual({ width: 0.4, traffic: 0.3, slope: 0.3, light: 0 });
    expect(onOverrideEnabledChange).toHaveBeenCalledExactlyOnceWith(true);
  });

  it("矢印以外のキーと、もう動かせない向きの矢印では何も上げない", async () => {
    serveCatalog();
    const { onRoutePreferenceChange } = renderPanel({ width: WEIGHT_STEP, traffic: 0.3, slope: 0.3, light: 0 });
    await chipsShown();

    boundary("道幅と交通の配分").focus();
    await userEvent.keyboard("{Enter}{Home}{ArrowLeft}");

    expect(onRoutePreferenceChange).not.toHaveBeenCalled();
  });

  /** 帯の幅を決めて、区切りを押してから画面の上で指を動かす。 */
  async function startDrag(name: string, barWidthPx: number, startX: number) {
    const handle = boundary(name);
    vi.spyOn(handle.parentElement!, "getBoundingClientRect").mockReturnValue(
      DOMRect.fromRect({ x: 0, y: 0, width: barWidthPx, height: 30 }),
    );
    fireEvent.pointerDown(handle, { clientX: startX });
    return (clientX: number) => act(() => void window.dispatchEvent(new PointerEvent("pointermove", { clientX })));
  }

  it("区切りをドラッグすると、押した位置からの幅を帯の幅に対する重みへ換算して2軸の間で移し、指を離したら止まる", async () => {
    serveCatalog();
    const { onRoutePreferenceChange } = renderPanel({ width: 0.4, traffic: 0.3, slope: 0.3, light: 0 });
    await chipsShown();

    // 帯200pxが重みの合計1.0なので、1pxが0.005。
    const moveTo = await startDrag("道幅と交通の配分", 200, 100);
    moveTo(110);
    moveTo(120);
    act(() => void window.dispatchEvent(new PointerEvent("pointerup")));
    moveTo(150);

    expect(onRoutePreferenceChange.mock.calls.map(([next]) => next)).toEqual([
      { width: 0.45, traffic: 0.25, slope: 0.3, light: 0 },
      { width: 0.5, traffic: 0.2, slope: 0.3, light: 0 },
    ]);
  });

  it("ドラッグは、指の操作が取り消されても止まる", async () => {
    serveCatalog();
    const { onRoutePreferenceChange } = renderPanel({ width: 0.4, traffic: 0.3, slope: 0.3, light: 0 });
    await chipsShown();

    const moveTo = await startDrag("道幅と交通の配分", 200, 100);
    act(() => void window.dispatchEvent(new PointerEvent("pointercancel")));
    moveTo(150);

    expect(onRoutePreferenceChange).not.toHaveBeenCalled();
  });
});
