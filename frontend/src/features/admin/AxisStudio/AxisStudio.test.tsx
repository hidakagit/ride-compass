/**
 * `AxisStudio.tsx`——軸スタジオの一覧と状態: 下書き・公開済みの一覧、どのモード（新規・編集・表示だけ編集・複製・
 * 調整）でフォームを開くか、保存・削除・非公開化・調整の結果をどう扱うか。
 *
 * フォーム（`AxisComposer`）は差し替え、渡したものを見て、保存（`onSave(payload, isNew)`）とやめる（`onCancelEdit`）
 * だけを呼ばせる。管理APIと軸カタログは網の層で応え、軸の定義は書いた結果が次に取る一覧へ出る代役にする。
 * 材料は本物の一覧（生成物）を通す。
 *
 * ここで見ないもの:
 * - フォームの中身・検証・payloadの組み立て → `AxisComposer.test.tsx`
 * - 段の配色そのもの → `lib/mapDisplay`（期待値はそこの関数から引く）
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MATERIAL_CATALOG } from "@/lib/axisMaterialsCatalog";
import { heldReplies, onSameOrigin, type SentRequest } from "@/testing/backendServer";
import { catalogResponse, rampEntry, serveAxisCatalog } from "@/testing/catalogAxes";
import type { AxisCatalogEntry, AxisDefinitionPayload, AxisDefinitionResponse } from "@/types/route";

interface ComposerProps {
  editing: AxisDefinitionResponse | null;
  duplicateFrom: AxisDefinitionResponse | null;
  otherAxes: readonly AxisDefinitionResponse[];
  mapBandColors: ((boundaries: readonly number[]) => readonly string[]) | undefined;
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
    priority_overrides: [],
    icon_id: null,
    chip_label: null,
    panel_hint: null,
    display_thresholds_override: null,
    display_band_labels_override: null,
    category: "推定",
    default_weight: 0.25,
    is_published: false,
    show_map_icon: true,
    time_scope: "always",
    dedicated_way_value_layer: false,
    shape: { kind: "breakpoint_linear", terms: [], preprocess: "identity", breakpoints: [] },
    display: { kind: "none", label: "", category: "", tile_inputs: [], thresholds: [] },
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

const DEFINITIONS = "/admin/api/axis-definitions";
const DEFINITION = `${DEFINITIONS}/:axisId`;
const UNPUBLISH = `${DEFINITION}/unpublish`;

const failure = (detail: string) => Response.json({ detail }, { status: 409 });
const idOf = ({ path }: SentRequest) => path.split("/")[4];

/** 管理APIの軸の定義の代役。作成・更新・削除・下書きへ戻すの結果は、次に取る一覧へ出る。書いた要求を返す。 */
function serveAxisDefinitions(initial: AxisDefinitionResponse[]) {
  let axes = [...initial];
  onSameOrigin("GET", DEFINITIONS, () => Response.json(axes));
  return {
    created: onSameOrigin("POST", DEFINITIONS, ({ body }) => {
      const created = { ...axis(), ...(body as AxisDefinitionPayload) } as AxisDefinitionResponse;
      axes = [...axes, created];
      return Response.json(created, { status: 201 });
    }),
    updated: onSameOrigin("PUT", DEFINITION, (request) => {
      const updated = request.body as AxisDefinitionResponse;
      axes = axes.map((a) => (a.axis_id === idOf(request) ? updated : a));
      return Response.json(updated);
    }),
    deleted: onSameOrigin("DELETE", DEFINITION, (request) => {
      axes = axes.filter((a) => a.axis_id !== idOf(request));
      return new Response(null, { status: 204 });
    }),
    unpublished: onSameOrigin("POST", UNPUBLISH, (request) => {
      axes = axes.map((a) => (a.axis_id === idOf(request) ? { ...a, is_published: false } : a));
      return Response.json(axes.find((a) => a.axis_id === idOf(request)));
    }),
  };
}

let writes: ReturnType<typeof serveAxisDefinitions>;
/** 軸カタログの応答の軸。 */
let catalogAxes: AxisCatalogEntry[] = [];

beforeEach(() => {
  writes = serveAxisDefinitions([DRAFT, PUBLISHED, PUBLISHED_2]);
  catalogAxes = [];
  composer.props = null;
  composer.saveError = null;
});

/** 描いて、既定の一覧が届くまで待つ（`loaded: false`なら待たない。一覧を差し替えたテスト用）。 */
async function renderStudio({ loaded = true } = {}) {
  serveAxisCatalog(catalogResponse(catalogAxes));
  const user = userEvent.setup();
  render(<AxisStudio />);
  if (loaded) await screen.findByRole("tab", { name: "公開済み（2）" });
  return user;
}

