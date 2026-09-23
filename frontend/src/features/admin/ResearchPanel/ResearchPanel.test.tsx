import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { setResearchEnabled } from "@/lib/researchMode";
import ResearchPanel from "./ResearchPanel";

// 改善計画T519: 研究モードON/OFFの操作導線は一般公開ページのヘッダーメニュー
// （HeaderMenu.tsx、HeaderMenu.test.tsx参照）へ移設した。ResearchPanelは現在値の
// 読み取り専用表示のみを持つ（チェックボックス操作は無い）。
describe("ResearchPanel", () => {
  beforeEach(() => {
    setResearchEnabled(false);
  });

  it("研究モードOFF時は「OFF」と表示する", () => {
    render(<ResearchPanel />);
    expect(screen.getByText("OFF")).toBeInTheDocument();
  });

  it("研究モードON時は「ON」と表示する", () => {
    setResearchEnabled(true);
    render(<ResearchPanel />);
    expect(screen.getByText("ON")).toBeInTheDocument();
  });

  it("チェックボックス等の操作可能な要素を持たない（読み取り専用表示のみ）", () => {
    render(<ResearchPanel />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
