import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { onBackend } from "@/testing/backendServer";

const mocks = vi.hoisted(() => ({ setJmaTileIndex: vi.fn() }));
vi.mock("@/features/map/layers/jmaTileProtocol", () => ({ setJmaTileIndex: mocks.setJmaTileIndex }));

import { useJmaTileIndex } from "./useJmaTileIndex";

describe("useJmaTileIndex", () => {
  it("取れるまではインデックス無しを渡し、取れたらタイルの横取り側へ渡す", async () => {
    const index = { available: true, coverage: null, elements: {} };
    onBackend("GET", "/api/jma-tile-index", () => Response.json(index));
    renderHook(() => useJmaTileIndex());
    expect(mocks.setJmaTileIndex).toHaveBeenLastCalledWith(null);
    await waitFor(() => expect(mocks.setJmaTileIndex).toHaveBeenLastCalledWith(index));
  });
});
