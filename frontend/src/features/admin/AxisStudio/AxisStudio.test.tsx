/**
 * `AxisStudio.tsx`——軸スタジオの一覧と状態: 下書き・公開済みの一覧、どのモード（新規・編集・表示だけ編集・複製・
 * 調整）でフォームを開くか、保存・削除・非公開化・調整の結果をどう扱うか。
 *
 * フォーム（`AxisComposer`）は差し替え、渡したものを見て、保存（`onSave(payload, isNew)`）とやめる（`onCancelEdit`）
 * だけを呼ばせる。管理API・軸カタログも差し替える。材料は本物の一覧（生成物）を通す。
 *
 * ここで見ないもの:
 * - フォームの中身・検証・payloadの組み立て → `AxisComposer.test.tsx`
 * - 段の配色そのもの → `lib/mapDisplay`（期待値はそこの関数から引く）
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EMPTY_CATALOG, type AxisCatalog } from "@/lib/axisCatalog";
import { MATERIAL_CATALOG } from "@/lib/axisMaterialsCatalog";
import type { RampAxis } from "@/lib/mapDisplay/axisLayers";
import type { AxisDefinitionPayload, AxisDefinitionResponse } from "@/types/route";

const api = vi.hoisted(() => ({
  listAxisDefinitions: vi.fn(),
  createAxisDefinition: vi.fn(),
  updateAxisDefinition: vi.fn(),
  deleteAxisDefinition: vi.fn(),
  unpublishAxisDefinition: vi.fn(),
}));
vi.mock("@/features/admin/adminApi", () => api);

const catalogs = vi.hoisted(() => ({
  axisCatalog: null as unknown,
}));
vi.mock("@/hooks/useAxisCatalog", () => ({ useAxisCatalog: () => catalogs.axisCatalog }));

interface ComposerProps {
  editing: AxisDefinitionResponse | null;
  duplicateFrom: AxisDefinitionResponse | null;
  otherAxes: readonly AxisDefinitionResponse[];
  mapBandColors?: (boundaries: readonly number[]) => readonly string[];
  mapValueUnit: string;
  republishing: boolean;
  onCancelEdit: () => void;
  onSave: (payload: AxisDefinitionPayload, isNew: boolean) => Promise<void>;
}
const composer = vi.hoisted(() => ({ props: null as ComposerProps | null, saveError: null as string | null }));
vi.mock("./AxisComposer", () => ({
  default: (props: ComposerProps) => {
    composer.props = props;
    const source = props.editing ?? props.duplicateFrom;
    const payload = { ...(source ?? {}), axis_id: source?.axis_id ?? "axis_new" } as AxisDefinitionPayload;
    return (
      <>
        <button
          type="button"
          onClick={() => {
            props.onSave(payload, props.editing === null).catch((error: Error) => (composer.saveError = error.message));
          }}
        >
          フォームで保存
        </button>
        <button type="button" onClick={props.onCancelEdit}>
          フォームでやめる
        </button>
      </>
    );
  },
}));

import AxisStudio from "./AxisStudio";

function axis(overrides: Partial<AxisDefinitionResponse> = {}): AxisDefinitionResponse {
  return {
    axis_id: "axis_a",
    label: "軸A",
    description: "",
    weight_share_when_published: null,
    category: "推定",
    default_weight: 0.25,
    is_published: false,
    show_map_icon: true,
    time_scope: "always",
    dedicated_way_value_layer: false,
    dynamic_way_value_needs_time: false,
    dynamic_way_value_needs_bearing: false,
    dynamic_way_value_needs_speed: false,
    shape: { kind: "breakpoint_linear", terms: [], preprocess: "identity", breakpoints: [] },
    display: { kind: "none", label: "", category: "" },
    ...overrides,
  };
}

function termsOf(...materials: string[]): AxisDefinitionResponse["shape"] {
  return {
    kind: "breakpoint_linear",
    terms: materials.map((material) => ({ material, weight: 1, required: true })),
    preprocess: "identity",
    breakpoints: [],
  };
}

const DRAFT = axis({ axis_id: "axis_draft", label: "下書きの軸" });
const PUBLISHED = axis({ axis_id: "axis_pub", label: "公開の軸", is_published: true });
const PUBLISHED_2 = axis({ axis_id: "axis_pub2", label: "公開の軸2", is_published: true });

/** backendの一覧。下書きへ戻すと、次に取る一覧でその軸が下書きになる。 */
let server: AxisDefinitionResponse[] = [];

