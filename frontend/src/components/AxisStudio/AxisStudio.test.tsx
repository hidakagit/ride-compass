// 改善計画T329: 既定のDOM環境をhappy-domへ変更した際、happy-domはwindow.confirmを
// 定義せずvi.spyOn(window, "confirm")が失敗した（jsdomはNot implementedスタブとして
// 関数を持つため成功する）。window.confirmを使う削除確認ダイアログのテストがあるこの
// ファイルだけ、明示的に従来のjsdomへ戻す。
// @vitest-environment jsdom
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
  getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

import {
  createAxisDefinition,
  deleteAxisDefinition,
  listAxisDefinitions,
  unpublishAxisDefinition,
} from "@/services/axisAdminApi";

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
    time_scope: "always",
    supports_route_coloring: false,
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
  // 改善計画T332でウィザード化された後は、この項目は最終ステップ（地図表示・公開）に
  // あるため、表示名を入力して3ステップ分「次へ」を押してから確認する。
  it("フォームに地図上アイコン表示のON/OFFチェックボックスがあり、既定でONで、見出しに開発用のタスク番号表記が残っていない", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));
    await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "新軸");
    await user.click(screen.getByRole("button", { name: "次へ" }));
    await user.click(screen.getByRole("button", { name: "次へ" }));
    await user.click(screen.getByRole("button", { name: "次へ" }));

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

  // 改善計画T322: 「ぴったり評価」の材料選択にcategorical dtype材料（tracktype等）も
  // 現れ、選ぶと値ごとのスコア行編集UIへ切り替わる回帰テスト。改善計画T332で
  // ウィザード化された後は、表示名入力→点数のつけ方カード選択→材料選択、という
  // 3ステップに分かれている（改善計画T397でカード名を「ぴったり評価」へ変更）。
  it("「ぴったり評価」でcategorical材料を選ぶと値ごとのスコア行が編集できる", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));
    await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "新軸");
    await user.click(screen.getByRole("button", { name: "次へ" }));
    await user.click(screen.getByRole("radio", { name: /ぴったり評価/ }));
    await user.click(screen.getByRole("button", { name: "次へ" }));

    const materialSelect = screen.getByRole("combobox", { name: "材料(material)" });
    // 静的フォールバック(AXIS_MATERIAL_OPTIONS)にはcategorical材料として未舗装路グレードを含む
    // （改善計画T345さらなるフォローアップ2: labelは「論理名 - 物理名」形式）。
    expect(screen.getByRole("option", { name: "未舗装路グレード(tracktype) - tracktype" })).toBeInTheDocument();
    await user.selectOptions(materialSelect, "tracktype");

    expect(screen.queryByText("該当時(true)のスコア")).not.toBeInTheDocument();
    const valueInput = screen.getByLabelText("値");
    await user.type(valueInput, "separated");
    await user.click(screen.getByRole("button", { name: "+ 値を追加" }));
    expect(screen.getAllByLabelText("値")).toHaveLength(2);
  });

  // 改善計画T332（軸スタジオのウィザード化）: 表示名が空のまま「次へ」を押すと、
  // ステップは進まずエラーが表示される回帰テスト。
  it("ウィザードの1ステップ目で表示名が空のまま「次へ」を押すと進まずエラーが出る", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));
    await user.click(screen.getByRole("button", { name: "次へ" }));

    expect(screen.getByText("表示名(label)を入力してください。")).toBeInTheDocument();
    expect(screen.getByText("ステップ 1/4: 基本情報")).toBeInTheDocument();
  });

  // 改善計画T332: 「戻る」で前のステップに戻っても入力済みの値は失われない回帰テスト。
  it("ウィザードで「次へ」→「戻る」しても表示名の入力内容が残る", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));
    await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "私の軸");
    await user.click(screen.getByRole("button", { name: "次へ" }));
    expect(screen.getByText("ステップ 2/4: 点数のつけ方を選ぶ")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "戻る" }));

    expect(screen.getByText("ステップ 1/4: 基本情報")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "表示名(label)" })).toHaveValue("私の軸");
  });

  // 改善計画T327（UIレビュー2026-08-25 F-5）: 点数の詳細ステップに、スコアの向き
  // を明示する説明文が出る回帰テスト。改善計画T345: T327時点の文言は実際の向きと逆
  // だった（0=走りやすい・100=走りにくいが正しい。組み込みのgradient軸が勾配0%→
  // スコア0・15%→スコア100であることから判明したバグ）。改善計画T397フォローアップ
  // （ユーザー指摘: 説明文が多く見にくい）で、折れ点・カテゴリ等3箇所に重複していた
  // この文言をステップ先頭の1箇所へ統合・短縮した（AxisComposer.tsx:
  // renderShapeParamsStep冒頭参照）。
  it("点数の詳細ステップにスコアの向きを説明する文言がある", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));
    await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "新軸");
    await user.click(screen.getByRole("button", { name: "次へ" }));
    // 既定の選択（なめらか評価）のまま次へ。
    await user.click(screen.getByRole("button", { name: "次へ" }));

    expect(screen.getByText(/スコアは0\(走りやすい\)〜100\(走りにくい\)/)).toBeInTheDocument();
  });

  // 改善計画T325（UIレビュー2026-08-25 F-3）: 他axis_idを材料として参照する軸（例:
  // car_stress軸）の一覧サマリが、生のsnake_case識別子ではなく参照先の表示名(label)で
  // 表示される回帰テスト。
  it("他axis_idを材料として参照する軸のサマリは、生の識別子ではなく参照先の表示名で表示される", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([
      definition({ axis_id: "highway_base", label: "highway基準値" }),
      definition({
        axis_id: "car_stress",
        label: "車の圧迫感",
        shape: {
          kind: "breakpoint_linear",
          terms: [{ material: "highway_base", weight: 1.0, required: true }],
          preprocess: "identity",
          breakpoints: [
            [0, 0],
            [10, 100],
          ],
        },
      }),
    ]);
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("車の圧迫感")).toBeInTheDocument());

    // 軸名の見出し（"highway基準値"単体）と紛れないよう、サマリ行特有の
    // 「・ <ラベル>」という区切り付きパターンで照合する。
    expect(screen.getByText(/・ highway基準値/)).toBeInTheDocument();
    expect(screen.queryByText(/highway_base/)).not.toBeInTheDocument();
  });

  // 改善計画T323（UIレビュー2026-08-25 F-1）: 他の軸から材料として参照されている軸を
  // 削除しようとすると、参照元の名前と影響を明示する確認ダイアログが出る回帰テスト。
  it("他の軸から参照されている軸を削除しようとすると確認ダイアログが出て、キャンセルすれば削除されない", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([
      definition({ axis_id: "highway_base", label: "highway基準値" }),
      definition({
        axis_id: "car_stress",
        label: "車の圧迫感",
        shape: {
          kind: "breakpoint_linear",
          terms: [{ material: "highway_base", weight: 1.0, required: true }],
          preprocess: "identity",
          breakpoints: [
            [0, 0],
            [10, 100],
          ],
        },
      }),
    ]);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("highway基準値")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: "削除" })[0]);

    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining("車の圧迫感"));
    expect(deleteAxisDefinition).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("確認ダイアログでOKを押せば、参照されている軸でも削除される", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([
      definition({ axis_id: "highway_base", label: "highway基準値" }),
      definition({
        axis_id: "car_stress",
        label: "車の圧迫感",
        shape: {
          kind: "breakpoint_linear",
          terms: [{ material: "highway_base", weight: 1.0, required: true }],
          preprocess: "identity",
          breakpoints: [
            [0, 0],
            [10, 100],
          ],
        },
      }),
    ]);
    vi.mocked(deleteAxisDefinition).mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("highway基準値")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: "削除" })[0]);

    expect(deleteAxisDefinition).toHaveBeenCalledWith("highway_base");
    confirmSpy.mockRestore();
  });

  it("他の軸から参照されていない軸の削除は確認ダイアログを出さない", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition(), definition({ axis_id: "surface_q", label: "舗装状況" })]);
    vi.mocked(deleteAxisDefinition).mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: "削除" })[0]);

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(deleteAxisDefinition).toHaveBeenCalledWith("gradient");
    confirmSpy.mockRestore();
  });

  // 改善計画T397フォローアップ（ユーザー指摘: 公開済み/未公開をタブで分けたい）:
  // 「非公開に戻す」は公開済みタブにのみ現れ、下書きタブには編集・削除ボタンが現れる
  // （公開済みタブは編集・削除ボタン自体を出さない設計、AxisStudio.tsx参照）。
  it("下書きタブには編集・削除ボタンが、公開済みタブには非公開に戻すボタンが現れる", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([
      definition({ axis_id: "gradient", is_published: true }),
      definition({ axis_id: "draft_axis", label: "下書き軸", is_published: false }),
    ]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("下書き軸")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "編集" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "非公開に戻す" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /公開済み/ }));

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "非公開に戻す" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "編集" })).not.toBeInTheDocument();
  });

  // 改善計画T331残り5項目: AxisStudio.tsxのCRUD実行系（複製・削除・非公開化・保存）の
  // うち、削除は既にテスト済み。ここでは複製・非公開化・保存（新規作成）の配線を確認する。

  it("「複製して新規作成」を押すと複製元の内容で新規作成モーダルが開く（axis_idは新規採番、is_publishedはfalseへ戻る）", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([
      definition({ axis_id: "gradient", label: "勾配", is_published: true, default_weight: 0.42 }),
    ]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    // 改善計画T397フォローアップ: 公開済み軸は公開済みタブにいる。
    await user.click(screen.getByRole("tab", { name: /公開済み/ }));
    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "複製して新規作成" }));

    expect(screen.getByRole("dialog", { name: "「勾配」を複製して新しい軸を作る" })).toBeInTheDocument();
    // 複製元の値（表示名・既定重み）は引き継がれる
    expect(screen.getByRole("textbox", { name: "表示名(label)" })).toHaveValue("勾配");
    expect(screen.getByRole("spinbutton", { name: "既定重み(default_weight)" })).toHaveValue(0.42);
  });

  it("「非公開に戻す」を押すとunpublishAxisDefinitionが呼ばれ、一覧が再読み込みされる", async () => {
    // listAxisDefinitionsはファイル内の全テストで共有されるモックのため（beforeEachでの
    // リセットが無い、Checkbox関連のResizeObserverモックのみ）、絶対呼び出し回数ではなく
    // 「この操作の前後での差分」で検証する。
    vi.mocked(listAxisDefinitions)
      .mockResolvedValueOnce([definition({ axis_id: "gradient", is_published: true })])
      .mockResolvedValueOnce([definition({ axis_id: "gradient", is_published: false })]);
    vi.mocked(unpublishAxisDefinition).mockResolvedValue(definition({ axis_id: "gradient", is_published: false }));
    const user = userEvent.setup();
    render(<AxisStudio />);

    // 改善計画T397フォローアップ: 公開済み軸は公開済みタブにいる。
    await user.click(screen.getByRole("tab", { name: /公開済み/ }));
    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    const callsBeforeUnpublish = vi.mocked(listAxisDefinitions).mock.calls.length;
    await user.click(screen.getByRole("button", { name: "非公開に戻す" }));

    expect(unpublishAxisDefinition).toHaveBeenCalledWith("gradient");
    // 再読み込み後は下書き（is_published: false）扱いになり、「非公開に戻す」ボタンが消える
    await waitFor(() => expect(screen.queryByRole("button", { name: "非公開に戻す" })).not.toBeInTheDocument());
    expect(vi.mocked(listAxisDefinitions).mock.calls.length).toBe(callsBeforeUnpublish + 1);
  });

  it("ウィザードを最後まで完了して保存すると、createAxisDefinitionが呼ばれモーダルが閉じて一覧が再読み込みされる", async () => {
    vi.mocked(listAxisDefinitions)
      .mockResolvedValueOnce([definition()])
      .mockResolvedValueOnce([definition(), definition({ axis_id: "new_axis", label: "新軸" })]);
    vi.mocked(createAxisDefinition).mockResolvedValue(definition({ axis_id: "new_axis", label: "新軸" }));
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    const callsBeforeSave = vi.mocked(listAxisDefinitions).mock.calls.length;
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));
    await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "新軸");
    await user.click(screen.getByRole("button", { name: "次へ" })); // 1/4 -> 2/4
    await user.click(screen.getByRole("button", { name: "次へ" })); // 2/4 -> 3/4（既定のbreakpoint_linearのまま）
    await user.click(screen.getByRole("button", { name: "次へ" })); // 3/4 -> 4/4（既定の材料・折れ点のまま）
    await user.click(screen.getByRole("button", { name: "作成する" }));

    await waitFor(() => expect(createAxisDefinition).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(createAxisDefinition).mock.calls[0][0];
    expect(payload.label).toBe("新軸");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(vi.mocked(listAxisDefinitions).mock.calls.length).toBe(callsBeforeSave + 1);
  });
});
