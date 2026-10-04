/**
 * `features/route/RouteAxisProfile/RouteAxisProfile.tsx`——候補の中身の総合難易度・所要・負荷と、重み付きの寄与の帯。
 *
 * 見るもの: 総合難易度が無ければ何も描かないこと、総合難易度・所要・負荷の数（丸め）と所要が無いときの省き方、
 * 所要時間の前提が崩れたことの注記（風・値の無い区間の割合を丸めて1%以上）、寄与が1つも無いときの案内、
 * 凡例のチップに並ぶ軸（重みが0・重みの無い軸は出さず、重みがあれば寄与が無くても出す）、チップから開く軸の詳細
 * （軸別難易度の丸めと「データなし」・生値・材料の内訳・説明）。
 *
 * ここで見ないもの: 帯の積み方・チップの値と色 → `components/AxisContributionBar`。生値と内訳の1件の書き方 →
 * `features/route/RouteAxisProfile/axisRawValue.ts`。所要の書き方 → `features/route/formatDuration.ts`。
 *
 * 軸は架空のもの（`axis_a`等）を`src/testing/catalogAxes.ts`の雛形から作る。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LOAD_BAR_MAX_HEIGHT_RATIO } from "@/features/route/difficultyLoadBar";
import { catalogAxisFromEntry } from "@/lib/catalogAxis";
import { catalogEntry } from "@/testing/catalogAxes";
import RouteAxisProfile from "./RouteAxisProfile";

const A = catalogAxisFromEntry(catalogEntry({ axis_id: "axis_a", label: "軸A", description: "軸Aの説明" }));
const B = catalogAxisFromEntry(catalogEntry({ axis_id: "axis_b", label: "軸B" }));
const C = catalogAxisFromEntry(catalogEntry({ axis_id: "axis_c", label: "軸C" }));

type Props = React.ComponentProps<typeof RouteAxisProfile>;

function renderProfile(props: Partial<Props> = {}) {
  return render(
    <RouteAxisProfile
      axes={[A, B, C]}
      weights={{ axis_a: 0.5, axis_b: 0.5, axis_c: 0 }}
      axisDifficulties={{}}
      axisContributions={{ axis_a: 20 }}
      axisRawValues={{}}
      materialValues={{}}
      materialCategoryShares={{}}
      distanceKm={30}
      overallDifficulty={{ average: 41.6, load: 1248.4 }}
      estimatedDurationSeconds={3720}
      windUnavailable={false}
      missingTravelDataShare={null}
      axisColors={{}}
      {...props}
    />,
  );
}

/** 凡例のチップから開いた軸の詳細の文。 */
async function openDetail(label: string): Promise<string> {
  await userEvent.click(screen.getByRole("button", { name: `${label}の詳細を表示` }));
  return screen.getByRole("dialog").textContent ?? "";
}

