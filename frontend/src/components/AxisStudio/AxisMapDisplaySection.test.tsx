/**
 * `AxisMapDisplaySection.tsx`——地図の色分けしきい値と体感ラベルの入力欄。
 *
 * ここで見るのは**下書きがどう変わるか**だけ。下書きをpayloadへ変えて保存する経路は
 * `AxisComposer`（`AxisComposer.test.tsx`）が持つ。しきい値の文字列の解析そのものは
 * `axisDraft.thresholds.test.ts`が直接見ている。
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { AxisMapDisplaySection } from "./AxisMapDisplaySection";
import { draftFromExisting, emptyDraft, type Draft } from "./axisDraft";
import { baseAxisDefinition } from "@/testing/axisDefinitionFixtures";
import { materialCatalogFixture } from "@/testing/materialCatalogFixture";
import type { AxisDefinitionResponse } from "@/types/route";
import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import type { MapBandsOfThresholds } from "@/services/axisPreviewApi";

const MATERIALS: readonly AxisMaterialOption[] = materialCatalogFixture().materials.map((m) => ({
  id: m.material_id,
  label: m.label,
  name: m.name,
  description: m.description,
  dtype: m.dtype,
  unit: m.unit,
  referencePoints: m.reference_points,
}));

/** 節だけを立ち上げ、いまの下書きを読み出せるようにする。 */
function openSection(
  options: {
    editing?: AxisDefinitionResponse | null;
    restrictedDisplayOnly?: boolean;
    mapBandColors?: (boundaries: readonly number[]) => readonly string[];
    mapValueUnit?: string;
    mapBands?: MapBandsOfThresholds;
    onThresholdErrorChange?: (error: string | null) => void;
  } = {},
) {
  const editing = options.editing ?? null;
  const latest: { draft: Draft } = {
    draft: editing ? draftFromExisting(editing, MATERIALS) : emptyDraft(MATERIALS),
  };

  function Harness() {
    const [draft, setDraft] = useState<Draft>(latest.draft);
    latest.draft = draft;
    return (
      <AxisMapDisplaySection
        draft={draft}
        setDraft={setDraft}
        editing={editing}
        restrictedDisplayOnly={options.restrictedDisplayOnly ?? false}
        mapBandColors={options.mapBandColors}
        mapValueUnit={options.mapValueUnit ?? ""}
        mapBands={options.mapBands}
        onThresholdErrorChange={options.onThresholdErrorChange ?? vi.fn()}
      />
    );
  }

  render(<Harness />);
  return { user: userEvent.setup(), latest };
}

async function turnOverrideOn(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
}

describe("色分けのしきい値", () => {
  it("既定は自動計算で、入力欄を出すまでまとめ入力は現れない", async () => {
    const { user, latest } = openSection();

    expect(screen.queryByLabelText("色分けのしきい値（まとめて入力）")).not.toBeInTheDocument();
    await turnOverrideOn(user);

    expect(screen.getByLabelText("色分けのしきい値（まとめて入力）")).toBeInTheDocument();
    expect(latest.draft.displayThresholdsOverride).toEqual([]);
  });

  it("まとめて貼り付けた境界が、そのまま段階になる", async () => {
    const { user, latest } = openSection();

    await turnOverrideOn(user);
    await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "-10, -5, -1, 1, 2, 3");

    expect(latest.draft.displayThresholdsOverride).toEqual([-10, -5, -1, 1, 2, 3]);
    // 段階数（しきい値+1）と両端が、入力した場で分かる。
    expect(screen.getByLabelText("色分けプレビュー（7段階）")).toBeInTheDocument();
    expect(screen.getByText("-10未満")).toBeInTheDocument();
    expect(screen.getByText("3以上")).toBeInTheDocument();
  });

  it("プレビューは親から渡された配色と単位で描く", async () => {
    const { user } = openSection({
      mapBandColors: (boundaries) => boundaries.map(() => "#111111").concat("#222222"),
      mapValueUnit: "%",
    });

    await turnOverrideOn(user);
    await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "1, 4");

    expect(screen.getByText("1%未満")).toBeInTheDocument();
    expect(screen.getByText("4%以上")).toBeInTheDocument();
  });

  it("「自動計算に戻す」でnullへ戻る", async () => {
    const { user, latest } = openSection();

    await turnOverrideOn(user);
    await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "1, 4");
    await user.click(screen.getByRole("button", { name: "自動計算に戻す" }));

    expect(latest.draft.displayThresholdsOverride).toBeNull();
  });

  it("読めない入力は親へ伝える（親はそれを見て保存を止める）", async () => {
    const onThresholdErrorChange = vi.fn();
    const { user } = openSection({ onThresholdErrorChange });

    await turnOverrideOn(user);
    await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "3, 1");

    expect(onThresholdErrorChange).toHaveBeenCalledWith(expect.any(String));
  });

  it("既存軸の値が入力欄へ初期反映される", () => {
    openSection({ editing: baseAxisDefinition({ display_thresholds_override: [1, 4] }) });

    expect(screen.getByLabelText("色分けのしきい値（まとめて入力）")).toHaveValue("1, 4");
  });

  it("地図では段にならない値を入力欄の脇に名指しする", () => {
    openSection({
      editing: baseAxisDefinition({ display_thresholds_override: [2, 4, 7, 12, 15, 20] }),
      mapBands: { droppedOnMap: [15, 20], bandsOnMap: [0, 1, 2, 3, 4] },
    });

    expect(screen.getByText("地図では効かない: 15, 20")).toBeInTheDocument();
  });

  it("地図で効かない値を含むとき、段階プレビューは地図の凡例と同じ段で出す", () => {
    // 地図は[2, 4, 7, 12]で段を作るため、凡例は5段階で最上位は「12以上」。
    openSection({
      editing: baseAxisDefinition({ display_thresholds_override: [2, 4, 7, 12, 15, 20] }),
      mapBands: { droppedOnMap: [15, 20], bandsOnMap: [0, 1, 2, 3, 4] },
    });

    expect(screen.getByText("5段階になります")).toBeInTheDocument();
    expect(screen.getByLabelText("色分けプレビュー（5段階）")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "2未満",
      "2〜4",
      "4〜7",
      "7〜12",
      "12以上",
    ]);
  });

  it("すべての値が地図で効くときは印を出さない", () => {
    openSection({
      editing: baseAxisDefinition({ display_thresholds_override: [2, 4, 7] }),
      mapBands: { droppedOnMap: [], bandsOnMap: [0, 1, 2, 3] },
    });

    expect(screen.queryByText(/地図では効かない/)).not.toBeInTheDocument();
  });
});

