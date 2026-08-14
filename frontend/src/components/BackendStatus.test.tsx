import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { checkBackendHealth } from "@/services/healthApi";
import BackendStatus from "./BackendStatus";

vi.mock("@/services/healthApi");

const mockedCheckBackendHealth = vi.mocked(checkBackendHealth);

describe("BackendStatus", () => {
  it("初期描画(未解決)では確認中...を表示する", () => {
    mockedCheckBackendHealth.mockReturnValue(new Promise(() => {}));
    render(<BackendStatus />);
    expect(screen.getByText("確認中...")).toBeInTheDocument();
  });

  it("checkBackendHealthがtrueに解決するとBackend: OKを表示する", async () => {
    mockedCheckBackendHealth.mockResolvedValue(true);
    render(<BackendStatus />);

    await waitFor(() => expect(screen.getByText("Backend: OK")).toBeInTheDocument());
  });

  it("checkBackendHealthがfalseに解決するとBackend: NGを表示する", async () => {
    mockedCheckBackendHealth.mockResolvedValue(false);
    render(<BackendStatus />);

    await waitFor(() => expect(screen.getByText("Backend: NG")).toBeInTheDocument());
  });
});
