/**
 * `RouteSettingsPanel/RouteSettingsPanel.tsx`——「重み」タブ。配分の帯（区間・区切りのドラッグと矢印キー）と軸のチップ。
 *
 * 見るもの: 軸一覧を取れないときの告知と再試行、公開軸ごとのチップ（有効な軸を先に・割合・押して有効/無効）、
 * 有効に戻したときの重み（既定が0なら backend が宣言する値、既定が後から変わったときの追い方と帯で動かした値）、
 * 帯に置く有効な軸と、区間に書く文字の落とし方（境界ちょうどの割合）、区切り（隣り合う有効な軸ごと・累積の割合）を矢印キーと
 * ドラッグで動かして上がる2軸の重み、重みを変えると上書きの状態にすること。
 *
 * ここで見ないもの: 区切りを動かした量を範囲へ寄せて刻みへ丸めること → `features/route/routeWeightShare.test.ts`。
 * 受け取る重みを公開軸へ揃えること → `features/route/routePreferenceSync.test.ts`（このパネルは揃った値を受け取る）。
 * 再試行で取れたかどうか → `hooks/useAxisCatalog.test.ts`。無効な軸のチップを薄くすること（クラスで付ける見た目）。
 * 軸カタログの値をそのまま渡すもの（チップの印と帯の区間の色・(i)の奥の軸の説明）、割合に%を付けて渡す区間の幅、
 * 書いた定数を差し込むだけのもの（帯の(i)の奥の上限・区切りの値の範囲）。
 *
 * 差し替えたもの: 軸カタログの応答（網の層）はテストが決め、軸は架空のもの
 * （`testing/catalogAxes.ts`）。帯の実寸はテスト環境に無いので、ドラッグのテストだけ帯の`getBoundingClientRect`を決める。
 * 重みと上書きの状態は親が持つので、テストの包みが上がった値を持ち直して渡す。
 */
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ENABLED_AXIS_WEIGHT, WEIGHT_STEP } from "@/features/route/routeWeightShare";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { inTurn, onBackend, serveAxisCatalog } from "@/testing/backendServer";
import { catalogEntry, catalogResponse } from "@/testing/catalogAxes";
import type { RoutePreferenceWeights } from "@/types/route";

import RouteSettingsPanel from "./RouteSettingsPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

const WIDTH = catalogEntry({
  axis_id: "width",
  label: "道幅",
  description: "道の広さを見ます。",
  default_weight: 0.5,
});
const TRAFFIC = catalogEntry({ axis_id: "traffic", label: "交通", default_weight: 0.3 });
const SLOPE = catalogEntry({ axis_id: "slope", label: "勾配", default_weight: 0.2 });
const LIGHT = catalogEntry({ axis_id: "light", label: "街灯", default_weight: 0 });
const AXES = [WIDTH, TRAFFIC, SLOPE, LIGHT];