function axisCatalog(overrides: Partial<AxisCatalog> = {}): AxisCatalog {
  return { ...EMPTY_CATALOG, ...overrides };
}

function rampAxis(axisId: string): RampAxis {
  return { axisId, label: "", category: "", tileInputs: [], thresholds: [], unit: "" };
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  server = [DRAFT, PUBLISHED, PUBLISHED_2];
  api.listAxisDefinitions.mockImplementation(async () => server);
  api.createAxisDefinition.mockResolvedValue(undefined);
  api.updateAxisDefinition.mockResolvedValue(undefined);
  api.deleteAxisDefinition.mockResolvedValue(undefined);
  api.unpublishAxisDefinition.mockImplementation(async (axisId: string) => {
    server = server.map((a) => (a.axis_id === axisId ? { ...a, is_published: false } : a));
  });
  catalogs.axisCatalog = axisCatalog();
  composer.props = null;
  composer.saveError = null;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function renderStudio() {
  const user = userEvent.setup();
  render(<AxisStudio />);
  await waitFor(() => expect(api.listAxisDefinitions).toHaveBeenCalledTimes(1));
  return user;
}

function rowOf(label: string): HTMLElement {
  return screen.getByText(label).closest("div.flex-wrap") as HTMLElement;
}

async function openPublishedTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("tab", { name: /公開済み/ }));
}

describe("一覧", () => {
  it("開くと一覧を取り、下書きのタブを既定で開き、タブに件数を出す", async () => {
    await renderStudio();
    expect(await screen.findByRole("tab", { name: "下書き（1）", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "公開済み（2）" })).toBeInTheDocument();
    expect(screen.getByText("下書きの軸")).toBeInTheDocument();
  });

  it("一覧を取れなければ、理由を出す", async () => {
    api.listAxisDefinitions.mockRejectedValue(new Error("リクエストに失敗しました"));
    await renderStudio();
    expect(await screen.findByText("リクエストに失敗しました")).toBeInTheDocument();
  });

  it("どちらのタブも、軸が無ければそう言う", async () => {
    api.listAxisDefinitions.mockResolvedValue([]);
    const user = await renderStudio();
    expect(await screen.findByText("下書きの軸はありません。")).toBeInTheDocument();
    await openPublishedTab(user);
    expect(screen.getByText("公開済みの軸はありません。")).toBeInTheDocument();
  });

  it("行には分類・既定重み（小数2桁）・使うものを出し、使うものは軸なら軸の名前、材料なら材料の名前、どちらでもなければidで出す", async () => {
    const material = MATERIAL_CATALOG[0];
    api.listAxisDefinitions.mockResolvedValue([
      axis({ axis_id: "axis_ref", label: "参照する軸", shape: termsOf("axis_base", material.id, "unknown_id") }),
      axis({ axis_id: "axis_base", label: "土台の軸" }),
    ]);
    await renderStudio();

    const summary = `推定 ・ 重み0.25 ・ 土台の軸・${material.label}・unknown_id`;
    expect(await screen.findByText(new RegExp(summary.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBeInTheDocument();
  });
});

describe("フォームを開くモード", () => {
  it("新しい軸を作るときは、新規のフォームを開く", async () => {
    const user = await renderStudio();
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));
    expect(screen.getByRole("dialog", { name: "新しい軸を作る" })).toBeInTheDocument();
    expect(composer.props).toMatchObject({ editing: null, duplicateFrom: null, republishing: false });
  });

  it("下書きの軸の編集は、その軸の編集として開き、ほかの軸には一覧の全部を渡す", async () => {
    const user = await renderStudio();
    await screen.findByText("下書きの軸");
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "編集" }));

    expect(screen.getByRole("dialog", { name: "軸を編集: 下書きの軸" })).toBeInTheDocument();
    expect(composer.props).toMatchObject({ editing: DRAFT, duplicateFrom: null, republishing: false });
    expect(composer.props!.otherAxes).toEqual([DRAFT, PUBLISHED, PUBLISHED_2]);
  });

  it("公開済みの軸の「表示だけ編集」は、表示の項目の編集として開く", async () => {
    const user = await renderStudio();
    await openPublishedTab(user);
    await user.click(within(rowOf("公開の軸")).getByRole("button", { name: "表示だけ編集" }));

    expect(screen.getByRole("dialog", { name: "表示専用フィールドを編集: 公開の軸" })).toBeInTheDocument();
    expect(composer.props).toMatchObject({ editing: PUBLISHED, republishing: false });
  });

  it.each([
    ["下書き", "下書きの軸", DRAFT],
    ["公開済み", "公開の軸", PUBLISHED],
  ])("%sの軸の複製は、その軸を元にした新規のフォームとして開く", async (tab, label, source) => {
    const user = await renderStudio();
    if (tab === "公開済み") await openPublishedTab(user);
    await user.click(within(await waitFor(() => rowOf(label))).getByRole("button", { name: "複製して新規作成" }));

    expect(screen.getByRole("dialog", { name: `「${label}」を複製して新しい軸を作る` })).toBeInTheDocument();
    expect(composer.props).toMatchObject({ editing: null, duplicateFrom: source });
  });
});

