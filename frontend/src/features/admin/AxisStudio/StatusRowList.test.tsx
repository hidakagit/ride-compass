/**
 * `StatusRowList.tsx`——点検の行の一覧: 見出しは持たせた群にだけ出し、行は名前・規模・手当ての要否
 * （読み上げの文）を1行に、開いた先に項目と値・注記を置く。結果の一言は手当ての要否で目立たせ方を変える。
 *
 * ここで見ないもの:
 * - どの点検からどの行を作るか → `DerivedDataFreshnessPanel.test.tsx`・`DbStatusPanel.test.tsx`
 * - 目立たせ方の見た目 → `components/ui/Callout`
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/ui/Callout/Callout", () => ({
  Callout: ({ tone, children }: { tone: string; children: React.ReactNode }) => (
    <div data-testid="verdict" data-tone={tone}>
      {children}
    </div>
  ),
}));

import { type StatusRow, StatusRowList, StatusVerdict } from "./StatusRowList";

function row(overrides: Partial<StatusRow>): StatusRow {
  return { name: "row", scale: "", flagged: false, detail: [], ...overrides };
}

function renderList(groups: { title?: string; rows: StatusRow[] }[]) {
  render(<StatusRowList groups={groups} flaggedLabel="要対応" okLabel="問題なし" />);
  return screen.getByRole("list");
}

describe("StatusRowList", () => {
  it("見出しは、持たせた群にだけ、その群の行より前に出す", () => {
    const list = renderList([{ title: "群A", rows: [row({ name: "a1" })] }, { rows: [row({ name: "b1" })] }]);

    const items = within(list)
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(items).toEqual(["群A", expect.stringMatching(/^a1/), expect.stringMatching(/^b1/)]);
  });

  it("行の名前の横に規模と、手当ての要否を置く", () => {
    renderList([
      {
        rows: [row({ name: "flagged_table", scale: "12行", flagged: true }), row({ name: "ok_table", flagged: false })],
      },
    ]);

    const flagged = screen.getByText("flagged_table").closest("summary")!;
    expect(flagged).toHaveTextContent("12行");
    expect(within(flagged).getByText("要対応")).toBeInTheDocument();
    expect(within(screen.getByText("ok_table").closest("summary")!).getByText("問題なし")).toBeInTheDocument();
  });

  it("開いた先に項目と値を並べ、注記は持たせた行にだけ出す", () => {
    renderList([
      {
        rows: [
          row({ name: "with_note", detail: [{ label: "最新", value: "#3" }], note: "注記です" }),
          row({ name: "without_note", detail: [{ label: "最新", value: "#4" }] }),
        ],
      },
    ]);

    const withNote = screen.getByText("with_note").closest("details")!;
    expect(within(withNote).getByText("最新").tagName).toBe("DT");
    expect(within(withNote).getByText("#3").tagName).toBe("DD");
    expect(within(withNote).getByText("注記です")).toBeInTheDocument();
    expect(screen.getByText("without_note").closest("details")!.querySelectorAll("p")).toHaveLength(0);
  });
});

describe("StatusVerdict", () => {
  it.each([
    [true, "danger"],
    [false, "neutral"],
  ])("手当てが要る（%s）かで目立たせ方を変える", (flagged, tone) => {
    render(<StatusVerdict flagged={flagged}>結果</StatusVerdict>);
    expect(screen.getByTestId("verdict")).toHaveAttribute("data-tone", tone);
    expect(screen.getByTestId("verdict")).toHaveTextContent("結果");
  });
});
