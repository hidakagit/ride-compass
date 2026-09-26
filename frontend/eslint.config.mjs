import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// 層の読む向き（docs/architecture/directory-layout.md「frontend」）。上から順に並べ、各層はそれより上の層を読まない。
const LAYERS = ["app", "features", "components", "hooks", "services", "lib"];
const LAYOUT_DOC = "docs/architecture/directory-layout.md「frontend」";

const layerZones = LAYERS.slice(1).map((layer, index) => ({
  target: `./src/${layer}`,
  from: LAYERS.slice(0, index + 1).map((upper) => `./src/${upper}`),
  message: `${layer}/は上の層を読まない（${LAYOUT_DOC}）`,
}));

// 機能の一覧はディレクトリから取り、機能を足しても設定を書き足さずに境界が効く。
const featureZones = readdirSync(new URL("./src/features", import.meta.url), { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map(({ name }) => ({
    target: `./src/features/${name}`,
    from: "./src/features",
    except: [`./${name}`],
    message: `機能どうしは互いを読まない。2つの機能が要るものは共有の層へ下ろす（${LAYOUT_DOC}）`,
  }));

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["src/**/*.{ts,tsx,mts}"],
    rules: {
      "import/no-restricted-paths": [
        "error",
        { basePath: fileURLToPath(new URL(".", import.meta.url)), zones: [...layerZones, ...featureZones] },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
