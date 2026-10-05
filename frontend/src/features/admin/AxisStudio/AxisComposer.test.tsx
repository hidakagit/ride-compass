/**
 * `AxisComposer.tsx`——軸を作る1画面のフォームの状態・保存前の検証・送るpayloadの組み立てと、節の組み立て。
 *
 * 節（点数の決め方・地図表示と公開）と地図の段の判定の取得は本物を通し、backendの応答（網の層）だけを与える。
 * 節へ渡したものは節の表示で、節から受けたものは保存で見る。材料は本物の一覧（生成物）を通す。
 *
 * ここで見ないもの:
 * - 軸と下書きの相互変換そのもの → `axisDraft.test.ts`
 * - 節の中の入力欄 → `AxisScoringSection.test.tsx`・`AxisMapDisplaySection.test.tsx`
 * - どのモードで開くか・保存の結果をどう扱うか → `AxisStudio.test.tsx`
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MATERIAL_CATALOG, type AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import { onSameOrigin } from "@/testing/backendServer";
import type { AxisDefinitionPayload, AxisDefinitionResponse } from "@/types/route";

import AxisComposer from "./AxisComposer";
import { emptyDraft, parseThresholdList } from "./axisDraft";

const materialOf = (dtype: AxisMaterialOption["dtype"]) => MATERIAL_CATALOG.find((m) => m.dtype === dtype)!;
const NUM = materialOf("numeric");
const CAT = materialOf("categorical");

function axis(overrides: Partial<AxisDefinitionResponse> = {}): AxisDefinitionResponse {
  return {
    axis_id: "axis_edit",
    label: "名前",
    description: "",
    weight_share_when_published: null,
    priority_overrides: [],
    icon_id: null,
    chip_label: null,
    panel_hint: null,
    display_thresholds_override: null,
    display_band_labels_override: null,
    category: "推定",
    default_weight: 0.2,
    is_published: false,
    show_map_icon: true,
    time_scope: "always",
    dedicated_way_value_layer: false,
    shape: {
      kind: "breakpoint_linear",
      terms: [{ material: NUM.id, weight: 1, required: true }],
      preprocess: "identity",
      breakpoints: [
        [0, 0],
        [10, 100],
      ],
    },
    display: { kind: "none", label: "", category: "", tile_inputs: [], thresholds: [] },
    ...overrides,
  };
}

interface ComposerProps {
  editing?: AxisDefinitionResponse | null;
  duplicateFrom?: AxisDefinitionResponse | null;
  otherAxes?: readonly AxisDefinitionResponse[];
  republishing?: boolean;
  mapBandColors?: (boundaries: readonly number[]) => readonly string[];
  mapValueUnit?: string;
}

function renderComposer(props: ComposerProps = {}) {
  const onSave = vi.fn<(payload: AxisDefinitionPayload, isNew: boolean) => Promise<void>>(async () => {});
  const onCancelEdit = vi.fn();
  const user = userEvent.setup();
  const view = render(
    <AxisComposer
      editing={null}
      duplicateFrom={null}
      otherAxes={[]}
      mapBandColors={undefined}
      mapValueUnit=""
      republishing={false}
      onSave={onSave}
      onCancelEdit={onCancelEdit}
      {...props}
    />,
  );
  return { user, onSave, onCancelEdit, ...view };
}

const submitButton = () => screen.getByRole("button", { name: /作成する|更新する|保存中/ });

const PREVIEW_DISPLAY_THRESHOLDS = "/admin/api/axis-definitions/preview-display-thresholds";
const thresholdInput = () => screen.getByRole("textbox", { name: "色分けのしきい値（まとめて入力）" });

/** 点数の節が描くと同時に取る分布・点数と、地図の段の判定（段にならない値なし）に応える。 */
beforeEach(() => {
  onSameOrigin("POST", "/admin/api/axis-definitions/preview-distribution", () =>
    Response.json({ sample_ways: 1, total_km: 1, quantiles: {}, bins: [[0, 2, 1]], zero_share: 0 }),
  );
  onSameOrigin("POST", "/admin/api/axis-definitions/preview-scores", () =>
    Response.json({ scores: [0], material_points: [] }),
  );
  onSameOrigin("POST", PREVIEW_DISPLAY_THRESHOLDS, ({ body }) => {
    const { thresholds } = body as { thresholds: number[] };
    return Response.json({ dropped_on_map: [], bands_on_map: [...thresholds, 0].map((_, i) => i) });
  });
});

