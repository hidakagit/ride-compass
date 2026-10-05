/**
 * `RouteSplicePanel/RouteSplicePanel.tsx`——区間の乗り換えの結果面。見出し行の操作、元と編集後の指標、軸別の差の棒、案内。
 *
 * 見るもの: 見出し（戻る・回数）と操作（1つ戻す・全部戻す・差分・作成）の出し方・押せる条件・上がる操作、区間を
 * 持たない候補の書き方、指標（距離・所要・総合難易度・負荷）の元・編集後・差の書き方と、表示する桁で丸めた差で決める
 * 良し悪しの印、寄与度が動いた軸の棒（出す境界・読み上げの並び・左右・長さ）と下に書く大きい軸、状態ごとの案内、
 * 合成の失敗。
 *
 * ここで見ないもの: どの区間を乗り換えるか・差分と作成の評価 → `features/route/useSpliceSession.test.ts`。
 * 差の表記（符号・桁）→ `features/route/routeEditDiff.test.ts`。所要の表記 → `features/route/formatDuration.test.ts`。
 * 良し悪しの印から付く色（クラスで付ける見た目）。受け取った値や書いた文をそのまま出すもの（棒の軸の色・(i)の奥の使い方）。
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { catalogEntry, catalogOf } from "@/testing/catalogAxes";
import { makeRouteCandidate } from "@/testing/routeFixtures";

import RouteSplicePanel from "./RouteSplicePanel";

type Props = ComponentProps<typeof RouteSplicePanel>;

const CATALOG = catalogOf([
  catalogEntry({ axis_id: "width", label: "道幅" }),
  catalogEntry({ axis_id: "traffic", label: "交通" }),
  catalogEntry({ axis_id: "slope", label: "勾配" }),
  catalogEntry({ axis_id: "light", label: "街灯" }),
]);

const DISPLAYED = makeRouteCandidate({
  edge_ids: ["e1", "e2", "e3"],
  distance_km: 12.3,
  estimated_duration_seconds: 1800,
  overall_difficulty: { average: 40.4, load: 300.6 },
  axis_contributions: { width: 10, traffic: 5, slope: 3 },
});

function renderPanel(props: Partial<Props> = {}) {
  const handlers = {
    onUndo: vi.fn(),
    onReset: vi.fn(),
    onPreview: vi.fn(),
    onApply: vi.fn(),
    onCancel: vi.fn(),
  };
  render(
    <RouteSplicePanel
      displayed={DISPLAYED}
      appliedCount={0}
      hasAlternatives
      preview={null}
      previewing={false}
      applying={false}
      error={null}
      axes={CATALOG.axes}
      axisColors={CATALOG.axisColors}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

/** 指標1つの、元・矢印・編集後・差のセル。 */
function metric(label: string) {
  const term = screen.getByText(label, { selector: "dt" });
  const base = term.nextElementSibling as HTMLElement;
  const arrow = base.nextElementSibling as HTMLElement;
  const after = arrow.nextElementSibling as HTMLElement;
  const delta = after.nextElementSibling as HTMLElement;
  return { base, arrow, after, delta };
}

/** 良し悪しの印（表示する差が増えたら悪い・減ったら良い）。 */
function verdict(cell: HTMLElement) {
  if (cell.dataset.worse === "true") return "悪い";
  if (cell.dataset.better === "true") return "良い";
  return "なし";
}

const ACTIONS = ["1つ戻す", "全部戻す", "差分を見る", "新しいルートを作成"];

