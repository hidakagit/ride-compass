import { readFileSync } from "node:fs";
import { join } from "node:path";

/** backend の契約（生成物`types/generated/openapi.json`）のうち、テストが読む所。 */
interface OpenApiDocument {
  paths: Record<string, Record<string, unknown>>;
  components: { schemas: Record<string, { properties?: Record<string, unknown> }> };
}

/** backend の契約。画面の口と型が契約と合うかを見るテストが読む（JSON の import にすると、型検査が全体を型にする）。 */
export const openApi: OpenApiDocument = JSON.parse(
  readFileSync(join(__dirname, "../types/generated/openapi.json"), "utf-8"),
);
