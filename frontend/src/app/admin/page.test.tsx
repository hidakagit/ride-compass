import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// /adminページ（改善計画T270軸スタジオ・T331でpage.tsx自体の未テストを解消）。
// 軸スタジオ・研究モード・開発者向けの各セクションを束ねるだけの薄いコンテナのため、
// 地図等の重いコンポーネントは無く子コンポーネントの実体はここでは検証しない
// （各コンポーネント自身のテストファイルの責務）。ここではpage.tsx固有のロジック——
// researchEnabled/debugEnabledによる条件表示の出し分け、systemStatusOpenの開閉トグル、
// weightOverrideEnabled/scoringWeightsのuseStoredJsonState経由でのlocalStorage同期——
// だけを確認する。

vi.mock("@/components/BackendStatus", () => ({ default: () => <div data-testid="backend-status" /> }));
vi.mock("@/components/DebugPanel/DebugPanel", () => ({ default: () => <div data-testid="debug-panel" /> }));
vi.mock("@/components/ResearchPanel/ResearchPanel", () => ({ default: () => <div data-testid="research-panel" /> }));
vi.mock("@/components/AxisStudio/AxisStudio", () => ({ default: () => <div data-testid="axis-studio" /> }));
vi.mock("@/components/SystemStatusPanel/SystemStatusPanel", () => ({
  default: ({ open, onClose }: { open: boolean; onClose: () => void }) => (
    <div data-testid="system-status-panel" data-open={open}>
      <button type="button" onClick={onClose}>
        close
      </button>
    </div>
  ),
}));
vi.mock("@/components/WeightPanel/WeightPanel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/WeightPanel/WeightPanel")>();
  return {
    ...actual,
    default: ({
      overrideEnabled,
      onOverrideEnabledChange,
      scoringWeights,
      onScoringWeightsChange,
    }: {
      overrideEnabled: boolean;
      onOverrideEnabledChange: (v: boolean) => void;
      scoringWeights: Record<string, number>;
      onScoringWeightsChange: (v: Record<string, number>) => void;
    }) => (
      <div data-testid="weight-panel" data-override-enabled={overrideEnabled}>
        <button type="button" onClick={() => onOverrideEnabledChange(true)}>
          override-on
        </button>
        <button type="button" onClick={() => onScoringWeightsChange({ ...scoringWeights, gradient: 0.9 })}>
          change-weight
        </button>
      </div>
    ),
  };
});

const useResearchEnabledMock = vi.fn();
const useDebugEnabledMock = vi.fn();
vi.mock("@/hooks/useResearchMode", () => ({ useResearchEnabled: () => useResearchEnabledMock() }));
vi.mock("@/hooks/useDebugLog", () => ({ useDebugEnabled: () => useDebugEnabledMock() }));

import AdminPage from "./page";

// 「開発者」セクションはDisclosureにdefaultOpenを渡していないため既定で閉じている
// （「研究」セクションと異なりRadix Accordion.Contentは閉状態だと中身自体をレンダリングしない、
// 実機確認で判明）。DebugPanel/BackendStatus/システム状況トグル等、このセクション配下を
// 検証するテストは、先にトリガーをクリックして開いてから中身を見る必要がある。
async function openDeveloperSection() {
  const { default: userEvent } = await import("@testing-library/user-event");
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "開発者" }));
  return user;
}