describe("RouteSplicePanel 見出しと操作", () => {
  it("見出し「区間の乗り換え」の面を出し、戻る操作を押すと上げる", async () => {
    const { onCancel } = renderPanel();

    const panel = screen.getByRole("region", { name: "区間の乗り換え" });
    await userEvent.click(within(panel).getByRole("button", { name: "編集をやめて候補へ戻る" }));

    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("乗り換える前は回数と戻す操作を出さず、差分と作成を押せない", () => {
    renderPanel({ appliedCount: 0 });

    expect(screen.queryByText(/^\d+回$/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "1つ戻す" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "全部戻す" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "差分を見る" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "新しいルートを作成" })).toBeDisabled();
  });

  it("乗り換えた回数を出し、1つ戻す・全部戻す・差分・作成を押すとそれぞれ上げる", async () => {
    const { onUndo, onReset, onPreview, onApply } = renderPanel({ appliedCount: 2 });

    expect(screen.getByText("2回")).toBeInTheDocument();
    for (const name of ACTIONS) await userEvent.click(screen.getByRole("button", { name }));

    for (const handler of [onUndo, onReset, onPreview, onApply]) expect(handler).toHaveBeenCalledOnce();
  });

  it.each([
    ["差分の評価", { previewing: true }, "差分を見る"],
    ["作成", { applying: true }, "新しいルートを作成"],
  ] as const)("%sを待つ間は、どの操作も押せず、待っている操作に待ちの印を付ける", (_waiting, props, busy) => {
    renderPanel({ appliedCount: 1, ...props });

    for (const name of ACTIONS) {
      const button = screen.getByRole("button", { name });
      expect(button).toBeDisabled();
      if (name === busy) expect(button).toHaveAttribute("aria-busy", "true");
      else expect(button).not.toHaveAttribute("aria-busy", "true");
    }
  });

  it("区間を持たない候補では、操作と指標を出さずに区間を出せないことを書き、戻る操作は残す", () => {
    renderPanel({ displayed: { ...DISPLAYED, edge_ids: [] }, appliedCount: 1 });

    expect(screen.getByText("この候補は経路のEdge情報を持たないため、区間を出せません。")).toBeInTheDocument();
    for (const name of ACTIONS) expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    expect(screen.queryByText("距離", { selector: "dt" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "編集をやめて候補へ戻る" })).toBeInTheDocument();
  });
});

describe("RouteSplicePanel 指標", () => {
  it("差分を見る前は元の距離・所要・総合難易度・負荷だけを出し、矢印と編集後と差は出さない", () => {
    renderPanel({ appliedCount: 1 });

    expect(["距離", "所要", "総合難易度", "負荷"].map((label) => metric(label).base.textContent)).toEqual([
      "12.3",
      "30分",
      "40",
      "301",
    ]);
    for (const label of ["距離", "所要", "総合難易度", "負荷"]) {
      const { arrow, after, delta } = metric(label);
      expect([arrow.textContent, after.textContent, delta.textContent]).toEqual(["", "", ""]);
    }
  });

  it("差分を見たら元→編集後と差を出し、表示する桁で丸めた差が増えたら悪い・減ったら良い印を付ける", () => {
    const preview = makeRouteCandidate({
      edge_ids: ["e1", "e4", "e3"],
      distance_km: 13,
      estimated_duration_seconds: 1500,
      overall_difficulty: { average: 40.6, load: 280.2 },
    });
    renderPanel({ appliedCount: 1, preview });

    const rows = ["距離", "所要", "総合難易度", "負荷"].map((label) => {
      const { arrow, after, delta } = metric(label);
      return [label, arrow.textContent, after.textContent, delta.textContent, verdict(after), verdict(delta)];
    });
    expect(rows).toEqual([
      ["距離", "→", "13.0km", "+0.7", "悪い", "悪い"],
      ["所要", "→", "25分", "−5", "良い", "良い"],
      // 差0.2は0桁で書くと0になるので、良し悪しを言わない。
      ["総合難易度", "→", "41", "±0", "なし", "なし"],
      ["負荷", "→", "280", "−20", "良い", "良い"],
    ]);
  });

  it("元の値が無い指標は「—」を出し、差を出さない", () => {
    const preview = makeRouteCandidate({
      edge_ids: ["e1", "e4", "e3"],
      distance_km: 13,
      estimated_duration_seconds: 1500,
      overall_difficulty: { average: 40, load: 300 },
    });
    renderPanel({
      displayed: { ...DISPLAYED, estimated_duration_seconds: null, overall_difficulty: null },
      appliedCount: 1,
      preview,
    });

    const rows = ["所要", "総合難易度"].map((label) => {
      const { base, after, delta } = metric(label);
      return [base.textContent, after.textContent, delta.textContent];
    });
    expect(rows).toEqual([
      ["—", "25分", ""],
      ["—", "40", ""],
    ]);
  });
});

describe("RouteSplicePanel 軸別の差", () => {
  /** 寄与度: 道幅−2・交通+0.05（0.1未満）・勾配+3・街灯+0.1（ちょうど0.1。元に無い軸は0から）。 */
  const MOVED = makeRouteCandidate({
    edge_ids: ["e1", "e4", "e3"],
    distance_km: 12.3,
    axis_contributions: { width: 8, traffic: 5.05, slope: 6, light: 0.1 },
  });

  it("寄与度が0.1以上動いた軸を大きい順に棒の読み上げへ並べ、大きい2つを下に書く", () => {
    renderPanel({ appliedCount: 1, preview: MOVED });

    expect(screen.getByRole("img", { name: "勾配 +3.0、道幅 −2.0、街灯 +0.1" })).toBeInTheDocument();
    expect(screen.getByText("勾配 +3.0")).toBeInTheDocument();
    expect(screen.getByText("道幅 −2.0")).toBeInTheDocument();
    expect(screen.queryByText("街灯 +0.1")).not.toBeInTheDocument();
  });

  it("棒は中央を0に、減った軸を左・増えた軸を右へ、いちばん大きい差を片側いっぱいとする長さで描く", () => {
    renderPanel({ appliedCount: 1, preview: MOVED });

    const bar = screen.getByRole("img");
    const widths = (side: Element) => [...side.children].map((piece) => (piece as HTMLElement).style.width);
    const [decreased, increased] = [bar.firstElementChild!, bar.lastElementChild!];
    expect(widths(decreased).map(parseFloat)).toEqual([expect.closeTo((2 / 3) * 50, 5)]);
    expect(widths(increased).map(parseFloat)).toEqual([50, expect.closeTo((0.1 / 3) * 50, 5)]);
  });
});

describe("RouteSplicePanel 案内", () => {
  it.each([
    ["乗り換え先があれば", true, "地図の破線をタップして乗り換えます"],
    ["乗り換え先が無ければ", false, "他の候補と別の道を通る区間がありません。"],
  ] as const)("乗り換える前で%s、「%s」と出す", (_state, hasAlternatives, hint) => {
    renderPanel({ appliedCount: 0, hasAlternatives });

    expect(screen.getByText(hint)).toBeInTheDocument();
  });

  it("乗り換えて軸の差がまだ無ければ、棒を出さずに「差分を見る」を押す案内を出す", () => {
    renderPanel({ appliedCount: 1, hasAlternatives: false, preview: null });

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText(/乗り換えた結果が出ます/)).toHaveTextContent("差分を見るを押すと、乗り換えた結果が出ます");
  });

  it.each([
    ["合成した経路を評価できませんでした。", ["合成した経路を評価できませんでした。"]],
    [null, []],
  ])("合成に失敗した理由（%s）があるときだけ、知らせとして出す", (error, alerts) => {
    renderPanel({ appliedCount: 1, error });

    expect(screen.queryAllByRole("alert").map((alert) => alert.textContent)).toEqual(alerts);
  });
});
