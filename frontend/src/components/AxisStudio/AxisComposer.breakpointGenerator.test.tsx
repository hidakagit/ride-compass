// T598(2〜4番): 折れ点の自動生成・効き目プレビュー・エディタ操作改善の回帰テスト。
// これらはいずれも材料の参考点（reference_points）が無いと表示されない
// （primaryMaterialReferencePoints、AxisComposer.tsx参照）。AxisComposer.test.tsxは
// getMaterialCatalogを常に失敗させる方針（静的フォールバックには参考点が無い）のため、
// 参考点ありのケースはAxisComposer.materialValues.test.tsxと同じ考え方でこのファイルへ
// 分離する。
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AxisComposer from "./AxisComposer";

vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockResolvedValue({
    materials: [
      {
        material_id: "gradient_percent",
        label: "勾配%（符号付き） - gradient_percent",
        description: "勾配（%）。",
        dtype: "numeric",
        unit: "%",
        reference_points: [
          { label: "緩い坂", value: 3 },
          { label: "きつい坂", value: 9 },
        ],
      },
    ],
  }),
  getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

async function clickNext(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "次へ" }));
}

async function openBreakpointStep(user: ReturnType<typeof userEvent.setup>, label: string) {
  render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);
  await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), label);
  await clickNext(user); // basic -> shape_kind（既定でbreakpoint_linearが選択済み）
  await clickNext(user); // shape_kind -> shape_params
  // 材料カタログの実行時取得が解決し、参考点付きの折れ点自動生成UIが現れるのを待つ。
  await waitFor(() => expect(screen.getByRole("group", { name: "参考点から値を選ぶ" })).toBeInTheDocument());
}

describe("AxisComposer 折れ点の自動生成・効き目プレビュー", () => {
  it("参考点ボタンをクリックすると生成フォームの値欄が埋まる", async () => {
    const user = userEvent.setup();
    await openBreakpointStep(user, "軸F");

    await user.click(screen.getByRole("button", { name: "緩い坂" }));
    expect(screen.getByRole("spinbutton", { name: "0点にする値" })).toHaveValue(3);

    await user.dblClick(screen.getByRole("button", { name: "きつい坂" }));
    expect(screen.getByRole("spinbutton", { name: "100点にする値" })).toHaveValue(9);
  });

  it("「生成」を押すと一定(flat)の形で折れ点を作り直す", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);
    await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸F");
    await clickNext(user);
    await clickNext(user);
    await waitFor(() => expect(screen.getByRole("group", { name: "参考点から値を選ぶ" })).toBeInTheDocument());

    const zeroInput = screen.getByRole("spinbutton", { name: "0点にする値" });
    await user.clear(zeroInput);
    await user.type(zeroInput, "0");
    const hundredInput = screen.getByRole("spinbutton", { name: "100点にする値" });
    await user.clear(hundredInput);
    await user.type(hundredInput, "10");
    await user.click(screen.getByRole("button", { name: "生成" }));

    await clickNext(user);
    await user.click(screen.getByRole("button", { name: "作成する" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const [payload] = onSave.mock.calls[0];
    expect(payload.shape.breakpoints).toEqual([
      [0, 0],
      [2, 20],
      [4, 40],
      [6, 60],
      [8, 80],
      [10, 100],
    ]);
  });

  it("効き目プレビュー表は今の折れ点で各参考点が何点になるかを表示し、折れ点を変えると追従する", async () => {
    const user = userEvent.setup();
    await openBreakpointStep(user, "軸F");

    // 既定の折れ点[[0,0],[10,100]]・weight=1のため、緩い坂(3)→30点・きつい坂(9)→90点。
    const rows = screen.getAllByRole("row");
    expect(rows.find((r) => r.textContent?.includes("緩い坂"))?.textContent).toContain("30");
    expect(rows.find((r) => r.textContent?.includes("きつい坂"))?.textContent).toContain("90");

    // 折れ点[10,100]をスコア50へ変更すると、プレビューも追従する。
    const scoreInputs = screen.getAllByRole("spinbutton", { name: "スコア" });
    await user.clear(scoreInputs[1]);
    await user.type(scoreInputs[1], "50");

    await waitFor(() => {
      const updatedRows = screen.getAllByRole("row");
      expect(updatedRows.find((r) => r.textContent?.includes("緩い坂"))?.textContent).toContain("15");
      expect(updatedRows.find((r) => r.textContent?.includes("きつい坂"))?.textContent).toContain("45");
    });
  });

  it("矢印キーで折れ点を微調整できる", async () => {
    const user = userEvent.setup();
    await openBreakpointStep(user, "軸F");

    const sliders = screen.getAllByRole("slider", { name: /折れ点/ });
    sliders[1].focus();
    await user.keyboard("{ArrowDown}");

    expect(screen.getAllByRole("spinbutton", { name: "スコア" })[1]).toHaveValue(99);
  });
});