const sentIds = (sent: SentRequest[]) => sent.map(idOf);

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
    onSameOrigin("GET", DEFINITIONS, () => failure("リクエストに失敗しました"));
    await renderStudio({ loaded: false });
    expect(await screen.findByText("リクエストに失敗しました")).toBeInTheDocument();
  });

  it("どちらのタブも、軸が無ければそう言う", async () => {
    serveAxisDefinitions([]);
    const user = await renderStudio({ loaded: false });
    expect(await screen.findByText("下書きの軸はありません。")).toBeInTheDocument();
    await openPublishedTab(user);
    expect(screen.getByText("公開済みの軸はありません。")).toBeInTheDocument();
  });

  it("行には分類・既定重み（小数2桁）・使うものを出し、使うものは軸なら軸の名前、材料なら材料の名前、どちらでもなければidで出す", async () => {
    const material = MATERIAL_CATALOG[0];
    serveAxisDefinitions([
      axis({ axis_id: "axis_ref", label: "参照する軸", shape: termsOf("axis_base", material.id, "unknown_id") }),
      axis({ axis_id: "axis_base", label: "土台の軸" }),
    ]);
    await renderStudio({ loaded: false });

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
    expect(writes.created.map(({ body }) => body)).toEqual([expect.objectContaining({ axis_id: "axis_new" })]);
    expect(screen.getByRole("tab", { name: "下書き（2）" })).toBeInTheDocument();
  });

  it("編集の保存は、その軸を送られたとおりに更新して閉じる", async () => {
    const user = await renderStudio();
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "編集" }));
    await user.click(screen.getByRole("button", { name: "フォームで保存" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(writes.updated.map((request) => [idOf(request), request.body])).toEqual([
      [DRAFT.axis_id, expect.objectContaining({ is_published: false })],
    ]);
  });

  it("保存に失敗したら、フォームへ失敗を返し、開いたままにする", async () => {
    onSameOrigin("PUT", DEFINITION, () => failure("軸は公開済みです"));
    const user = await renderStudio();
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
    expect(sentIds(writes.unpublished)).toEqual([PUBLISHED.axis_id]);
    expect(composer.props!.editing).toEqual({ ...PUBLISHED, is_published: false });
    expect(screen.getByRole("dialog", { name: "軸を編集: 公開の軸" })).toBeInTheDocument();
  });

  it("保存すると公開へ戻して更新し、下書きのままだとは言わない", async () => {
    const user = await renderStudio();
    await adjust(user);
    await waitFor(() => expect(composer.props?.republishing).toBe(true));
    await user.click(screen.getByRole("button", { name: "フォームで保存" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(writes.updated.map((request) => [idOf(request), request.body])).toEqual([
      [PUBLISHED.axis_id, expect.objectContaining({ is_published: true })],
    ]);
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
    onSameOrigin("POST", UNPUBLISH, () => failure("戻せません"));
    const user = await renderStudio();
    await adjust(user);

    expect(await screen.findByText("戻せません")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("ふつうの編集をやめても、下書きのまま残ったとは言わない", async () => {
    const user = await renderStudio();
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
    await waitFor(() => expect(screen.queryByText("公開の軸")).not.toBeInTheDocument());
    expect(sentIds(writes.unpublished)).toEqual([PUBLISHED.axis_id]);

    onSameOrigin("POST", UNPUBLISH, () => failure("戻せません"));
    await user.click(within(rowOf("公開の軸2")).getByRole("button", { name: "非公開に戻す" }));
    expect(await screen.findByText("戻せません")).toBeInTheDocument();
  });

  it("戻している間は、その軸の「非公開に戻す」と「調整する」を押せない", async () => {
    onSameOrigin("POST", UNPUBLISH, heldReplies().reply);
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

async function deleteDraft(user: ReturnType<typeof userEvent.setup>) {
  await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "削除" }));
  const dialog = screen.getByRole("dialog", { name: "「下書きの軸」を削除します" });
  await user.click(within(dialog).getByRole("button", { name: "削除する" }));
}

describe("削除", () => {
  it("確認で「削除する」を押すと消して一覧を取り直す", async () => {
    const user = await renderStudio();
    await deleteDraft(user);

    await waitFor(() => expect(screen.queryByText("下書きの軸")).not.toBeInTheDocument());
    expect(sentIds(writes.deleted)).toEqual([DRAFT.axis_id]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("確認を取り消すと消さない", async () => {
    const user = await renderStudio();
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "削除" }));
    await user.click(screen.getByRole("button", { name: "キャンセル" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(writes.deleted).toEqual([]);
  });

  it("削除している間はその軸の削除を押せず、失敗したら理由を出す", async () => {
    const held = heldReplies();
    onSameOrigin("DELETE", DEFINITION, held.reply);
    const user = await renderStudio();
    await deleteDraft(user);
    expect(within(rowOf("下書きの軸")).getByRole("button", { name: "削除" })).toBeDisabled();

    await held.answer(0, failure("削除できません"));
    expect(await screen.findByText("削除できません")).toBeInTheDocument();
    expect(within(rowOf("下書きの軸")).getByRole("button", { name: "削除" })).toBeEnabled();
  });
});

describe("段階プレビューの配色", () => {
  async function openEdit() {
    const user = await renderStudio();
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "編集" }));
  }

  it("地図に出る経路がまだ無い軸には、配色を渡さない（単位も空）", async () => {
    await openEdit();
    expect(composer.props!.mapBandColors).toBeUndefined();
    expect(composer.props!.mapValueUnit).toBe("");
  });

  it("複製のときは、複製元の軸の配色を使う", async () => {
    catalogAxes = [rampEntry(DRAFT.axis_id, [])];
    const user = await renderStudio();
    await user.click(within(rowOf("下書きの軸")).getByRole("button", { name: "複製して新規作成" }));
    await waitFor(() => expect(composer.props!.mapBandColors).toBeDefined());
  });
});
