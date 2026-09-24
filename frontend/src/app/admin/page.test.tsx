/**
 * `app/admin/page.tsx`——管理画面の入口の状態: 開いたときのタブ、システム状況の開閉、
 * デバッグモード中の案内。
 *
 * 各タブの中身は差し替えて、目印だけを描く（中身の振る舞いはそれぞれのファイルが持つ）。
 * どのタブにどのパネルを置くかは画面の宣言で、ここでは書き写さない。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const debug = vi.hoisted(() => ({ enabled: false }));

vi.mock("@/hooks/useDebugLog", () => ({ useDebugEnabled: () => debug.enabled }));

function marker(name: string) {
  return { default: () => <div data-testid={name} /> };
}
vi.mock("@/features/admin/AxisStudio/AxisStudio", () => marker("AxisStudio"));
vi.mock("@/features/admin/AxisStudio/MaterialCoveragePanel", () => marker("MaterialCoveragePanel"));
vi.mock("@/features/admin/AxisStudio/DerivedDataFreshnessPanel", () => marker("DerivedDataFreshnessPanel"));
vi.mock("@/features/admin/AxisStudio/DbStatusPanel", () => marker("DbStatusPanel"));
vi.mock("@/features/admin/AxisStudio/TileCachePanel", () => marker("TileCachePanel"));
vi.mock("@/features/admin/AxisStudio/TuningPanel", () => marker("TuningPanel"));
vi.mock("@/features/admin/ResearchPanel/ResearchPanel", () => marker("ResearchPanel"));
vi.mock("@/features/admin/DebugPanel/DebugPanel", () => marker("DebugPanel"));
vi.mock("@/features/admin/BackendStatus/BackendStatus", () => marker("BackendStatus"));
vi.mock("@/features/admin/BackendLogsPanel/BackendLogsPanel", () => marker("BackendLogsPanel"));
vi.mock("@/features/admin/SystemStatusPanel/SystemStatusPanel", () => ({
  default: ({ open, onClose }: { open: boolean; onClose: () => void }) =>
    open ? (
      <button type="button" onClick={onClose}>
        パネルを閉じる
      </button>
    ) : null,
}));

import AdminPage from "./page";

beforeEach(() => {
  debug.enabled = false;
});

async function openDeveloperTab() {
  const user = userEvent.setup();
  render(<AdminPage />);
  await user.click(screen.getByRole("tab", { name: "開発者" }));
  return user;
}

describe("AdminPage", () => {
  it("開くと軸スタジオのタブが選ばれる", () => {
    render(<AdminPage />);

    expect(screen.getByRole("tab", { name: "軸スタジオ" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("AxisStudio")).toBeInTheDocument();
  });

  it("システム状況は閉じた状態で始まり、ボタンで開閉し、パネル側から閉じても戻る", async () => {
    const user = await openDeveloperTab();

    expect(screen.queryByRole("button", { name: "パネルを閉じる" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "システム状況を表示" }));
    expect(screen.getByRole("button", { name: "パネルを閉じる" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "システム状況を隠す" }));
    expect(screen.queryByRole("button", { name: "パネルを閉じる" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "システム状況を表示" }));
    await user.click(screen.getByRole("button", { name: "パネルを閉じる" }));
    expect(screen.queryByRole("button", { name: "パネルを閉じる" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "システム状況を表示" })).toBeInTheDocument();
  });

  it("デバッグモード中だけ、ログの表示はトップページで行うと案内する", async () => {
    debug.enabled = true;
    await openDeveloperTab();
    expect(screen.getByText(/トップページ/)).toBeInTheDocument();
  });

  it("デバッグモードでなければ、その案内を出さない", async () => {
    await openDeveloperTab();
    expect(screen.queryByText(/トップページ/)).not.toBeInTheDocument();
  });
});