describe("保存するpayload", () => {
  const payloadKeys: string[] = Object.keys(
    JSON.parse(readFileSync(join(__dirname, "../../../types/generated/openapi.json"), "utf-8")).components.schemas
      .AxisDefinitionPayload.properties,
  );

  it("既存の軸を開いて何も変えずに保存すると、backendの契約の全項目が元の軸と同じ値で届く", async () => {
    const editing = axis({
      category: "観測",
      priority_overrides: [{ material: CAT.id, equals: "x", value: 1 }],
      time_scope: "night_only",
      dedicated_way_value_layer: true,
      icon_id: "icon_a",
      chip_label: "略",
      panel_hint: "補足",
      show_map_icon: false,
      display_thresholds_override: [1, 2],
      display_band_labels_override: ["a", "b", "c"],
      description: "説明",
    });
    const defaults = emptyDraft(MATERIAL_CATALOG).passthrough;
    for (const [key, value] of Object.entries(defaults)) {
      expect(
        editing[key as keyof AxisDefinitionResponse],
        `${key}が新規の値と同じで、素通しを確かめられない`,
      ).not.toEqual(value);
    }
    const { user, onSave } = renderComposer({ editing });

    await user.click(submitButton());
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const [payload, isNew] = onSave.mock.calls[0];
    expect(isNew).toBe(false);
    expect(payloadKeys.length).toBeGreaterThan(0);
    for (const key of payloadKeys) {
      expect(payload[key as keyof AxisDefinitionPayload], key).toEqual(editing[key as keyof AxisDefinitionResponse]);
    }
  });

  it("表示名・略称・説明文は前後の空白を落とし、空の略称・説明文・アイコンは未設定（null）で送る", async () => {
    const { user, onSave } = renderComposer({
      editing: axis({ label: "  名前  ", chip_label: " 略 ", panel_hint: "   ", icon_id: "" }),
    });
    await user.click(submitButton());

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toMatchObject({ label: "名前", chip_label: "略", panel_hint: null, icon_id: null });
  });

  it("表示名・説明・既定重みを下書きへ入れて送る", async () => {
    const { user, onSave } = renderComposer({ editing: axis() });
    const label = screen.getByRole("textbox", { name: "表示名" });
    await user.clear(label);
    await user.type(label, "改名");
    await user.type(screen.getByRole("textbox", { name: "説明" }), "説明文");
    const weight = screen.getByRole("spinbutton", { name: "既定重み" });
    await user.clear(weight);
    await user.type(weight, "0.5");
    await user.click(submitButton());

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toMatchObject({ label: "改名", description: "説明文", default_weight: 0.5 });
  });
});

describe("保存前の検証", () => {
  it.each([
    ["下書きの軸", false],
    ["公開済みの軸（表示だけ編集）", true],
  ])("%sで、しきい値の入力を読めない間は、その理由で止め、読めたら送る", async (_case, isPublished) => {
    const { user, onSave } = renderComposer({
      editing: axis({ is_published: isPublished, display_thresholds_override: [1] }),
    });
    await user.type(thresholdInput(), ", x");
    const message = parseThresholdList("1, x").error!;
    await user.click(submitButton());
    // 節が入力欄の下に出す理由と、保存を止めた理由の2つ。
    expect(await screen.findAllByText(message)).toHaveLength(2);
    expect(onSave).not.toHaveBeenCalled();

    await user.clear(thresholdInput());
    await user.type(thresholdInput(), "1");
    await user.click(submitButton());
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(screen.queryByText(message)).not.toBeInTheDocument();
  });
});

