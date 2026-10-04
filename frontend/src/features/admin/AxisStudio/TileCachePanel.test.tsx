/**
 * `TileCachePanel.tsx`——押したときだけタイルキャッシュを消し、消したこと（反映の時機つき）か失敗の理由を出す。
 *
 * ここで見ないもの:
 * - 叩く先 → `app/admin/adminApi.test.ts`
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { heldReplies, inTurn, onSameOrigin } from "@/testing/backendServer";

import TileCachePanel from "./TileCachePanel";

const CLEAR = "タイルキャッシュを消去する";
const REFRESH = "/admin/api/basemap/refresh";
const cleared = () => Response.json({});
const failed = (detail: string) => Response.json({ detail }, { status: 500 });

describe("TileCachePanel", () => {
  it("押すまで消さない。消去中は押せず、終わると消したことと反映の時機を出す", async () => {
    const held = heldReplies();
    const sent = onSameOrigin("POST", REFRESH, held.reply);
    const user = userEvent.setup();
    render(<TileCachePanel />);
    expect(sent).toEqual([]);

    await user.click(screen.getByRole("button", { name: CLEAR }));
    expect(screen.getByRole("button", { name: "消去中…" })).toBeDisabled();

    await held.answer(0, cleared());
    expect(await screen.findByText(/^消去しました。/)).toHaveTextContent("Cache-Control");
    expect(screen.getByRole("button", { name: CLEAR })).toBeEnabled();
    expect(sent).toHaveLength(1);
  });

  it("失敗したら理由を出し、消したとは言わない。押し直して成功すれば理由は消える", async () => {
    onSameOrigin("POST", REFRESH, inTurn(failed("タイルキャッシュの消去に失敗しました"), cleared()));
    const user = userEvent.setup();
    render(<TileCachePanel />);

    await user.click(screen.getByRole("button", { name: CLEAR }));
    expect(await screen.findByText("タイルキャッシュの消去に失敗しました")).toBeInTheDocument();
    expect(screen.queryByText(/^消去しました。/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: CLEAR }));
    expect(await screen.findByText(/^消去しました。/)).toBeInTheDocument();
    expect(screen.queryByText("タイルキャッシュの消去に失敗しました")).not.toBeInTheDocument();
  });

  it("成功のあとに押し直して失敗したら、前の成功の表示は消す", async () => {
    onSameOrigin("POST", REFRESH, inTurn(cleared(), failed("timeout")));
    const user = userEvent.setup();
    render(<TileCachePanel />);
    await user.click(screen.getByRole("button", { name: CLEAR }));
    await screen.findByText(/^消去しました。/);

    await user.click(screen.getByRole("button", { name: CLEAR }));
    expect(await screen.findByText("timeout")).toBeInTheDocument();
    expect(screen.queryByText(/^消去しました。/)).not.toBeInTheDocument();
  });
});
