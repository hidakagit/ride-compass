import { afterEach } from "vitest";

// DOMを使わないテスト（`// @vitest-environment node`docblock付き）では
// Testing Library自体が不要なため読み込まない。
if (typeof window !== "undefined") {
  await import("@testing-library/jest-dom/vitest");
  const { cleanup } = await import("@testing-library/react");
  afterEach(() => {
    cleanup();
  });
}
