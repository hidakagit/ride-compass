import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ fetchJmaTileIndex: vi.fn(), setJmaTileIndex: vi.fn() }));
vi.mock("@/services/weatherApi", () => ({ fetchJmaTileIndex: mocks.fetchJmaTileIndex }));
vi.mock("@/features/map/layers/jmaTileProtocol", () => ({ setJmaTileIndex: mocks.setJmaTileIndex }));

import { useJmaTileIndex } from "./useJmaTileIndex";

describe("useJmaTileIndex", () => {
  it("取れるまではインデックス無しを渡し、取れたらタイルの横取り側へ渡す", async () => {
    const index = { available: true, coverage: null, elements: {} };
    mocks.fetchJmaTileIndex.mockResolvedValue(index);
    renderHook(() => useJmaTileIndex());
    expect(mocks.setJmaTileIndex).toHaveBeenLastCalledWith(null);
    await act(async () => {
      for (let i = 0; i < 10; i += 1) await Promise.resolve();
    });
    expect(mocks.setJmaTileIndex).toHaveBeenLastCalledWith(index);
  });
});
