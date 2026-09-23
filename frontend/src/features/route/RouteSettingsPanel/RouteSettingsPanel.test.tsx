import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { RoutePreferenceWeights } from "@/types/route";

import RouteSettingsPanel from "./RouteSettingsPanel";

// 軸カタログはテストが直接決める（取得の流れは`useAxisCatalog`自身のテストが見る）。
const hook = vi.hoisted(() => ({ catalog: null as unknown as AxisCatalog, retry: vi.fn() }));
vi.mock("@/hooks/useAxisCatalog", () => ({
  useAxisCatalog: () => hook.catalog,
  retryAxisCatalogFetch: hook.retry,
}));

const axis = (axisId: string, label: string, chipLabel: string | null = null): PreferenceAxisDef => ({
  axisId,
  label,
  chipLabel,
  description: `${label}の説明文`,
  dedicatedWayValueLayer: false,
});

const AXES = [axis("surface", "路面の質", "路面"), axis("traffic", "交通量"), axis("slope", "勾配")];

function catalogOf(overrides: Partial<AxisCatalog> = {}): AxisCatalog {
  return {
    ...EMPTY_CATALOG,
    axes: AXES,
    defaultWeights: { surface: 0.5, traffic: 0.3, slope: 0.2 },
    axisColors: { surface: "#111111", traffic: "#222222", slope: "#333333" },
    loaded: true,
    ...overrides,
  };
}

beforeEach(() => {
  hook.catalog = catalogOf();
  hook.retry.mockClear();
});

/** 重みと上書きの有効フラグを親として持つ。親へ渡った値は`changes`に並ぶ。 */
function renderPanel(initial: RoutePreferenceWeights, { overrideEnabled = false } = {}) {
  const changes: RoutePreferenceWeights[] = [];
  const onOverrideEnabledChange = vi.fn();
  function Parent() {
    const [weights, setWeights] = useState(initial);
    return (
      <RouteSettingsPanel
        routePreference={weights}
        onRoutePreferenceChange={(next) => {
          changes.push(next);
          setWeights(next);
        }}
        overrideEnabled={overrideEnabled}
        onOverrideEnabledChange={onOverrideEnabledChange}
      />
    );
  }
  const view = render(<Parent />);
  /** 同じ画面のまま描き直す（カタログを差し替えた後に、新しいカタログを読ませる）。 */
  const refresh = () => view.rerender(<Parent />);
  return { changes, onOverrideEnabledChange, refresh, ...view };
}

const chipNames = () =>
  screen.getAllByRole("button", { name: /を(有効|無効)にする$/ }).map((chip) => chip.getAttribute("aria-label"));