function serveCatalog(entries = AXES) {
  serveAxisCatalog(catalogResponse(entries));
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

describe("RouteSettingsPanel 評価軸の一覧を取れないとき", () => {
  it("重みが反映されないことと再試行を出し、再試行を押すと取り直して告知を下ろす", async () => {
    onBackend(
      "GET",
      "/api/axis-catalog",
      inTurn(new Response(null, { status: 503 }), Response.json(catalogResponse(AXES))),
    );
    renderPanel({});

    expect(await screen.findByRole("status")).toHaveTextContent(
      "評価軸の一覧を取得できませんでした。地図の道路・スポットを表示できません。ルートは重み配分を変えていても反映できず、既定の配分で作ります。ルートの合成も使えません。",
    );

    await userEvent.click(screen.getByRole("button", { name: "再試行" }));

    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  });
});

describe("RouteSettingsPanel 軸のチップ", () => {
  it("公開軸ごとに名前のチップを、有効な軸を先に、それぞれカタログの並びのまま出す", async () => {
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
    expect(chip("道幅を有効にする")).toHaveTextContent(/^道幅$/);
  });

  it("有効な軸のチップに重みの合計に占める割合を出し、無効な軸には出さない", async () => {
    serveCatalog();
    renderPanel({ width: 0.5, traffic: 0, slope: 0.2, light: 0 });
    await chipsShown();

    expect(chip("道幅を無効にする")).toHaveTextContent("71%");
    expect(chip("勾配を無効にする")).toHaveTextContent("29%");
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

  it("既定の重みが0の軸を有効にすると、backendが宣言する入れたときの重みにする", async () => {
    serveCatalog();
    const { onRoutePreferenceChange } = renderPanel({ width: 0.5, traffic: 0.3, slope: 0.2, light: 0 });
    await chipsShown();

    await userEvent.click(chip("街灯を有効にする"));

    expect(onRoutePreferenceChange).toHaveBeenLastCalledWith({
      width: 0.5,
      traffic: 0.3,
      slope: 0.2,
      light: ENABLED_AXIS_WEIGHT,
    });
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
  it("区間には、10%以上ならアイコンと%を、6%以上なら数だけを書き、それより狭ければ書かない", async () => {
    serveCatalog();
    renderPanel({ width: 0.79, traffic: 0.1, slope: 0.06, light: 0.05 });
    await chipsShown();

    for (const [title, text, icon] of [
      ["交通 10%", /^10%$/, true],
      ["勾配 6%", /^6$/, false],
      ["街灯 5%", /^$/, false],
    ] as const) {
      const segment = screen.getByTitle(title);
      expect(segment).toHaveTextContent(text);
      expect(segment.querySelector("svg") !== null).toBe(icon);
    }
  });

  it("帯には有効な軸だけを置き、隣り合う有効な軸の間ごとに、2軸の配分を動かす区切りを累積の割合（0〜100）の位置で出す", async () => {
    serveCatalog();
    renderPanel({ width: 0.5, traffic: 0, slope: 0.3, light: 0.2 });
    await chipsShown();

    const sliders = screen.getAllByRole("slider");
    expect(sliders.map((slider) => [slider.getAttribute("aria-label"), slider.getAttribute("aria-valuenow")])).toEqual([
      ["道幅と勾配の配分", "50"],
      ["勾配と街灯の配分", "80"],
    ]);
    expect(screen.queryByTitle(/^交通/)).not.toBeInTheDocument();
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

  it("合計が1でない配分でも、区切りは割合の上限（説明の文の%）で止まる", async () => {
    serveCatalog();
    // 合計 0.38 で、道幅は 0.22（58%）。もう1刻み足すと 0.23（61%）で上限を越える。
    const { onRoutePreferenceChange } = renderPanel({ width: 0.22, traffic: 0.08, slope: 0.08, light: 0 });
    await chipsShown();

    boundary("道幅と交通の配分").focus();
    await userEvent.keyboard("{ArrowRight}");
    await userEvent.click(screen.getByRole("button", { name: "重みの配分の説明を表示" }));

    expect(onRoutePreferenceChange).not.toHaveBeenCalled();
    expect(await screen.findByText(/1つの評価軸に置ける重みは60%まで/)).toBeInTheDocument();
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

  it.each(["pointerup", "pointercancel"])(
    "区切りをドラッグすると、押した位置からの幅を帯の幅に対する重みへ換算して2軸の間で移し、%sで止まる",
    async (end) => {
      serveCatalog();
      const { onRoutePreferenceChange } = renderPanel({ width: 0.4, traffic: 0.3, slope: 0.3, light: 0 });
      await chipsShown();

      // 帯200pxが重みの合計1.0なので、1pxが0.005。
      const moveTo = await startDrag("道幅と交通の配分", 200, 100);
      moveTo(110);
      moveTo(120);
      act(() => void window.dispatchEvent(new PointerEvent(end)));
      moveTo(150);

      expect(onRoutePreferenceChange.mock.calls.map(([next]) => next)).toEqual([
        { width: 0.45, traffic: 0.25, slope: 0.3, light: 0 },
        { width: 0.5, traffic: 0.2, slope: 0.3, light: 0 },
      ]);
    },
  );
});
