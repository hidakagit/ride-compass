import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AxisDefinitionResponse } from "@/types/route";
import AxisStudio from "./AxisStudio";

// 改善計画T304: 「編集ボタンを押した後にそのまま編集画面がポップアップ起動してほしい。
// 下部エリアの編集エリアまで目が行かない」という実機フィードバックへの対応の回帰テスト。
// 一覧・作成・更新・削除はbackendの管理APIへ実際に飛ぶため、ここではaxisAdminApi.ts全体を
// モックする（RouteSettingsPanel.test.tsxと同じ方針、実HTTPは呼ばない）。
vi.mock("@/services/axisAdminApi", () => ({
  listAxisDefinitions: vi.fn(),
  createAxisDefinition: vi.fn(),
  updateAxisDefinition: vi.fn(),
  deleteAxisDefinition: vi.fn(),
  unpublishAxisDefinition: vi.fn(),
}));
// AxisComposerが使うuseMaterialCatalogの取得先。フォールバック（静的9材料）で十分なため
// 失敗させておく。
vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

import { listAxisDefinitions } from "@/services/axisAdminApi";

function definition(overrides: Partial<AxisDefinitionResponse> = {}): AxisDefinitionResponse {
  return {
    axis_id: "gradient",
    label: "勾配",
    description: "",
    category: "観測",
    default_weight: 0.2,
    is_published: false,
    priority_overrides: [],
    show_map_icon: true,
    shape: {
      kind: "breakpoint_linear",
      terms: [{ material: "gradient_percent", weight: 1.0, required: true }],
      preprocess: "identity",
      breakpoints: [
        [0, 0],
        [10, 100],
      ],
    },
    ...overrides,
  };
}

describe("AxisStudio", () => {
  beforeEach(() => {
    // jsdomはResizeObserverを実装しない（DynamicLayerTimeSlider.test.tsxと同じ既知の欠落）。
    // AxisComposerの<form>内にあるRadix Checkbox（改善計画T299フォローアップ）はフォーム
    // 直下でのみ隠しbubble input（HTMLフォーム互換用）のサイズ同期にuseSizeを使い、これが
    // 内部でResizeObserverを呼ぶため、フォーム外で単体レンダリングするCheckbox.test.tsxでは
    // 再現しないがAxisStudioのモーダルを開くテストでは未定義のまま例外になる。
    class ResizeObserverMock {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    }
    window.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;
  });

  it("マウント時に資格情報の入力を待たず軸一覧を読み込む", async () => {
    // 改善計画T305: /adminページ自体が既にBasic認証済みのため、この画面固有の
    // ユーザー名/パスワード入力欄はもう無い（回帰確認）。
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    expect(screen.queryByLabelText("管理者ユーザー名")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("管理者パスワード")).not.toBeInTheDocument();
  });

  it("「編集」を押すとその軸の内容で編集モーダルが即座に開く", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "編集" }));

    // 改善計画T305: axis_idはフォームから撤去し、モーダル見出しも表示名(label)基準にした。
    expect(screen.getByRole("dialog", { name: "軸を編集: 勾配" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "表示名(label)" })).toHaveValue("勾配");
    expect(screen.queryByRole("textbox", { name: "axis_id" })).not.toBeInTheDocument();
  });

  it("「+ 新しい軸を作る」を押すと空のモーダルが開く", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition(), definition({ axis_id: "surface_q", label: "舗装状況" })]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));

    expect(screen.getByRole("dialog", { name: "新しい軸を作る" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "表示名(label)" })).toHaveValue("");
  });

  // 改善計画T318（ユーザー判断: 「軸スタジオで、地図マップ上にアイコン表示するかどうか
  // ON/OFFできるようにして。ヘッダのT310等の文字は消して」）。
  it("フォームに地図上アイコン表示のON/OFFチェックボックスがあり、既定でONで、見出しに開発用のタスク番号表記が残っていない", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));

    const toggle = screen.getByRole("checkbox", { name: "地図上にアイコンを表示する(show_map_icon)" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByText(/改善計画T310/)).not.toBeInTheDocument();
  });

  it("モーダルを閉じるとダイアログが消え、一覧はそのまま残る", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "編集" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "閉じる" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("勾配")).toBeInTheDocument();
  });

  // 改善計画T322: 「カテゴリ値」テンプレートの材料選択にcategorical dtype材料
  // （bicycle_infra等）も現れ、選ぶと値ごとのスコア行編集UIへ切り替わる回帰テスト。
  it("「カテゴリ値」テンプレートでcategorical材料を選ぶと値ごとのスコア行が編集できる", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "変換テンプレート(shape)" }), "categorical");

    const materialSelect = screen.getByRole("combobox", { name: "材料(material)" });
    // 静的フォールバック(AXIS_MATERIAL_OPTIONS)にはcategorical材料として自転車インフラ種別を含む。
    expect(screen.getByRole("option", { name: "自転車インフラ種別" })).toBeInTheDocument();
    await user.selectOptions(materialSelect, "bicycle_infra");

    expect(screen.queryByText("該当時(true)のスコア")).not.toBeInTheDocument();
    const valueInput = screen.getByLabelText("値");
    await user.type(valueInput, "separated");
    await user.click(screen.getByRole("button", { name: "+ 値を追加" }));
    expect(screen.getAllByLabelText("値")).toHaveLength(2);
  });

  it("公開済み軸には「非公開に戻す」ボタンが表示され、下書き軸には表示されない", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([
      definition({ axis_id: "gradient", is_published: true }),
      definition({ axis_id: "draft_axis", label: "下書き軸", is_published: false }),
    ]);
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());

    expect(screen.getAllByRole("button", { name: "非公開に戻す" })).toHaveLength(1);
  });
});