describe("AdminPage（/admin、改善計画T270・T272）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useResearchEnabledMock.mockReturnValue(false);
    useDebugEnabledMock.mockReturnValue(false);
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("見出しと軸スタジオ・研究セクションを表示する（開発者セクションは既定で閉じている）", () => {
    render(<AdminPage />);

    expect(screen.getByRole("heading", { name: "軸スタジオ・研究/開発者ツール" })).toBeInTheDocument();
    expect(screen.getByTestId("axis-studio")).toBeInTheDocument();
    expect(screen.getByTestId("research-panel")).toBeInTheDocument();
    // 「開発者」はDisclosureのdefaultOpenを渡していないため既定で閉じており、
    // 中身（DebugPanel/BackendStatus）はまだDOMへ現れない。
    expect(screen.queryByTestId("debug-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("backend-status")).not.toBeInTheDocument();
  });

  it("「開発者」セクションを開くとDebugPanel/BackendStatusを表示する", async () => {
    render(<AdminPage />);

    await openDeveloperSection();

    expect(screen.getByTestId("debug-panel")).toBeInTheDocument();
    expect(screen.getByTestId("backend-status")).toBeInTheDocument();
  });

  it("研究モードOFFの間はWeightPanelを表示せずヒントのみ表示する", () => {
    useResearchEnabledMock.mockReturnValue(false);
    render(<AdminPage />);

    expect(screen.queryByTestId("weight-panel")).not.toBeInTheDocument();
    expect(screen.getByText(/研究モードは現在OFFです/)).toBeInTheDocument();
  });

  it("研究モードONの間はWeightPanelを表示しヒントを表示しない", () => {
    useResearchEnabledMock.mockReturnValue(true);
    render(<AdminPage />);

    expect(screen.getByTestId("weight-panel")).toBeInTheDocument();
    expect(screen.queryByText(/研究モードは現在OFFです/)).not.toBeInTheDocument();
  });

  it("デバッグモードOFFの間はDebugConsole案内ヒントを表示しない", () => {
    useDebugEnabledMock.mockReturnValue(false);
    render(<AdminPage />);

    expect(screen.queryByText(/デバッグログの表示はトップページ/)).not.toBeInTheDocument();
  });

  it("デバッグモードONの間はDebugConsole案内ヒント（トップページのヘッダーアイコンで見る旨）を表示する", async () => {
    useDebugEnabledMock.mockReturnValue(true);
    render(<AdminPage />);

    await openDeveloperSection();

    expect(screen.getByText(/デバッグログの表示はトップページ/)).toBeInTheDocument();
  });

  it("「システム状況を表示」ボタンでSystemStatusPanelのopenをトグルする", async () => {
    render(<AdminPage />);
    const user = await openDeveloperSection();

    const toggleButton = screen.getByRole("button", { name: "システム状況を表示" });
    expect(toggleButton).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("system-status-panel")).toHaveAttribute("data-open", "false");

    await user.click(toggleButton);

    expect(screen.getByRole("button", { name: "システム状況を隠す" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("system-status-panel")).toHaveAttribute("data-open", "true");
  });

  it("SystemStatusPanelのonCloseはsystemStatusOpenをfalseへ戻す", async () => {
    render(<AdminPage />);
    const user = await openDeveloperSection();

    await user.click(screen.getByRole("button", { name: "システム状況を表示" }));
    expect(screen.getByTestId("system-status-panel")).toHaveAttribute("data-open", "true");

    await user.click(screen.getByRole("button", { name: "close" }));

    expect(screen.getByTestId("system-status-panel")).toHaveAttribute("data-open", "false");
    expect(screen.getByRole("button", { name: "システム状況を表示" })).toHaveAttribute("aria-pressed", "false");
  });

  it("WeightPanelのonOverrideEnabledChangeはlocalStorage（ridecompass:weight-override-enabled）へ保存する", async () => {
    useResearchEnabledMock.mockReturnValue(true);
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<AdminPage />);

    await user.click(screen.getByRole("button", { name: "override-on" }));

    expect(window.localStorage.getItem("ridecompass:weight-override-enabled")).toBe("true");
    expect(screen.getByTestId("weight-panel")).toHaveAttribute("data-override-enabled", "true");
  });

  it("WeightPanelのonScoringWeightsChangeはlocalStorage（ridecompass:scoring-weights）へ保存する", async () => {
    useResearchEnabledMock.mockReturnValue(true);
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<AdminPage />);

    await user.click(screen.getByRole("button", { name: "change-weight" }));

    const stored = JSON.parse(window.localStorage.getItem("ridecompass:scoring-weights") ?? "{}");
    expect(stored.gradient).toBe(0.9);
  });

  it("localStorageに保存済みの評価重みがあれば初期表示に反映される", () => {
    useResearchEnabledMock.mockReturnValue(true);
    window.localStorage.setItem("ridecompass:weight-override-enabled", "true");
    render(<AdminPage />);

    expect(screen.getByTestId("weight-panel")).toHaveAttribute("data-override-enabled", "true");
  });
});
