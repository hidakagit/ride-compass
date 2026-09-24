/**
 * `BackendStatus.tsx`——backendの疎通を、確認中・OK・接続できないの3つで出すこと。
 *
 * ここで見ないもの:
 * - 疎通の判定（応答の読み方・失敗を偽にすること） → `features/admin/adminApi.test.ts`
 */
import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ checkBackendHealth: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => api);

import BackendStatus from "./BackendStatus";

beforeEach(() => {
  api.checkBackendHealth.mockReset();
});

describe("BackendStatus", () => {
  it("答えが来るまでは確認中と出す", () => {
    api.checkBackendHealth.mockReturnValue(new Promise(() => {}));
    render(<BackendStatus />);
    expect(screen.getByText("サーバー接続を確認中…")).toBeInTheDocument();
  });

  it("疎通できればOK", async () => {
    api.checkBackendHealth.mockResolvedValue(true);
    render(<BackendStatus />);
    expect(await screen.findByText("サーバー接続: OK")).toBeInTheDocument();
  });

  it("疎通できなければ、接続できないと出す", async () => {
    api.checkBackendHealth.mockResolvedValue(false);
    render(<BackendStatus />);
    expect(await screen.findByText("サーバーに接続できません")).toBeInTheDocument();
  });

  it("立ち上げ直しで問い合わせが2回走っても、後から届いた古い方の答えで上書きしない", async () => {
    let answerFirst!: (ok: boolean) => void;
    api.checkBackendHealth
      .mockReturnValueOnce(new Promise<boolean>((resolve) => (answerFirst = resolve)))
      .mockResolvedValueOnce(true);

    render(
      <StrictMode>
        <BackendStatus />
      </StrictMode>,
    );
    expect(await screen.findByText("サーバー接続: OK")).toBeInTheDocument();
    expect(api.checkBackendHealth).toHaveBeenCalledTimes(2);

    await act(async () => answerFirst(false));
    expect(screen.getByText("サーバー接続: OK")).toBeInTheDocument();
  });
});
