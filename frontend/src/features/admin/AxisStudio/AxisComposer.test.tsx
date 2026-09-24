/**
 * `AxisComposer.tsx`——軸を作る1画面のフォームの状態・保存前の検証・送るpayloadの組み立てと、節の組み立て。
 *
 * 節（点数の決め方・地図表示と公開）は差し替え、この画面が節へ何を渡し、節から何を受けるかだけを見る。
 * 検証に掛ける状態は、節を操作せずに編集対象の軸（`editing`）で与える。材料カタログ（実行時に取得する）と
 * 地図の段の判定の取得も差し替える。
 *
 * ここで見ないもの:
 * - 軸と下書きの相互変換そのもの → `axisDraft.test.ts`
 * - 節の中の入力欄 → `AxisScoringSection.test.tsx`・`AxisMapDisplaySection.test.tsx`
 * - どのモードで開くか・保存の結果をどう扱うか → `AxisStudio.test.tsx`
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import type { AxisDefinitionPayload, AxisDefinitionResponse } from "@/types/route";

import { emptyDraft, type Draft } from "./axisDraft";

const catalog = vi.hoisted(() => ({ materials: [] as AxisMaterialOption[], loaded: true }));
vi.mock("@/hooks/useMaterialCatalog", () => ({ useMaterialCatalog: () => catalog }));

const bands = vi.hoisted(() => ({
  requests: [] as unknown[],
  result: { droppedOnMap: [], bandsOnMap: null } as unknown,
}));
vi.mock("@/features/admin/useMapBandsOfThresholds", () => ({
  useMapBandsOfThresholds: (request: unknown) => {
    bands.requests.push(request);
    return bands.result;
  },
}));

type Props = Record<string, unknown> & { draft: Draft; setDraft: (update: (d: Draft) => Draft) => void };
const sections = vi.hoisted(() => ({ scoring: null as Props | null, display: null as Props | null }));
vi.mock("./AxisScoringSection", () => ({
  AxisScoringSection: (props: Props) => {
    sections.scoring = props;
    return (
      <>
        <button type="button" onClick={() => props.setDraft((d) => ({ ...d }))}>
          点数の節で触る
        </button>
        <button
          type="button"
          onClick={() => props.setDraft((d) => ({ ...d, categoricalRows: [{ value: "  ", score: 0 }] }))}
        >
          値の行を空欄で足す
        </button>
      </>
    );
  },
}));
vi.mock("./AxisMapDisplaySection", () => ({
  AxisMapDisplaySection: (props: Props & { onThresholdErrorChange: (error: string | null) => void }) => {
    sections.display = props;
    return (
      <>
        <button type="button" onClick={() => props.onThresholdErrorChange("しきい値を読めません")}>
          しきい値の誤りを伝える
        </button>
        <button type="button" onClick={() => props.onThresholdErrorChange(null)}>
          しきい値の誤りなしを伝える
        </button>
        <button type="button" onClick={() => props.setDraft((d) => ({ ...d, isPublished: true }))}>
          公開にする
        </button>
      </>
    );
  },
}));

import AxisComposer from "./AxisComposer";

function material(id: string, dtype: AxisMaterialOption["dtype"]): AxisMaterialOption {
  return { id, label: id, name: id, description: "", dtype, unit: "" };
}
const NUM = material("num_a", "numeric");
const BOOL = material("bool_a", "boolean");
const CAT = material("cat_a", "categorical");
const MATERIALS = [NUM, BOOL, CAT];

function axis(overrides: Partial<AxisDefinitionResponse> = {}): AxisDefinitionResponse {
  return {
    axis_id: "axis_edit",
    label: "名前",
    description: "",
    weight_share_when_published: null,
    category: "推定",
    default_weight: 0.2,
    is_published: false,
    show_map_icon: true,
    time_scope: "always",
    dedicated_way_value_layer: false,
    dynamic_way_value_needs_time: false,
    dynamic_way_value_needs_bearing: false,
    dynamic_way_value_needs_speed: false,
    shape: {
      kind: "breakpoint_linear",
      terms: [{ material: NUM.id, weight: 1, required: true }],
      preprocess: "identity",
      breakpoints: [
        [0, 0],
        [10, 100],
      ],
    },
    display: { kind: "none", label: "", category: "" },
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
    <AxisComposer editing={null} duplicateFrom={null} onSave={onSave} onCancelEdit={onCancelEdit} {...props} />,
  );
  return { user, onSave, onCancelEdit, ...view };
}

const submitButton = () => screen.getByRole("button", { name: /作成する|更新する|保存中/ });

beforeEach(() => {
  catalog.materials = MATERIALS;
  catalog.loaded = true;
  bands.requests = [];
  bands.result = { droppedOnMap: [], bandsOnMap: null };
  sections.scoring = null;
  sections.display = null;
});

describe("材料カタログ", () => {
  it("読み込み中は、フォームを出さずに読み込み中と言う", () => {
    catalog.loaded = false;
    catalog.materials = [];
    renderComposer();
    expect(screen.getByText(/材料カタログを読み込んでいます/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "作成する" })).not.toBeInTheDocument();
  });

  it("読み込んだが0件なら、フォームを出さずに理由と閉じる口だけを出す", async () => {
    catalog.materials = [];
    const { user, onCancelEdit } = renderComposer();
    expect(screen.getByText(/材料カタログを取得できませんでした/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "作成する" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "閉じる" }));
    expect(onCancelEdit).toHaveBeenCalled();
  });

  it("カタログが後から入れ替わったら、まだ触っていない下書きを作り直す", () => {
    catalog.materials = [BOOL];
    const editing = axis();
    const { rerender, onSave, onCancelEdit } = renderComposer({ editing });
    expect(sections.scoring!.draft.shapeKind).toBe("recipe_then_breakpoint_linear");

    catalog.materials = MATERIALS;
    rerender(<AxisComposer editing={editing} duplicateFrom={null} onSave={onSave} onCancelEdit={onCancelEdit} />);
    expect(sections.scoring!.draft.shapeKind).toBe("breakpoint_linear");
  });

  it("触った後にカタログが入れ替わっても、下書きは作り直さない", async () => {
    catalog.materials = [BOOL];
    const editing = axis();
    const { rerender, onSave, onCancelEdit, user } = renderComposer({ editing });
    await user.click(screen.getByRole("button", { name: "点数の節で触る" }));

    catalog.materials = MATERIALS;
    rerender(<AxisComposer editing={editing} duplicateFrom={null} onSave={onSave} onCancelEdit={onCancelEdit} />);
    expect(sections.scoring!.draft.shapeKind).toBe("recipe_then_breakpoint_linear");
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
      dynamic_way_value_needs_time: true,
      dynamic_way_value_needs_bearing: true,
      dynamic_way_value_needs_speed: true,
      icon_id: "icon_a",
      chip_label: "略",
      panel_hint: "補足",
      show_map_icon: false,
      display_thresholds_override: [1, 2],
      display_band_labels_override: ["a", "b", "c"],
      description: "説明",
    });
    const defaults = emptyDraft(MATERIALS).passthrough;
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
  it("地図表示の節が、しきい値の入力を読めないと伝えている間は、その理由で止め、読めたら送る", async () => {
    const { user, onSave } = renderComposer({ editing: axis({ display_thresholds_override: [1] }) });
    await user.click(screen.getByRole("button", { name: "しきい値の誤りを伝える" }));
    await user.click(submitButton());
    expect(await screen.findByText("しきい値を読めません")).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "しきい値の誤りなしを伝える" }));
    await user.click(submitButton());
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(screen.queryByText("しきい値を読めません")).not.toBeInTheDocument();
  });
});

describe("公開済みの軸（表示だけ編集）", () => {
  it("表示の項目しか変えられないと言い、基本の項目と点数の節を出さず、表示の節へ制限を伝える", () => {
    renderComposer({ editing: axis({ is_published: true }) });
    expect(screen.getByText(/地図表示に関わる項目のみ編集できます/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "表示名" })).not.toBeInTheDocument();
    expect(sections.scoring).toBeNull();
    expect(sections.display!.restrictedDisplayOnly).toBe(true);
  });

  it("描いていない節は検証せず、表示の節の入力の読み取りの誤りだけで止める", async () => {
    const first = await (async () => {
      const { user, onSave, unmount } = renderComposer({ editing: axis({ is_published: true, label: "" }) });
      await user.click(submitButton());
      await waitFor(() => expect(onSave).toHaveBeenCalled());
      return unmount;
    })();
    first();

    const { user, onSave } = renderComposer({
      editing: axis({ is_published: true, display_thresholds_override: [1] }),
    });
    await user.click(screen.getByRole("button", { name: "しきい値の誤りを伝える" }));
    await user.click(submitButton());
    expect(await screen.findByText("しきい値を読めません")).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
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
  it("点数の節へは、材料と、編集中の軸自身を除いたほかの軸（点数の材料として）を渡す", () => {
    const self = axis({ axis_id: "axis_edit" });
    const other = axis({ axis_id: "axis_other", label: "ほかの軸", description: "ほかの説明" });
    renderComposer({ editing: self, otherAxes: [self, other] });

    expect(sections.scoring!.materialOptions).toEqual(MATERIALS);
    expect(sections.scoring!.axisTermOptions).toEqual([
      { id: "axis_other", label: "ほかの軸", name: "ほかの軸", description: "ほかの説明", dtype: "numeric", unit: "" },
    ]);
  });

  it("表示の節へは、編集中の軸・調整中か・段の配色と単位・地図の段の判定を渡す", () => {
    const editing = axis();
    const mapBandColors = () => [];
    bands.result = { droppedOnMap: [3], bandsOnMap: [0] };
    renderComposer({ editing, republishing: true, mapBandColors, mapValueUnit: "km/h" });

    expect(sections.display).toMatchObject({
      editing,
      republishing: true,
      restrictedDisplayOnly: false,
      mapBandColors,
      mapValueUnit: "km/h",
      mapBands: { droppedOnMap: [3], bandsOnMap: [0] },
    });
  });

  it.each([
    ["上書きしていない", axis({ display_thresholds_override: null })],
    ["上書きが空", axis({ display_thresholds_override: [] })],
  ])("しきい値を%sときは、地図の段を問わない", (_case, editing) => {
    renderComposer({ editing });
    expect(bands.requests.at(-1)).toBeNull();
  });
});

describe("既定重みの参考表示", () => {
  it("ほかの軸を渡されていなければ、出さない", () => {
    renderComposer({ editing: axis({ is_published: false }) });
    expect(screen.queryByText(/参考:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/現在非公開のため/)).not.toBeInTheDocument();
  });

  it("下書きの軸には、公開するまで重みが効かないと言う", () => {
    renderComposer({ editing: axis({ is_published: false }), otherAxes: [] });
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
    await user.click(screen.getByRole("button", { name: "公開にする" }));

    expect(screen.getByText(/参考:/)).toHaveTextContent("（2軸）の重み合計に対して約40.0%");
  });

  it("割合が無い（重みの合計が0）なら、割合を出さない", async () => {
    const self = axis({ is_published: false, weight_share_when_published: null });
    const { user } = renderComposer({ editing: self, otherAxes: [self] });
    await user.click(screen.getByRole("button", { name: "公開にする" }));

    expect(screen.queryByText(/参考:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/現在非公開のため/)).not.toBeInTheDocument();
  });
});