describe("段階の体感ラベル", () => {
  it("しきい値の上書きが無いうちは編集欄を出さない", () => {
    openSection();

    expect(screen.queryByRole("button", { name: "+ 体感ラベルを設定する" })).not.toBeInTheDocument();
  });

  it("段階数ぶんの入力欄が出て、しきい値を足すと一緒に増える", async () => {
    const { user, latest } = openSection();

    await turnOverrideOn(user);
    await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "1, 4");
    await user.click(screen.getByRole("button", { name: "+ 体感ラベルを設定する" }));

    // しきい値2つ＝3段階。
    expect(latest.draft.displayBandLabelsOverride).toHaveLength(3);

    await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), ", 7");

    expect(latest.draft.displayBandLabelsOverride).toHaveLength(4);
  });

  it("「自動計算に戻す」でしきい値と一緒にnullへ戻る", async () => {
    const { user, latest } = openSection();

    await turnOverrideOn(user);
    await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "1, 4");
    await user.click(screen.getByRole("button", { name: "+ 体感ラベルを設定する" }));
    await user.click(screen.getByRole("button", { name: "自動計算に戻す" }));

    expect(latest.draft.displayThresholdsOverride).toBeNull();
    expect(latest.draft.displayBandLabelsOverride).toBeNull();
  });

  it("既存軸の値が入力欄へ初期反映される", () => {
    openSection({
      editing: baseAxisDefinition({
        display_thresholds_override: [1, 4],
        display_band_labels_override: ["低", "中", "高"],
      }),
    });

    expect(screen.getByDisplayValue("低")).toBeInTheDocument();
    expect(screen.getByDisplayValue("高")).toBeInTheDocument();
  });

  it("地図で段がまとまるとき、プレビューの各段には地図と同じラベルが当たり、出ないラベルの欄に印が付く", () => {
    // 地図は[2, 4, 7, 12]で段を作り（15・20が落ちる）、「12以上」は下端12で始まる入力の段
    // （5番目のラベル）として残る——backendの`bands_the_map_keeps`が返す番号。
    openSection({
      editing: baseAxisDefinition({
        display_thresholds_override: [2, 4, 7, 12, 15, 20],
        display_band_labels_override: ["とても楽", "楽", "ふつう", "きつい", "とてもきつい", "限界", "限界超"],
      }),
      mapBands: { droppedOnMap: [15, 20], bandsOnMap: [0, 1, 2, 3, 4] },
    });

    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "とても楽（2未満）",
      "楽（2〜4）",
      "ふつう（4〜7）",
      "きつい（7〜12）",
      "とてもきつい（12以上）",
    ]);
    const marked = screen
      .getAllByRole("textbox", { name: /^体感ラベル/ })
      .filter((input) => input.parentElement?.textContent?.includes("地図には出ない"))
      .map((input) => (input as HTMLInputElement).value);
    expect(marked).toEqual(["限界", "限界超"]);
  });
});

describe("地図に出せない軸の注記", () => {
  const NOTE = /地図表示用のデータ取得経路が用意されていません/;

  it("編集中の軸が地図に出ないなら注記を出す", () => {
    openSection({ editing: baseAxisDefinition({ display: { ...baseAxisDefinition().display, kind: "none" } }) });

    expect(screen.getByText(NOTE)).toBeInTheDocument();
  });

  it("地図に出る軸には出さない", () => {
    openSection({
      editing: baseAxisDefinition({
        display: { ...baseAxisDefinition().display, kind: "ramp", thresholds: [1], tile_inputs: [] },
      }),
    });

    expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
  });

  it("新規作成では、まだ計算結果が無いので出さない", () => {
    openSection();

    expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
  });
});