describe("保存", () => {
  it("新規の保存は作成し、一覧を取り直して閉じる", async () => {
    const user = await renderStudio();
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));
    await user.click(screen.getByRole("button", { name: "フォームで保存" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.createAxisDefinition).toHaveBeenCalledWith(expect.objectContaining({ axis_id: "axis_new" }));
    expect(api.listAxisDefinitions).toHaveBeenCalledTimes(2);
  });

  it("編集の保存は、その軸を送られたとおりに更新し、一覧を取り直して閉じる", async () => {
    const user = await renderStudio();
    await screen.findByText("下書きの軸");
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "編集" }));
    await user.click(screen.getByRole("button", { name: "フォームで保存" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.updateAxisDefinition).toHaveBeenCalledWith(
      DRAFT.axis_id,
      expect.objectContaining({ is_published: false }),
    );
    expect(api.listAxisDefinitions).toHaveBeenCalledTimes(2);
  });

  it("保存に失敗したら、フォームへ失敗を返し、開いたままにする", async () => {
    api.updateAxisDefinition.mockRejectedValue(new Error("軸は公開済みです"));
    const user = await renderStudio();
    await screen.findByText("下書きの軸");
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "編集" }));
    await user.click(screen.getByRole("button", { name: "フォームで保存" }));

    await waitFor(() => expect(composer.saveError).toBe("軸は公開済みです"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("フォームでやめると閉じる", async () => {
    const user = await renderStudio();
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));
    await user.click(screen.getByRole("button", { name: "フォームでやめる" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("公開済みの軸を「調整する」", () => {
  async function adjust(user: ReturnType<typeof userEvent.setup>) {
    await openPublishedTab(user);
    await user.click(within(rowOf("公開の軸")).getByRole("button", { name: "調整する" }));
  }

  it("下書きへ戻して一覧を取り直し、その軸を調整中として編集で開く", async () => {
    const user = await renderStudio();
    await adjust(user);

    await waitFor(() => expect(composer.props?.republishing).toBe(true));
    expect(api.unpublishAxisDefinition).toHaveBeenCalledWith(PUBLISHED.axis_id);
    expect(api.listAxisDefinitions).toHaveBeenCalledTimes(2);
    expect(composer.props!.editing).toEqual({ ...PUBLISHED, is_published: false });
    expect(screen.getByRole("dialog", { name: "軸を編集: 公開の軸" })).toBeInTheDocument();
  });

  it("保存すると公開へ戻して更新し、下書きのままだとは言わない", async () => {
    const user = await renderStudio();
    await adjust(user);
    await waitFor(() => expect(composer.props?.republishing).toBe(true));
    await user.click(screen.getByRole("button", { name: "フォームで保存" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.updateAxisDefinition).toHaveBeenCalledWith(
      PUBLISHED.axis_id,
      expect.objectContaining({ is_published: true }),
    );
    expect(screen.queryByText(/下書きへ戻したまま編集を終えました/)).not.toBeInTheDocument();
  });

  it.each([
    [
      "フォームでやめる",
      async (user: ReturnType<typeof userEvent.setup>) =>
        user.click(screen.getByRole("button", { name: "フォームでやめる" })),
    ],
    ["Escapeで閉じる", async (user: ReturnType<typeof userEvent.setup>) => user.keyboard("{Escape}")],
  ])("保存せずに%sと、下書きのまま残ったことを知らせ、次に調整を始めると消す", async (_how, close) => {
    const user = await renderStudio();
    await adjust(user);
    await waitFor(() => expect(composer.props?.republishing).toBe(true));
    await close(user);

    expect(await screen.findByText(/下書きへ戻したまま編集を終えました/)).toBeInTheDocument();
    await user.click(within(rowOf("公開の軸2")).getByRole("button", { name: "調整する" }));
    await waitFor(() => expect(screen.queryByText(/下書きへ戻したまま編集を終えました/)).not.toBeInTheDocument());
  });

  it("下書きへ戻せなければ、理由を出してフォームを開かない", async () => {
    api.unpublishAxisDefinition.mockRejectedValue(new Error("戻せません"));
    const user = await renderStudio();
    await adjust(user);

    expect(await screen.findByText("戻せません")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("ふつうの編集をやめても、下書きのまま残ったとは言わない", async () => {
    const user = await renderStudio();
    await screen.findByText("下書きの軸");
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "編集" }));
    await user.click(screen.getByRole("button", { name: "フォームでやめる" }));
    expect(screen.queryByText(/下書きへ戻したまま編集を終えました/)).not.toBeInTheDocument();
  });
});

describe("非公開に戻す", () => {
  it("下書きへ戻して一覧を取り直す。戻せなければ理由を出す", async () => {
    const user = await renderStudio();
    await openPublishedTab(user);
    await user.click(within(rowOf("公開の軸")).getByRole("button", { name: "非公開に戻す" }));
    await waitFor(() => expect(api.listAxisDefinitions).toHaveBeenCalledTimes(2));
    expect(api.unpublishAxisDefinition).toHaveBeenCalledWith(PUBLISHED.axis_id);

    expect(screen.queryByText("公開の軸")).not.toBeInTheDocument();

    api.unpublishAxisDefinition.mockRejectedValueOnce(new Error("戻せません"));
    await user.click(within(rowOf("公開の軸2")).getByRole("button", { name: "非公開に戻す" }));
    expect(await screen.findByText("戻せません")).toBeInTheDocument();
  });

  it("戻している間は、その軸の「非公開に戻す」と「調整する」を押せない", async () => {
    api.unpublishAxisDefinition.mockReturnValue(new Promise(() => {}));
    const user = await renderStudio();
    await openPublishedTab(user);
    await user.click(within(rowOf("公開の軸")).getByRole("button", { name: "非公開に戻す" }));

    expect(within(rowOf("公開の軸")).getByRole("button", { name: "非公開に戻す" })).toBeDisabled();
    expect(within(rowOf("公開の軸")).getByRole("button", { name: "調整する" })).toBeDisabled();
  });

  it("公開済みの軸には削除の口を置かない（先に非公開へ戻す）", async () => {
    const user = await renderStudio();
    await openPublishedTab(user);
    expect(within(rowOf("公開の軸")).queryByRole("button", { name: "削除" })).not.toBeInTheDocument();
  });
});

describe("削除", () => {
  it("ほかの軸から参照されていなければ、確かめずに削除して一覧を取り直す", async () => {
    const confirm = vi.fn();
    vi.stubGlobal("confirm", confirm);
    const user = await renderStudio();
    await screen.findByText("下書きの軸");
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "削除" }));

    await waitFor(() => expect(api.listAxisDefinitions).toHaveBeenCalledTimes(2));
    expect(api.deleteAxisDefinition).toHaveBeenCalledWith(DRAFT.axis_id);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("ほかの軸から材料として参照されていれば、参照元の名前を出して確かめ、やめれば削除しない", async () => {
    api.listAxisDefinitions.mockResolvedValue([
      DRAFT,
      axis({ axis_id: "axis_user1", label: "使う軸1", shape: termsOf(DRAFT.axis_id) }),
      axis({
        axis_id: "axis_user2",
        label: "使う軸2",
        shape: { kind: "categorical", material: DRAFT.axis_id, mapping: {} },
      }),
    ]);
    const confirm = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true);
    vi.stubGlobal("confirm", confirm);
    const user = await renderStudio();
    await screen.findByText("下書きの軸");

    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "削除" }));
    expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining("使う軸1・使う軸2"));
    expect(api.deleteAxisDefinition).not.toHaveBeenCalled();

    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "削除" }));
    await waitFor(() => expect(api.deleteAxisDefinition).toHaveBeenCalledWith(DRAFT.axis_id));
  });

  it("最後の1軸は削除できない", async () => {
    api.listAxisDefinitions.mockResolvedValue([DRAFT]);
    await renderStudio();
    const button = within(await waitFor(() => rowOf("下書きの軸"))).getByRole("button", { name: "削除" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "最後の1軸は削除できません");
  });

  it("削除している間はその軸の削除を押せず、失敗したら理由を出す", async () => {
    let fail!: (reason: unknown) => void;
    api.deleteAxisDefinition.mockReturnValue(new Promise((_resolve, reject) => (fail = reject)));
    const user = await renderStudio();
    await screen.findByText("下書きの軸");
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "削除" }));
    expect(within(rowOf("下書きの軸")).getByRole("button", { name: "削除" })).toBeDisabled();

    fail(new Error("削除できません"));
    expect(await screen.findByText("削除できません")).toBeInTheDocument();
    expect(within(rowOf("下書きの軸")).getByRole("button", { name: "削除" })).toBeEnabled();
  });
});

