// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { GET } from "./route";

describe("GET /api/version", () => {
  const originalCommit = process.env.RENDER_GIT_COMMIT;

  afterEach(() => {
    if (originalCommit === undefined) {
      delete process.env.RENDER_GIT_COMMIT;
    } else {
      process.env.RENDER_GIT_COMMIT = originalCommit;
    }
  });

  it("returns status ok and a valid ISO started_at timestamp", async () => {
    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.status).toBe("ok");
    expect(typeof body.started_at).toBe("string");
    expect(Number.isNaN(new Date(body.started_at).getTime())).toBe(false);
  });

  it("returns commit as null when RENDER_GIT_COMMIT is not set", async () => {
    delete process.env.RENDER_GIT_COMMIT;

    const response = await GET();
    const body = await response.json();

    expect(body.commit).toBeNull();
  });

  it("reflects RENDER_GIT_COMMIT when set (Render本番相当)", async () => {
    process.env.RENDER_GIT_COMMIT = "abc1234def5678";

    const response = await GET();
    const body = await response.json();

    expect(body.commit).toBe("abc1234def5678");
  });
});
