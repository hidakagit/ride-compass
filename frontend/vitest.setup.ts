import { afterAll, afterEach } from "vitest";

// DOMを使わないテスト（`// @vitest-environment node`docblock付き）では
// Testing Library自体が不要なため読み込まない。
if (typeof window !== "undefined") {
  // 地図に重なる部品は、親が`pointer-events: none`で地図の操作を通し、押せる部品だけがTailwindの
  // `pointer-events-auto`で戻す。テスト環境はTailwindのプラグインを通さず、その規則を作らないため、
  // この1つだけを置く——無いと親の`none`だけが見え、押せるはずのボタンを押せないと判定される。
  document.head.insertAdjacentHTML("beforeend", "<style>.pointer-events-auto{pointer-events:auto}</style>");
  await import("@testing-library/jest-dom/vitest");
  const { cleanup } = await import("@testing-library/react");
  afterEach(() => {
    cleanup();
  });
}

// `pool: "vmThreads"`のため`process.env`はテストファイルをまたいで共有される。あるファイルが
// 立てたままにした環境変数は、並行実行中の別ファイルの期待値をその場で変える——単体では通るのに
// フルスイートでだけ落ちるテストになり、毎回同じ顔で落ちないため本物の退行を隠す。
//
// 「誰が読むか」は実行時には分からないので、**漏れたかどうか**を見る。ファイルの終わりに
// 開始時と違っていれば、そのファイルが漏らしている（`vi.stubEnv`のように復元されるものは通る）。
const ENV_AT_START = { ...process.env };

// `process.env`ごとの差し替え（`process.env = { ...ORIGINAL }`）は`vi.stubEnv`の復元まで壊すため、
// 束縛自体を固定して早い段階で落とす。
Object.defineProperty(process, "env", { value: process.env, writable: false, configurable: false });

afterAll(() => {
  const changed: string[] = [];
  for (const key of new Set([...Object.keys(ENV_AT_START), ...Object.keys(process.env)])) {
    if (ENV_AT_START[key] !== process.env[key]) {
      changed.push(`${key}: ${JSON.stringify(ENV_AT_START[key])} → ${JSON.stringify(process.env[key])}`);
    }
  }
  if (changed.length > 0) {
    throw new Error(
      "このテストファイルが`process.env`を変えたまま終わった。" +
        "共有されるため、並行実行中の別ファイルの期待値が変わる" +
        "（判断を環境変数を引数で受ける純関数へ出し、テストはその純関数を呼ぶ。" +
        "docs/conventions/testing.md パターン7）:\n  " +
        changed.join("\n  "),
    );
  }
});
