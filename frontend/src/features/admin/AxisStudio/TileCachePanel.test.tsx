/**
 * `TileCachePanel.tsx`——押したときだけタイルキャッシュを消し、消したこと（反映の時機つき）か失敗の理由を出す。
 *
 * ここで見ないもの:
 * - 叩く先 → `features/admin/adminApi.test.ts`
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ refreshTileCache: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => api);

import TileCachePanel from "./TileCachePanel";

const CLEAR = "タイルキャッシュを消去する";

beforeEach(() => {
  api.refreshTileCache.mockReset();
});

describe("TileCachePanel", () => {
  it("押すまで消さない。消去中は押せず、終わると消したことと反映の時機を出す", async () => {
    let resolve!: () => void;
    api.refreshTileCache.mockReturnValue(new Promise<void>((res) => (resolve = res)));
    const user = userEvent.setup();
    render(<TileCachePanel />);
    expect(api.refreshTileCache).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: CLEAR }));
    expect(screen.getByRole("button", { name: "消去中…" })).toBeDisabled();

    resolve();
    expect(await screen.findByText(/^消去しました。/)).toHaveTextContent("Cache-Control");
    expect(screen.getByRole("button", { name: CLEAR })).toBeEnabled();
  });

  it("失敗したら理由を出し、消したとは言わない。押し直して成功すれば理由は消える", async () => {
    api.refreshTileCache.mockRejectedValueOnce(new Error("タイルキャッシュの消去に失敗しました"));
    const user = userEvent.setup();
    render(<TileCachePanel />);

    await user.click(screen.getByRole("button", { name: CLEAR }));
    expect(await screen.findByText("タイルキャッシュの消去に失敗しました")).toBeInTheDocument();
    expect(screen.queryByText(/^消去しました。/)).not.toBeInTheDocument();

    api.refreshTileCache.mockResolvedValueOnce(undefined);
    await user.click(screen.getByRole("button", { name: CLEAR }));
    expect(await screen.findByText(/^消去しました。/)).toBeInTheDocument();
    expect(screen.queryByText("タイルキャッシュの消去に失敗しました")).not.toBeInTheDocument();
  });

  it("成功のあとに押し直して失敗したら、前の成功の表示は消す。Error以外の失敗も値を出す", async () => {
    api.refreshTileCache.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<TileCachePanel />);
    await user.click(screen.getByRole("button", { name: CLEAR }));
    await screen.findByText(/^消去しました。/);

    api.refreshTileCache.mockRejectedValueOnce("timeout");
    await user.click(screen.getByRole("button", { name: CLEAR }));
    expect(await screen.findByText("timeout")).toBeInTheDocument();
    expect(screen.queryByText(/^消去しました。/)).not.toBeInTheDocument();
  });
});
