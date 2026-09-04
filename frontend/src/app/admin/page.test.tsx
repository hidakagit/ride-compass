import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// /adminページ（改善計画T270軸スタジオ・T331でpage.tsx自体の未テストを解消、T397フォロー
// アップ2で縦積みDisclosure3枚からタブ3枚へ再構成）。軸スタジオ・研究モード・開発者向けの
// 各タブを束ねるだけの薄いコンテナのため、地図等の重いコンポーネントは無く子コンポーネント
// の実体はここでは検証しない（各コンポーネント自身のテストファイルの責務）。ここでは
// page.tsx固有のロジック——debugEnabledによる条件表示の出し分け、systemStatusOpenの
// 開閉トグル——だけを確認する（改善計画T548: 従来はweightOverrideEnabled/scoringWeightsの
// useStoredJsonState経由でのlocalStorage同期もここで検証していたが、total_score撤去に
// 伴いWeightPanel自体を削除したため対応するテストも削除した）。

vi.mock("@/components/BackendStatus", () => ({ default: () => <div data-testid="backend-status" /> }));
vi.mock("@/components/DebugPanel/DebugPanel", () => ({ default: () => <div data-testid="debug-panel" /> }));
vi.mock("@/components/ResearchPanel/ResearchPanel", () => ({ default: () => <div data-testid="research-panel" /> }));
vi.mock("@/components/AxisStudio/AxisStudio", () => ({ default: () => <div data-testid="axis-studio" /> }));
vi.mock("@/components/AxisStudio/MaterialCoveragePanel", () => ({
  default: () => <div data-testid="material-coverage-panel" />,
}));
vi.mock("@/components/SystemStatusPanel/SystemStatusPanel", () => ({
  default: ({ open, onClose }: { open: boolean; onClose: () => void }) => (
    <div data-testid="system-status-panel" data-open={open}>
      <button type="button" onClick={onClose}>
        close
      </button>
    </div>
  ),
}));

const useDebugEnabledMock = vi.fn();
vi.mock("@/hooks/useDebugLog", () => ({ useDebugEnabled: () => useDebugEnabledMock() }));

import AdminPage from "./page";

// 改善計画T397フォローアップ2: 軸スタジオ/研究/開発者はRadix Tabsの3タブになった
// （既定で開いているのは先頭の「軸スタジオ」のみ、Tabs.Contentは非選択中DOMへ現れない）。
// 研究・開発者タブの中身を検証するテストは、先にタブ自体をクリックして選択する必要がある。
async function openTab(name: "軸スタジオ" | "材料" | "研究" | "開発者") {
  const { default: userEvent } = await import("@testing-library/user-event");
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name }));
  return user;
}

describe("AdminPage（/admin、改善計画T270・T272・T397）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useDebugEnabledMock.mockReturnValue(false);
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("見出しと4つのタブを表示し、既定で軸スタジオタブが選択されている", () => {
    render(<AdminPage />);

    expect(screen.getByRole("heading", { name: "軸スタジオ・研究/開発者ツール" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["軸スタジオ", "材料", "研究", "開発者"]);
    expect(screen.getByRole("tab", { name: "軸スタジオ" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("axis-studio")).toBeInTheDocument();
    // 材料・研究・開発者タブは非選択のため中身はまだDOMへ現れない。
    expect(screen.queryByTestId("material-coverage-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("research-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("debug-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("backend-status")).not.toBeInTheDocument();
  });

  it("「材料」タブを開くとMaterialCoveragePanelを表示する", async () => {
    render(<AdminPage />);

    await openTab("材料");

    expect(screen.getByTestId("material-coverage-panel")).toBeInTheDocument();
  });

  it("「研究」タブを開くとResearchPanelを表示する", async () => {
    render(<AdminPage />);

    await openTab("研究");

    expect(screen.getByTestId("research-panel")).toBeInTheDocument();
  });

  it("「開発者」タブを開くとDebugPanel/BackendStatusを表示する", async () => {
    render(<AdminPage />);

    await openTab("開発者");

    expect(screen.getByTestId("debug-panel")).toBeInTheDocument();
    expect(screen.getByTestId("backend-status")).toBeInTheDocument();
  });

  it("デバッグモードOFFの間はDebugConsole案内ヒントを表示しない", async () => {
    useDebugEnabledMock.mockReturnValue(false);
    render(<AdminPage />);
    await openTab("開発者");

    expect(screen.queryByText(/デバッグログの表示はトップページ/)).not.toBeInTheDocument();
  });

  it("デバッグモードONの間はDebugConsole案内ヒント（トップページのヘッダーアイコンで見る旨）を表示する", async () => {
    useDebugEnabledMock.mockReturnValue(true);
    render(<AdminPage />);

    await openTab("開発者");

    expect(screen.getByText(/デバッグログの表示はトップページ/)).toBeInTheDocument();
  });

  it("「システム状況を表示」ボタンでSystemStatusPanelのopenをトグルする", async () => {
    render(<AdminPage />);
    const user = await openTab("開発者");

    const toggleButton = screen.getByRole("button", { name: "システム状況を表示" });
    expect(toggleButton).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("system-status-panel")).toHaveAttribute("data-open", "false");

    await user.click(toggleButton);

    expect(screen.getByRole("button", { name: "システム状況を隠す" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("system-status-panel")).toHaveAttribute("data-open", "true");
  });

  it("SystemStatusPanelのonCloseはsystemStatusOpenをfalseへ戻す", async () => {
    render(<AdminPage />);
    const user = await openTab("開発者");

    await user.click(screen.getByRole("button", { name: "システム状況を表示" }));
    expect(screen.getByTestId("system-status-panel")).toHaveAttribute("data-open", "true");

    await user.click(screen.getByRole("button", { name: "close" }));

    expect(screen.getByTestId("system-status-panel")).toHaveAttribute("data-open", "false");
    expect(screen.getByRole("button", { name: "システム状況を表示" })).toHaveAttribute("aria-pressed", "false");
  });
});