describe("RouteAxisProfile", () => {
  it("総合難易度が無い候補では何も出さない", () => {
    const { container } = renderProfile({ overallDifficulty: null });
    expect(container.textContent).toBe("");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("総合難易度・所要・負荷を丸めて並べ、それぞれに(i)の説明を持つ", () => {
    renderProfile();
    expect(screen.getByText("総合難易度").parentElement).toHaveTextContent("総合難易度42/100");
    expect(screen.getByText("所要").parentElement).toHaveTextContent("所要62分");
    expect(screen.getByText("負荷").parentElement).toHaveTextContent("負荷1248");
    for (const name of ["総合難易度の説明を表示", "所要時間の説明を表示", "負荷の説明を表示"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("負荷の(i)の奥に、一覧の帯の高さが頭打ちになる倍率を書く", async () => {
    renderProfile();
    await userEvent.click(screen.getByRole("button", { name: "負荷の説明を表示" }));
    expect(
      await screen.findByText(new RegExp(`最も短い候補の\\s*${LOAD_BAR_MAX_HEIGHT_RATIO}倍で頭打ち`)),
    ).toBeInTheDocument();
  });

  it("所要時間が無い候補では所要を出さない", () => {
    renderProfile({ estimatedDurationSeconds: null });
    expect(screen.queryByText("所要")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "所要時間の説明を表示" })).not.toBeInTheDocument();
  });

  it("風の値を使えなかった候補にだけ、無風として出した所要時間だと注記する", () => {
    const { unmount } = renderProfile({ windUnavailable: true });
    expect(
      screen.getByText("風のモデルの計算値を使えなかったため、無風として所要時間を出しています"),
    ).toBeInTheDocument();
    unmount();
    renderProfile({ windUnavailable: false });
    expect(screen.queryByText(/無風として/)).not.toBeInTheDocument();
  });

  it.each([
    [null, null],
    [0.004, null],
    [0.012, "データの無い区間が1%[坂・信号の無い道として所要時間を出しています]"],
    [0.25, "データの無い区間が25%[坂・信号の無い道として所要時間を出しています]"],
  ])("値の無い区間の割合が%sなら、注記は%s（百分率へ丸めて1以上のときだけ出す）", (share, expected) => {
    renderProfile({ missingTravelDataShare: share });
    if (expected === null) expect(screen.queryByText(/データの無い区間が/)).not.toBeInTheDocument();
    else expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("寄与のある軸が1つも無ければ、帯の代わりに表示できるデータが無いと案内する", () => {
    renderProfile({ axisContributions: { axis_a: 0 } });
    expect(screen.getByText("このルートで表示できる評価軸データがありません")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "難易度の内訳" })).not.toBeInTheDocument();
  });

  it("凡例のチップは評価に使った軸だけで、重みがあれば寄与が無くても出す", () => {
    renderProfile({ weights: { axis_a: 0.5, axis_b: 0.5, axis_c: 0 } });
    expect(screen.getByRole("img", { name: "難易度の内訳" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "軸Aの詳細を表示" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "軸Bの詳細を表示" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "軸Cの詳細を表示" })).not.toBeInTheDocument();
  });

  it("重みの辞書に無い軸は、重み0と同じく凡例に出さない", () => {
    renderProfile({ weights: { axis_a: 0.5 }, axisContributions: { axis_a: 20, axis_b: 5 } });
    expect(screen.queryByRole("button", { name: "軸Bの詳細を表示" })).not.toBeInTheDocument();
  });

  it("軸の詳細は、名前・丸めた軸別難易度・生値と総量・材料の内訳・説明を並べる", async () => {
    const axis = catalogAxisFromEntry(
      catalogEntry({
        axis_id: "axis_a",
        label: "軸A",
        description: "軸Aの説明",
        raw_value_unit: "回/km",
        raw_value_total_unit: "回",
        material_breakdown: [
          { material_id: "lit", label: "街灯あり", dtype: "boolean", unit: "", share: 0.5, value_labels: {} },
          { material_id: "absent", label: "値の来ない材料", dtype: "numeric", unit: "m", share: 0.2, value_labels: {} },
          {
            material_id: "road_kind",
            label: "道の種類",
            dtype: "categorical",
            unit: "",
            share: 0.3,
            value_labels: { residential: "住宅街の道" },
          },
        ],
      }),
    );
    renderProfile({
      axes: [axis],
      weights: { axis_a: 1 },
      axisDifficulties: { axis_a: 37.5 },
      axisRawValues: { axis_a: 0.8 },
      materialValues: { lit: 0.68 },
      materialCategoryShares: { road_kind: { residential: 0.62, primary: 0.38 } },
      distanceKm: 32.5,
    });
    const detail = await openDetail("軸A");
    expect(detail).toContain("軸A");
    expect(detail).toContain("軸別難易度 38/100");
    expect(detail).toContain("0.8回/km・約26回");
    expect(detail).toContain("この軸の内訳: 街灯あり 68%・住宅街の道 62%");
    expect(detail).toContain("軸Aの説明");
  });

  it("軸別難易度の値が来ない軸の詳細は「データなし」で、生値も内訳も出さない", async () => {
    renderProfile({ weights: { axis_a: 0.5, axis_b: 0.5 } });
    const detail = await openDetail("軸B");
    expect(detail).toContain("データなし");
    expect(detail).not.toContain("軸別難易度");
    expect(detail).not.toContain("この軸の内訳");
  });
});
