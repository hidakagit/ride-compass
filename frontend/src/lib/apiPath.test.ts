// @vitest-environment node
import { describe, expect, it } from "vitest";
import { apiPath } from "./apiPath";

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