describe("公開済みの軸（表示だけ編集）", () => {
  it("表示の項目しか変えられないと言い、基本の項目と点数の節を出さず、表示の節では公開を切り替えさせない", () => {
    renderComposer({ editing: axis({ is_published: true }) });
    expect(screen.getByText(/地図表示に関わる項目のみ編集できます/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "表示名" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "点数のもとになるもの" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ しきい値を自分で設定する" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "公開する" })).not.toBeInTheDocument();
  });
});

describe("保存の操作", () => {
  it("新規は「作成する」だけ、編集は「更新する」と「編集をやめる」を置き、やめると親へ伝える", async () => {
    const { unmount } = renderComposer();
    expect(screen.getByRole("button", { name: "作成する" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "編集をやめる" })).not.toBeInTheDocument();
    unmount();

    const { user, onCancelEdit } = renderComposer({ editing: axis() });
    expect(screen.getByRole("button", { name: "更新する" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "編集をやめる" }));
    expect(onCancelEdit).toHaveBeenCalled();
  });

  it("保存中は保存もやめるも押せない", async () => {
    const { user, onSave } = renderComposer({ editing: axis() });
    onSave.mockReturnValue(new Promise(() => {}));
    await user.click(submitButton());
    expect(await screen.findByRole("button", { name: "保存中..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "編集をやめる" })).toBeDisabled();
  });

  it.each([
    ["Error", new Error("軸は公開済みです"), "軸は公開済みです"],
    ["Error以外", "conflict", "conflict"],
  ])("保存が%sで失敗したら理由を出し、もう一度押せる", async (_kind, reason, message) => {
    const { user, onSave } = renderComposer({ editing: axis() });
    onSave.mockRejectedValueOnce(reason);
    await user.click(submitButton());
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更新する" })).toBeEnabled();
  });
});

describe("節へ渡すもの", () => {
  it("点数の節へは、編集中の軸自身を除いたほかの軸を、点数のもとの候補として渡す", () => {
    const self = axis({ axis_id: "axis_edit", label: "自分の軸" });
    const other = axis({ axis_id: "axis_other", label: "ほかの軸" });
    renderComposer({ editing: self, otherAxes: [self, other] });

    const group = screen
      .getByRole("combobox", { name: "点数のもとになるもの" })
      .querySelector('optgroup[label="ほかの軸"]')!;
    expect(
      within(group as HTMLElement)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual([expect.stringContaining("ほかの軸")]);
  });

  it("表示の節へは、編集中の軸・調整中か・段の配色と単位と、編集中のしきい値を問った地図の段の判定を渡す", async () => {
    onSameOrigin("POST", PREVIEW_DISPLAY_THRESHOLDS, () =>
      Response.json({ dropped_on_map: [3], bands_on_map: [0, 1] }),
    );
    const mapBandColors = (boundaries: readonly number[]) => [...boundaries, 0].map(() => "rgb(9, 9, 9)");
    renderComposer({
      editing: axis({ display_thresholds_override: [1, 3] }),
      republishing: true,
      mapBandColors,
      mapValueUnit: "km/h",
    });

    expect(screen.getByText(/地図表示用のデータ取得経路が用意されていません/)).toBeInTheDocument();
    expect(screen.getByText(/保存すると公開へ戻ります/)).toBeInTheDocument();
    expect(await screen.findByText("地図では効かない: 3")).toBeInTheDocument();
    const preview = screen.getByLabelText("色分けプレビュー（2段階）");
    expect(preview).toHaveTextContent("km/h");
    const swatches = Array.from(preview.querySelectorAll("li > span[aria-hidden]")) as HTMLElement[];
    expect(swatches.map((swatch) => swatch.style.background)).toEqual(["rgb(9, 9, 9)", "rgb(9, 9, 9)"]);
  });
});

describe("既定重みの参考表示", () => {
  it("下書きの軸には、公開するまで重みが効かないと言う", () => {
    renderComposer({ editing: axis({ is_published: false }) });
    expect(screen.getByText(/現在非公開のため/)).toBeInTheDocument();
  });

  it("公開にした軸には、backendが返した公開したときの割合を、公開軸の数（自分を含む）と一緒に出す", async () => {
    const self = axis({ axis_id: "axis_edit", is_published: false, weight_share_when_published: 0.4 });
    const others = [
      self,
      axis({ axis_id: "axis_p", is_published: true }),
      axis({ axis_id: "axis_d", is_published: false }),
    ];
    const { user } = renderComposer({ editing: self, otherAxes: others });
    await user.click(screen.getByRole("checkbox", { name: "公開する" }));

    expect(screen.getByText(/参考:/)).toHaveTextContent("（2軸）の重み合計に対して約40.0%");
  });

  it("割合が無い（重みの合計が0）なら、割合を出さない", async () => {
    const self = axis({ is_published: false, weight_share_when_published: null });
    const { user } = renderComposer({ editing: self, otherAxes: [self] });
    await user.click(screen.getByRole("checkbox", { name: "公開する" }));

    expect(screen.queryByText(/参考:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/現在非公開のため/)).not.toBeInTheDocument();
  });
});
