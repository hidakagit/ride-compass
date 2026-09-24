/**
 * `ResearchPanel.tsx`——研究モードの今の値を出すこと。
 *
 * ここで見ないもの:
 * - 研究モードの値の保持と共有 → `lib/researchMode.ts`
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const research = vi.hoisted(() => ({ enabled: false }));
vi.mock("@/hooks/useResearchMode", () => ({ useResearchEnabled: () => research.enabled }));

import ResearchPanel from "./ResearchPanel";

describe("ResearchPanel", () => {
  it.each([
    [true, "ON"],
    [false, "OFF"],
  ])("研究モードが%sならその値を出す", (enabled, shown) => {
    research.enabled = enabled;
    render(<ResearchPanel />);

    expect(screen.getByText(shown)).toBeInTheDocument();
  });
});
