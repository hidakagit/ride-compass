import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { PreferenceAxisDef } from "@/lib/evaluationAxes";

import RouteAxisProfile from "./RouteAxisProfile";

const axis = (axisId: string, label: string, extra: Partial<PreferenceAxisDef> = {}): PreferenceAxisDef => ({
  axisId,
  label,
  description: `${label}の説明文`,
  dedicatedWayValueLayer: false,
  ...extra,
});

const STOPS = axis("stops", "停止", { rawValueUnit: "回/km", rawValueTotalUnit: "回" });
const SURFACE = axis("surface", "路面", {
  materialBreakdown: [
    { materialId: "lit", label: "街灯あり", dtype: "boolean", unit: "", share: 0.5 },
    { materialId: "highway", label: "道の種類", dtype: "categorical", unit: "", share: 0.5 },
  ],
});
const UNUSED = axis("unused", "未使用");

type Props = React.ComponentProps<typeof RouteAxisProfile>;

function renderProfile(overrides: Partial<Props> = {}) {
  const props: Props = {
    axes: [STOPS, SURFACE, UNUSED],
    weights: { stops: 0.5, surface: 0.5, unused: 0 },
    axisDifficulties: { stops: 41.6, surface: 20 },
    axisContributions: { stops: 20.8, surface: 10, unused: 0 },
    axisRawValues: { stops: 0.8 },
    materialValues: { lit: 0.68 },
    materialCategoryShares: { highway: { residential: 0.62 } },
    distanceKm: 32.4,
    overallDifficulty: 30.8,
    difficultyLoad: 997.9,
    estimatedDurationSeconds: 102 * 60,
    axisColors: {},
    ...overrides,
  };
  return render(<RouteAxisProfile {...props} />);
}

async function openDetail(label: string) {
  await userEvent.click(screen.getByRole("button", { name: `${label}の詳細を表示` }));
}

describe("RouteAxisProfile 見出しの数値", () => {
  it("総合難易度・所要・負荷を出す（難易度と負荷は整数へ丸める）", () => {
    renderProfile();
    expect(screen.getByText("総合難易度").parentElement).toHaveTextContent("総合難易度31/100");
    expect(screen.getByText("所要").parentElement).toHaveTextContent("所要1時間42分");
    expect(screen.getByText("負荷").parentElement).toHaveTextContent("負荷998");
  });

  it("所要・負荷は、値が無ければ出さない", () => {
    renderProfile({ estimatedDurationSeconds: null, difficultyLoad: null });
    expect(screen.queryByText("所要")).not.toBeInTheDocument();
    expect(screen.queryByText("負荷")).not.toBeInTheDocument();
    expect(screen.getByText("総合難易度")).toBeInTheDocument();
  });

  it("総合難易度が無ければ、何も出さない", () => {
    const { container } = renderProfile({ overallDifficulty: null });
    expect(container).toHaveTextContent(/^$/);
  });
});

describe("RouteAxisProfile 内訳の帯", () => {
  it("寄与を持つ軸が1つも無ければ、帯の代わりにその旨を出す", () => {
    renderProfile({ axisContributions: { stops: 0, surface: 0, unused: 0 } });
    expect(screen.queryByRole("img", { name: "難易度の内訳" })).not.toBeInTheDocument();
    expect(screen.getByText("このルートで表示できる評価軸データがありません")).toBeInTheDocument();
  });
});

describe("RouteAxisProfile 軸の詳細", () => {
  it("評価に使っていない軸（重み0・重みの無い軸）は凡例に出さない", () => {
    renderProfile({ weights: { stops: 0.5, surface: 0.5 } });
    expect(screen.getByRole("button", { name: "停止の詳細を表示" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /未使用/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "未使用" })).not.toBeInTheDocument();
  });

  it("評価に使った軸は、このルートで寄与が0・値が来ない軸も凡例に残す（効くはずの軸が効かなかったことも判断材料）", () => {
    renderProfile({ axisContributions: { stops: 20.8, surface: 0 } });
    expect(screen.getByRole("button", { name: "路面の詳細を表示" })).toBeInTheDocument();
  });

  it("軸別難易度・単位付きの生値（総量つき）・説明を出す", async () => {
    renderProfile();
    await openDetail("停止");
    const detail = await screen.findByText("停止の説明文");
    expect(detail.parentElement).toHaveTextContent("軸別難易度 42/100");
    expect(detail.parentElement).toHaveTextContent("0.8回/km・約26回");
  });

  it("生値の単位が定まらない軸は、材料ごとの内訳を並べる（分類の材料は最も長い値）", async () => {
    renderProfile();
    await openDetail("路面");
    const detail = await screen.findByText("路面の説明文");
    expect(detail.parentElement).toHaveTextContent("この軸の内訳: 街灯あり 68%・residential 62%");
  });

  it("値の届かない材料は内訳から落とし、1つも無ければ内訳の行を出さない", async () => {
    renderProfile({ materialValues: {}, materialCategoryShares: {} });
    await openDetail("路面");
    const detail = await screen.findByText("路面の説明文");
    expect(detail.parentElement).not.toHaveTextContent("この軸の内訳");
  });

  it("軸別難易度が無い軸は「データなし」", async () => {
    renderProfile({ axisDifficulties: { surface: 20 } });
    await openDetail("停止");
    expect((await screen.findByText("停止の説明文")).parentElement).toHaveTextContent("データなし");
  });
});
