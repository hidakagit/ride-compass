/**
 * `BackendStatus.tsx`——backendの疎通を、確認中・OK・接続できないの3つで出すこと。
 *
 * ここで見ないもの:
 * - 疎通の判定（応答の読み方・失敗を偽にすること） → `app/admin/adminApi.test.ts`
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { heldReplies, onBackend } from "@/testing/backendServer";

import BackendStatus from "./BackendStatus";

describe("BackendStatus", () => {
  it("答えが来るまでは確認中と出す", () => {
    onBackend("GET", "/health", heldReplies().reply);
    render(<BackendStatus />);
    expect(screen.getByText("サーバー接続を確認中…")).toBeInTheDocument();
  });

  it("疎通できればOK", async () => {
    onBackend("GET", "/health", () => Response.json({ status: "ok" }));
    render(<BackendStatus />);
    expect(await screen.findByText("サーバー接続: OK")).toBeInTheDocument();
  });

  it("疎通できなければ、接続できないと出す", async () => {
    onBackend("GET", "/health", () => new Response(null, { status: 503 }));
    render(<BackendStatus />);
    expect(await screen.findByText("サーバーに接続できません")).toBeInTheDocument();
  });
});
