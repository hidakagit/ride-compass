// @vitest-environment node
import { describe, expect, it } from "vitest";
import { apiPath, apiQuery } from "./apiPath";

describe("apiPath", () => {
  it("fills the named parts of a declared path", () => {
    expect(apiPath("/api/routes/generate/{job_id}", { job_id: "abc" })).toBe("/api/routes/generate/abc");
  });

  it("leaves the parts it was not given for the map library to fill", () => {
    expect(apiPath("/api/region/dynamic-way-values/{axis_id}/{z}/{x}/{y}", { axis_id: "wind" })).toBe(
      "/api/region/dynamic-way-values/wind/{z}/{x}/{y}",
    );
  });

  it("puts a value spanning several segments in as it is", () => {
    expect(apiPath("/api/basemap/{path}", { path: "styles/liberty" })).toBe("/api/basemap/styles/liberty");
  });

  it("refuses a path the backend does not declare", () => {
    // @ts-expect-error backendの宣言に無いパスは型検査で落ちる。
    apiPath("/api/no-such-endpoint");
    // @ts-expect-error 宣言に無い名前は埋められない。
    apiPath("/api/routes/generate/{job_id}", { id: "abc" });
  });
});

describe("apiQuery", () => {
  const path = "/api/region/dynamic-way-values/{axis_id}/{z}/{x}/{y}";

  it("puts the given items after a question mark and leaves out the empty ones", () => {
    expect(apiQuery(path, { bearing_deg: 90, at: undefined, speed_kmh: null })).toBe("?bearing_deg=90");
    expect(apiQuery("/api/admin/debug/logs", { contains: "jma tile" })).toBe("?contains=jma+tile");
  });

  it("gives an empty string when there is nothing to ask", () => {
    expect(apiQuery(path, {})).toBe("");
    expect(apiQuery("/api/admin/debug/logs", { contains: "" })).toBe("");
  });

  it("refuses an item the backend does not declare for that path", () => {
    // @ts-expect-error 宣言に無い項目の名前は型検査で落ちる。
    apiQuery(path, { bearing: 90 });
    // @ts-expect-error 必須の項目を欠くと型検査で落ちる。
    apiQuery("/api/weather", { latitude: 35 });
  });
});