describe("Error以外の失敗", () => {
  it("一覧を取れないとき", async () => {
    api.listAxisDefinitions.mockRejectedValue("offline");
    await renderStudio();
    expect(await screen.findByText("offline")).toBeInTheDocument();
  });

  it.each([
    ["調整する", "unpublishAxisDefinition", "公開の軸"],
    ["非公開に戻す", "unpublishAxisDefinition", "公開の軸"],
  ] as const)("「%s」が失敗したとき", async (button, method, label) => {
    api[method].mockRejectedValue("conflict");
    const user = await renderStudio();
    await openPublishedTab(user);
    await user.click(within(rowOf(label)).getByRole("button", { name: button }));
    expect(await screen.findByText("conflict")).toBeInTheDocument();
  });

  it("削除が失敗したとき", async () => {
    api.deleteAxisDefinition.mockRejectedValue("conflict");
    const user = await renderStudio();
    await screen.findByText("下書きの軸");
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "削除" }));
    expect(await screen.findByText("conflict")).toBeInTheDocument();
  });
});

describe("段階プレビューの配色", () => {
  async function openEdit() {
    const user = await renderStudio();
    await screen.findByText("下書きの軸");
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "編集" }));
  }

  it("地図に出る経路がまだ無い軸には、配色を渡さない（単位も空）", async () => {
    await openEdit();
    expect(composer.props!.mapBandColors).toBeUndefined();
    expect(composer.props!.mapValueUnit).toBe("");
  });

  it("複製のときは、複製元の軸の配色を使う", async () => {
    catalogs.axisCatalog = axisCatalog({ rampAxes: [rampAxis(DRAFT.axis_id)] });
    const user = await renderStudio();
    await screen.findByText("下書きの軸");
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "複製して新規作成" }));
    expect(composer.props!.mapBandColors).toBeDefined();
  });
});