describe("RouteSettingsPanel 軸のチップ", () => {
  it("有効な軸を先に、無効な軸を後ろに、それぞれカタログの並びで出す", () => {
    renderPanel({ surface: 0, traffic: 0.3, slope: 0.2 });
    expect(chipNames()).toEqual(["交通量を無効にする", "勾配を無効にする", "路面の質を有効にする"]);
  });

  it("有効な軸だけに、全体に対する取り分（%）を添える。名前は略名があれば略名", () => {
    renderPanel({ surface: 0, traffic: 0.3, slope: 0.2 });
    expect(screen.getByRole("button", { name: "交通量を無効にする" })).toHaveTextContent("交通量60%");
    expect(screen.getByRole("button", { name: "勾配を無効にする" })).toHaveTextContent("勾配40%");
    expect(screen.getByRole("button", { name: "路面の質を有効にする" })).toHaveTextContent(/^路面$/);
  });

  it("軸の説明は、軸ごとの(i)から読める", async () => {
    renderPanel({ surface: 0.5, traffic: 0.3, slope: 0.2 });
    await userEvent.click(screen.getByRole("button", { name: "交通量の説明を表示" }));
    expect(await screen.findByText("交通量の説明文")).toBeInTheDocument();
  });

  it("無効にすると重みを0にし、上書きをONにする（既にONなら触らない）", async () => {
    const off = renderPanel({ surface: 0.5, traffic: 0.3, slope: 0.2 });
    await userEvent.click(screen.getByRole("button", { name: "交通量を無効にする" }));
    expect(off.changes.at(-1)).toEqual({ surface: 0.5, traffic: 0, slope: 0.2 });
    expect(off.onOverrideEnabledChange).toHaveBeenCalledWith(true);
    off.unmount();

    const alreadyOn = renderPanel({ surface: 0.5, traffic: 0.3, slope: 0.2 }, { overrideEnabled: true });
    await userEvent.click(screen.getByRole("button", { name: "交通量を無効にする" }));
    expect(alreadyOn.onOverrideEnabledChange).not.toHaveBeenCalled();
  });

  it("有効に戻すと、最後に使っていた重みに戻す", async () => {
    const { changes } = renderPanel({ surface: 0.5, traffic: 0.3, slope: 0.2 });
    const boundary = screen.getByRole("slider", { name: "路面の質と交通量の配分" });
    act(() => boundary.focus());
    await userEvent.keyboard("{ArrowLeft}");
    await userEvent.click(screen.getByRole("button", { name: "交通量を無効にする" }));
    await userEvent.click(screen.getByRole("button", { name: "交通量を有効にする" }));
    expect(changes.at(-1)?.traffic).toBe(0.31);
  });

  it("使っていた重みが無ければ既定の重み、既定も無ければ0.1にする", async () => {
    hook.catalog = catalogOf({ axes: [...AXES, axis("night", "夜道")] });
    const { changes } = renderPanel({ surface: 0, traffic: 0.3, slope: 0.2, night: 0 });
    await userEvent.click(screen.getByRole("button", { name: "路面の質を有効にする" }));
    expect(changes.at(-1)?.surface).toBe(0.5);
    await userEvent.click(screen.getByRole("button", { name: "夜道を有効にする" }));
    expect(changes.at(-1)?.night).toBe(0.1);
  });

  it("既定の重みが後から変わったら、利用者が変えていない軸の戻し先はその値に、変えた軸は変えた値のままにする", async () => {
    const { changes, refresh } = renderPanel({ surface: 0, traffic: 0.3, slope: 0.2 });
    // 交通量の戻し先を、利用者の操作で0.31にしておく。
    act(() => screen.getByRole("slider", { name: "交通量と勾配の配分" }).focus());
    await userEvent.keyboard("{ArrowRight}");
    hook.catalog = catalogOf({ defaultWeights: { surface: 0.4, traffic: 0.4, slope: 0.2 } });
    refresh();

    await userEvent.click(screen.getByRole("button", { name: "路面の質を有効にする" }));
    expect(changes.at(-1)?.surface).toBe(0.4);
    await userEvent.click(screen.getByRole("button", { name: "交通量を無効にする" }));
    await userEvent.click(screen.getByRole("button", { name: "交通量を有効にする" }));
    expect(changes.at(-1)?.traffic).toBe(0.31);
  });
});

describe("RouteSettingsPanel 軸カタログとの合わせ込み", () => {
  it("取得できたら、重みのキーをカタログへ合わせる（値は変えないので上書きはONにしない）", () => {
    const { changes, onOverrideEnabledChange } = renderPanel({ surface: 0.2, removed: 0.8 });
    expect(changes).toEqual([{ surface: 0.2, traffic: 0.3, slope: 0.2 }]);
    expect(onOverrideEnabledChange).not.toHaveBeenCalled();
  });

  it("取得できていない間は合わせない（軸0件へ合わせると保存済みの重みが消える）", () => {
    hook.catalog = catalogOf({ loaded: false });
    const { changes } = renderPanel({ surface: 0.2, removed: 0.8 });
    expect(changes).toEqual([]);
  });

  it("取得に失敗したら、何が起きるかを伝え、再試行できるようにする", async () => {
    hook.catalog = { ...EMPTY_CATALOG, failed: true };
    renderPanel({});
    expect(screen.getByRole("status")).toHaveTextContent("軸一覧を取得できませんでした");
    await userEvent.click(screen.getByRole("button", { name: "再試行" }));
    expect(hook.retry).toHaveBeenCalled();
  });

  it("失敗していなければ、その案内は出さない", () => {
    renderPanel({ surface: 0.5, traffic: 0.3, slope: 0.2 });
    expect(screen.queryByRole("button", { name: "再試行" })).not.toBeInTheDocument();
  });
});

