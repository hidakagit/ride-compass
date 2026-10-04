import { format } from "node:util";
import { afterAll, afterEach } from "vitest";

// 警告は既定でエラー（docs/conventions/testing.md「警告は既定でエラー」）。`console.warn`・`console.error`へ出たもの
// （Reactの警告もここへ届く）は、出したテストを落とす。vitestには出力の警告で落とす設定が無いため、ここで受ける。
// 直せない警告だけを、文で名指して下の一覧へ載せる（1件ずつ、理由と外せる条件を添える）。
// テストが`vi.spyOn(console, ...)`で差し替えている間は、そのテストが出力を受け持つ。
const ALLOWED_WARNINGS: readonly { message: RegExp; reason: string; removeWhen: string }[] = [];

const warnings: string[] = [];
for (const level of ["warn", "error"] as const) {
  const original = console[level];
  console[level] = (...args: unknown[]) => {
    original(...args);
    const text = format(...args);
    if (!ALLOWED_WARNINGS.some((allowed) => allowed.message.test(text))) warnings.push(`console.${level}: ${text}`);
  };
}

function failOnWarnings(): void {
  if (warnings.length === 0) return;
  const found = warnings.splice(0);
  throw new Error(
    `警告が${found.length}件出た。直すか、直せなければ vitest.setup.ts: ALLOWED_WARNINGS へ文で名指して載せる:\n  ` +
      found.join("\n  "),
  );
}

// テストの外（ファイルの読み込み・afterAll）で出たものは、ファイルの終わりに落とす。
afterEach(failOnWarnings);
afterAll(failOnWarnings);

// DOMを使わないテスト（`// @vitest-environment node`docblock付き）では
// Testing Library自体が不要なため読み込まない。
if (typeof window !== "undefined") {
  // 地図に重なる部品は、親が`pointer-events: none`で地図の操作を通し、押せる部品だけがTailwindの
  // `pointer-events-auto`で戻す。テスト環境はTailwindのプラグインを通さず、その規則を作らないため、
  // この1つだけを置く——無いと親の`none`だけが見え、押せるはずのボタンを押せないと判定される。
  document.head.insertAdjacentHTML("beforeend", "<style>.pointer-events-auto{pointer-events:auto}</style>");
  await import("@testing-library/jest-dom/vitest");
  const { cleanup } = await import("@testing-library/react");
  const { getQueryClient } = await import("@/lib/queryClient");
  afterEach(() => {
    cleanup();
    // 画面のデータ取得のキャッシュはファイルの中のテストをまたいで残るため、描いたものを外したあとに空にする
    // （残すと、前のテストで届いた値が次のテストの取得の代わりに出る）。
    getQueryClient().clear();
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
