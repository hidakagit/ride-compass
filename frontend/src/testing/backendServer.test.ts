/**
 * `testing/backendServer.ts`——網の層の差し替えの手引き。応答を与えた経路に答えて届いた要求を積むこと・順に返すこと・
 * 応えるまで待たせて、応えなかった要求をテストの終わりに閉じること。応答を与えていない要求が網へ出ずに落ちること
 * （`vitest.setup.ts`の設定）もここで見る。
 */
import { describe, expect, it, vi } from "vitest";

import { API_BASE_URL } from "@/lib/apiBaseUrl";

import { closeHeldReplies, heldReplies, inTurn, onBackend, onSameOrigin } from "./backendServer";

describe("onBackend・onSameOrigin", () => {
  it("backendの経路に答え、届いた要求のメソッド・パス・問い合わせ・本文を順に積む", async () => {
    const sent = onBackend("POST", "/api/items/:id", ({ body }) => Response.json({ echoed: body }));

    const response = await fetch(`${API_BASE_URL}/api/items/7?mode=a`, {
      method: "POST",
      body: JSON.stringify({ name: "x" }),
    });

    await expect(response.json()).resolves.toEqual({ echoed: { name: "x" } });
    expect(sent).toEqual([{ method: "POST", path: "/api/items/7", query: { mode: "a" }, body: { name: "x" } }]);
  });

  it("同じオリジンの経路は、相対パスの要求に答える", async () => {
    onSameOrigin("GET", "/admin/api/status", () => Response.json({ ok: true }));

    await expect((await fetch("/admin/api/status")).json()).resolves.toEqual({ ok: true });
  });
});

describe("inTurn", () => {
  it("届いた順に返し、尽きたら最後のものを返し続ける", async () => {
    onBackend("GET", "/api/turn", inTurn(Response.json(1), Response.json(2)));
    const next = async () => (await fetch(`${API_BASE_URL}/api/turn`)).json();

    expect([await next(), await next(), await next()]).toEqual([1, 2, 2]);
  });
});

describe("heldReplies", () => {
  it("応えるまで答えず、届いた順の番目に応える", async () => {
    const held = heldReplies();
    onBackend("GET", "/api/held", held.reply);

    const first = fetch(`${API_BASE_URL}/api/held`);
    const second = fetch(`${API_BASE_URL}/api/held`);
    await held.answer(1, Response.json("second"));
    await held.answer(0, Response.json("first"));

    expect([await (await first).json(), await (await second).json()]).toEqual(["first", "second"]);
  });

  it("応えなかった要求は、閉じると網の失敗になる", async () => {
    const held = heldReplies();
    onBackend("GET", "/api/held", held.reply);
    const pending = fetch(`${API_BASE_URL}/api/held`);
    await vi.waitFor(() => expect(held.arrived()).toBe(1));

    closeHeldReplies();

    await expect(pending).rejects.toThrow();
  });

  it("閉じる応答を渡した要求は、閉じるとその応答になる", async () => {
    const held = heldReplies(() => Response.json("closed"));
    onBackend("GET", "/api/held", held.reply);
    const pending = fetch(`${API_BASE_URL}/api/held`);
    await vi.waitFor(() => expect(held.arrived()).toBe(1));

    closeHeldReplies();

    await expect((await pending).json()).resolves.toBe("closed");
  });
});

describe("応答を与えていない要求", () => {
  it.each([["/api/unknown"], ["/api/unknown.json"]])(
    "%s は網へ出さずに失敗させ、知らせを出す（拡張子が静的なファイルのものも）",
    async (path) => {
      const printed = vi.spyOn(console, "error").mockImplementation(() => {});

      const succeeded = await fetch(`${API_BASE_URL}${path}`).then(
        (response) => response.ok,
        () => false,
      );

      expect(succeeded).toBe(false);
      expect(printed).toHaveBeenCalledWith(expect.stringContaining("without a matching request handler"));
      printed.mockRestore();
    },
  );
});
