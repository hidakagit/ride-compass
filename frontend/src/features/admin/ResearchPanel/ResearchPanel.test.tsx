/**
 * `ResearchPanel.tsx`——研究モードの今の値を出すこと。
 *
 * ここで見ないもの:
 * - 研究モードの値の保持と共有 → `lib/researchMode.ts`（本物を通し、テストごとにOFFへ戻す）
 */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { setResearchEnabled } from "@/lib/researchMode";

import ResearchPanel from "./ResearchPanel";

afterEach(() => {
  setResearchEnabled(false);
});

describe("ResearchPanel", () => {
  it.each([
    [true, "ON"],
    [false, "OFF"],
  ])("研究モードが%sならその値を出す", (enabled, shown) => {
    setResearchEnabled(enabled);
    render(<ResearchPanel />);

    expect(screen.getByText(shown)).toBeInTheDocument();
  });
});