describe("RouteSettingsPanel 配分の帯", () => {
  const segment = (label: string) => screen.getByTitle(new RegExp(`^${label} `));

  it("有効な軸ごとに、取り分の幅の区間を並べる", () => {
    renderPanel({ surface: 0, traffic: 0.3, slope: 0.2 });
    expect(segment("交通量")).toHaveAttribute("title", "交通量 60%");
    expect(segment("交通量").style.width).toBe("60%");
    expect(screen.queryByTitle(/^路面の質 /)).not.toBeInTheDocument();
  });

  it("区間の中の表記は幅で落とす（10%以上はアイコンと%・6%以上は数字だけ・それ未満は何も出さない）", () => {
    renderPanel({ surface: 0.9, traffic: 0.07, slope: 0.03 });
    expect(segment("路面の質")).toHaveTextContent("90%");
    expect(segment("路面の質").querySelector("svg")).not.toBeNull();
    expect(segment("交通量")).toHaveTextContent(/^7$/);
    expect(segment("勾配")).toHaveTextContent(/^$/);
  });

  it("10%ちょうどならアイコンと%、6%ちょうどなら数字を出す", () => {
    renderPanel({ surface: 0.84, traffic: 0.1, slope: 0.06 });
    expect(segment("交通量")).toHaveTextContent(/^10%$/);
    expect(segment("交通量").querySelector("svg")).not.toBeNull();
    expect(segment("勾配")).toHaveTextContent(/^6$/);
  });

  it("隣り合う有効な軸の間に区切りを置き、区切りの位置を累積の%で示す", () => {
    renderPanel({ surface: 0.5, traffic: 0.3, slope: 0.2 });
    const boundaries = screen.getAllByRole("slider");
    expect(boundaries.map((b) => b.getAttribute("aria-label"))).toEqual([
      "路面の質と交通量の配分",
      "交通量と勾配の配分",
    ]);
    expect(boundaries.map((b) => b.getAttribute("aria-valuenow"))).toEqual(["50", "80"]);
  });

  it("区切りを矢印キーで動かすと、両隣の2軸の間でだけ0.01ずつ重みを移す（1回の変更で両方）", async () => {
    const { changes } = renderPanel({ surface: 0.5, traffic: 0.3, slope: 0.2 });
    act(() => screen.getByRole("slider", { name: "路面の質と交通量の配分" }).focus());
    await userEvent.keyboard("{ArrowRight}");
    expect(changes).toEqual([{ surface: 0.51, traffic: 0.29, slope: 0.2 }]);
    await userEvent.keyboard("{ArrowDown}");
    expect(changes.at(-1)).toEqual({ surface: 0.5, traffic: 0.3, slope: 0.2 });
  });

  it("矢印以外のキーと、もう動かせない向きの矢印では何もしない", async () => {
    const { changes } = renderPanel({ surface: 0.59, traffic: 0.01, slope: 0.2 });
    act(() => screen.getByRole("slider", { name: "路面の質と交通量の配分" }).focus());
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard("{ArrowRight}");
    expect(changes).toEqual([]);
  });

  it("帯の幅が取れない間（描かれていない）は、ドラッグしても配分を変えない", () => {
    const { changes } = renderPanel({ surface: 0.25, traffic: 0.25, slope: 0 });
    const boundary = screen.getByRole("slider", { name: "路面の質と交通量の配分" });
    vi.spyOn(boundary.parentElement!, "getBoundingClientRect").mockReturnValue({ width: 0 } as DOMRect);
    fireEvent.pointerDown(boundary, { clientX: 50 });
    act(() => {
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: 60 }));
    });
    expect(changes).toEqual([]);
  });

  it("区切りをドラッグすると、動かした幅を重みに換算して2軸の間で移し、指を離したら止まる", () => {
    const { changes } = renderPanel({ surface: 0.25, traffic: 0.25, slope: 0 });
    const boundary = screen.getByRole("slider", { name: "路面の質と交通量の配分" });
    // 帯の幅100pxに全体0.5が乗る＝1pxあたり0.005。
    vi.spyOn(boundary.parentElement!, "getBoundingClientRect").mockReturnValue({ width: 100 } as DOMRect);
    fireEvent.pointerDown(boundary, { clientX: 50 });
    act(() => {
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: 60 }));
    });
    expect(changes.at(-1)).toMatchObject({ surface: 0.3, traffic: 0.2 });
    act(() => {
      window.dispatchEvent(new MouseEvent("pointerup"));
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: 90 }));
    });
    expect(changes).toHaveLength(1);
  });
});
