// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

const { setWorkerUrl } = vi.hoisted(() => ({ setWorkerUrl: vi.fn() }));
vi.mock("maplibre-gl", () => ({ setWorkerUrl }));

import { configureMaplibreWorker } from "./maplibreWorker";

describe("configureMaplibreWorker", () => {
  it("Workerの場所を、ビルド前に置いた複製へ1度だけ向ける", () => {
    configureMaplibreWorker();
    configureMaplibreWorker();
    expect(setWorkerUrl).toHaveBeenCalledTimes(1);
    expect(setWorkerUrl).toHaveBeenCalledWith("/maplibre/maplibre-gl-worker.mjs");
  });
});
