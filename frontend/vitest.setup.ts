import { format } from "node:util";
import { BroadcastChannel } from "node:worker_threads";
import { afterAll, afterEach, beforeAll } from "vitest";

// mswは読み込んだ時点で`BroadcastChannel`を使う。`pool: "vmThreads"`のテストの文脈にはNodeのそれが無いので、先に置いてから読み込む。
globalThis.BroadcastChannel ??= BroadcastChannel as unknown as typeof globalThis.BroadcastChannel;
const { backendServer, closeHeldReplies } = await import("@/testing/backendServer");

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

// backendとの通信は網の層で差し替える（`src/testing/backendServer.ts`）。応答を与えていない要求はテストを落とす
// （黙って本物の網へ出すと、テストが通るかが手元の網の具合で変わる）。既定の`"error"`は、拡張子が静的なファイルの
// もの（`.json`等。mswの`isCommonAssetRequest`）を落とさずに本物の網へ流すので、関数で渡してどの要求も落とす。
beforeAll(() =>
  backendServer.listen({
    onUnhandledFrame: async ({ defaults }) => {
      await defaults.error();
      throw new Error("応答を与えていない要求は網へ出さない");
    },
  }),
);
// テストの終わりに`fetch`へ出たばかりの要求は、mswへ届く前に応答を片付けると、次のテストの応答に当たる（次のテストが
// 受けた要求を数え違え、応答の無い要求として関係の無いテストを落とす）。mswは要求が届いた時点（`request:start`）の
// 応答で答えるので、描いたものを外したあと（後に足した`afterEach`が先に走る）、出た要求が全部届いてから片付ける。
// 応答の無い要求の失敗も、警告の確かめ（上の`failOnWarnings`。先に足したので後に走る）より前に出させる。
// 届く前に`fetch`ごと失敗した要求は届かないので、待つのは決まった回数までにする。
// 数える包みはmswの`listen()`より前に置くが、mswは`fetch`を包んでも包む前の`fetch`（この包み）を必ず呼び、
// 横取りは網の層で行う（`@mswjs/interceptors`の`FetchInterceptor`）ので、横取りした要求も数える。
let sentToFetch = 0;
let reachedServer = 0;
const fetchOfEnvironment = globalThis.fetch;
globalThis.fetch = (...args: Parameters<typeof fetch>) => {
  sentToFetch += 1;
  return fetchOfEnvironment(...args);
};
backendServer.events.on("request:start", () => (reachedServer += 1));
afterEach(async () => {
  let turn = 0;
  do await new Promise((resolve) => setTimeout(resolve, 0));
  while (reachedServer < sentToFetch && ++turn < 50);
  closeHeldReplies();
  backendServer.resetHandlers();
});
afterAll(() => backendServer.close());

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
