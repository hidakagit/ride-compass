// 起こし直したテストを外から測る（.claude/rules/testing.md「既存テストを直さず、実装から起こし直す」の手順3）。
//
//   node scripts/audit-test-rewrite.mjs <実装のファイル> [テストのファイル...] [--summary]
//
// 出すもの: 実装を変えていないか（①）・テストの本数（実行した数。it.each は展開した後）・テストの行数・行と分岐のカバレッジ・届いていない行と分岐・
// テストごとの「そのテストだけが届く行」。パスは frontend からの相対で渡す。
// テストを渡さなければ、母集団を集める: src の *.test.ts(x) のうち、import の指定子（相対・@/）をテストの位置から解決すると
// 渡した実装のパスになるもの（間接に通すテストは入らないので、要れば並べて渡す）。
// --summary は「そのテストだけが届く行」を出さない。それはテストを1本ずつ流して取るので、母集団の本数に比例して時間がかかる。
// 起こし直しの報告と完了の条件は全体の値と届いていない行・分岐で足り、テストごとの値は見落としを探す場面でだけ要るので、
// 全体の値だけでよいときに付ける。
// 1本だけ流すのは、vitest の -t が describe と題名を「 > 」でつないだ名前に当てるため、その形で絞る。
// 絞って1本も流れなければ（どれも skipped）、0行とせずに落とす。
// 実装が *.test.ts(x) のとき（src/structure のように検査の本体がテストファイルの中にあるもの）は、そのファイルが母集団の
// 全部で、テストを渡さない（渡すならそのファイルだけ）。vitest はテストの include に当たるファイルを coverage.exclude へ
// 必ず足し、設定では外せないので、同じ置き場へテストでない名前（.audit-copy）で写し、それを import するだけのテスト
// （.audit-run.test。元の @vitest-environment を継ぐ）から流して写しを測り、終わったら消す。写しは元と同じ行なので、
// 届いていない行は元のファイルの行番号で出る。
// この数え方では、テストの本体（it に渡した関数の中の文）も実装の行と分岐に入る。テストを消すと、その本体の行は
// 届いていない行にならず分母から消える。

import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const frontendRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const vitest = path.join(frontendRoot, "node_modules", "vitest", "vitest.mjs");

function fail(message) {
  console.error(`[audit] ${message}`);
  process.exit(1);
}

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: { summary: { type: "boolean" } },
});
const [implementation, ...givenTests] = positionals.map((p) => p.replaceAll("\\", "/"));
if (!implementation)
  fail("<実装のファイル> が要る（frontend からの相対。例: src/components/ui/Checkbox/Checkbox.tsx）");
if (!existsSync(path.join(frontendRoot, implementation))) fail(`実装のファイルが無い: ${implementation}`);
const testFile = /\.test\.(tsx?)$/;
const implementationIsTest = testFile.test(implementation);
if (implementationIsTest && givenTests.some((test) => test !== implementation))
  fail(`実装がテストファイルのときは、そのファイルだけを測る: ${implementation}`);

/**
 * 作業ツリーで、実装そのものを import するテスト。指定子（相対・`@/` の別名）をテストの位置から
 * 実装のパスへ解決して比べる（ファイル名だけで比べると、同じ名前の別の実装のテストが入る）。拡張子を省いた指定子と、
 * index を指すディレクトリの指定子も実装と同じとみなす。
 */
function collectPopulation() {
  const stem = implementation.replace(/\.[^./]+$/, "");
  const targets = new Set([implementation, stem]);
  if (path.posix.basename(stem) === "index") targets.add(path.posix.dirname(stem));
  const specifier = /(?:from|import)\s*\(?\s*["']([^"']+)["']/g;
  // 作業ツリーでは、まだ追跡していない起こし直したテストも拾う。
  const args = [
    "grep",
    "--untracked",
    "-E",
    `(from|import)[[:space:]]*\\(?[[:space:]]*["'][.@]`,
    "--",
    ":(glob)src/**/*.test.ts",
    ":(glob)src/**/*.test.tsx",
  ];
  const result = spawnSync("git", args, { cwd: frontendRoot, encoding: "utf-8", maxBuffer: 1 << 30 });
  if (result.status !== 0 && result.status !== 1) fail(`母集団を集められない: ${result.stderr}`);
  const population = new Set();
  // git grep は「<frontend からのパス>:<行>」で返す。
  for (const line of result.stdout.split("\n").filter(Boolean)) {
    const separator = line.indexOf(":");
    const test = line.slice(0, separator);
    for (const [, spec] of line.slice(separator + 1).matchAll(specifier)) {
      const resolved = spec.startsWith("@/")
        ? path.posix.join("src", spec.slice(2))
        : spec.startsWith(".")
          ? path.posix.join(path.posix.dirname(test), spec)
          : null;
      if (resolved && targets.has(resolved)) population.add(test);
    }
  }
  return [...population].sort();
}

const temporaryFiles = [];
process.on("exit", () => temporaryFiles.forEach((file) => rmSync(path.join(frontendRoot, file), { force: true })));
process.on("SIGINT", () => process.exit(130));

/** frontend からの相対の file へ一時のファイルを書く。書いたものは終わるときに消す。 */
function writeTemporary(file, content) {
  writeFileSync(path.join(frontendRoot, file), content);
  temporaryFiles.push(file);
}

/** 実装のテストファイルをテストでない名前へ写し、写しと、写しを流すテストのパスを返す。 */
function writeTestCopy() {
  const source = readFileSync(path.join(frontendRoot, implementation), "utf-8");
  const copy = implementation.replace(testFile, ".audit-copy.$1");
  const runner = implementation.replace(testFile, ".audit-run.test.$1");
  const environment = source.match(/@vitest-environment\s+(\S+)/);
  writeTemporary(copy, source);
  writeTemporary(
    runner,
    `${environment ? `// @vitest-environment ${environment[1]}\n` : ""}import "./${path.posix.basename(copy).replace(/\.tsx?$/, "")}";\n`,
  );
  return { copy, runner };
}

const workDir = mkdtempSync(path.join(os.tmpdir(), "ridecompass-audit-"));
process.on("exit", () => rmSync(workDir, { recursive: true, force: true }));

/** テストを流し、実行した（passed・failed の）テストと、measured のカバレッジを返す。 */
function runVitest(files, measured, namePattern) {
  const report = path.join(workDir, "report.json");
  const coverageDir = path.join(workDir, "coverage");
  rmSync(report, { force: true });
  rmSync(coverageDir, { recursive: true, force: true });
  const result = spawnSync(
    process.execPath,
    [
      vitest,
      "run",
      ...files,
      ...(namePattern ? ["-t", namePattern] : []),
      "--reporter=json",
      `--outputFile=${report}`,
      "--coverage.enabled",
      `--coverage.include=${measured}`,
      "--coverage.reporter=json",
      `--coverage.reportsDirectory=${coverageDir}`,
    ],
    { cwd: frontendRoot, encoding: "utf-8", maxBuffer: 1 << 30 },
  );
  if (!existsSync(report)) fail(`vitest が結果を書かなかった:\n${result.stderr}`);
  const executed = JSON.parse(readFileSync(report, "utf-8")).testResults.flatMap((file) =>
    file.assertionResults
      .filter((test) => test.status === "passed" || test.status === "failed")
      .map((test) => ({
        file: path.relative(frontendRoot, file.name).replaceAll("\\", "/"),
        name: [...test.ancestorTitles, test.title].join(" > "),
        status: test.status,
      })),
  );
  const failed = executed.filter((test) => test.status === "failed");
  if (failed.length > 0)
    fail(`落ちたテストがある。測った値は当てにならない:\n${failed.map((t) => `  ${t.file} > ${t.name}`).join("\n")}`);
  const coverage = Object.values(JSON.parse(readFileSync(path.join(coverageDir, "coverage-final.json"), "utf-8")))[0];
  if (!coverage) fail(`実装のカバレッジが出なかった: ${implementation}`);
  return { executed, coverage };
}

/** 行ごとの実行回数。istanbul と同じく、文の始まりの行にその行の文の最大の回数を置く。 */
function lineHits(coverage) {
  const lines = new Map();
  for (const [id, location] of Object.entries(coverage.statementMap)) {
    const line = location.start.line;
    lines.set(line, Math.max(lines.get(line) ?? 0, coverage.s[id]));
  }
  return lines;
}

/** 連続する行番号を「12-15」にまとめる。 */
function ranges(numbers) {
  const sorted = [...numbers].sort((a, b) => a - b);
  const out = [];
  for (const n of sorted) {
    const last = out.at(-1);
    if (last && last[1] === n - 1) last[1] = n;
    else out.push([n, n]);
  }
  return out.map(([a, b]) => (a === b ? `${a}` : `${a}-${b}`)).join(", ") || "なし";
}

const percent = (covered, total) => (total === 0 ? "100%" : `${((covered / total) * 100).toFixed(2)}%`);

const tests = implementationIsTest ? [implementation] : givenTests.length > 0 ? givenTests : collectPopulation();
if (tests.length === 0) fail(`母集団が空: ${implementation} を import するテストが無い`);
const missing = tests.filter((test) => !existsSync(path.join(frontendRoot, test)));
if (missing.length > 0) fail(`テストが無い: ${missing.join(" ")}`);
// lineSources は行数を数えるファイル、files は流すファイル、measured はカバレッジを取るファイル。
let lineSources, files, measured;
if (implementationIsTest) {
  const { copy, runner } = writeTestCopy();
  [lineSources, files, measured] = [[copy], [runner], copy];
} else {
  [lineSources, files, measured] = [tests, tests, implementation];
}

console.log(`対象: ${implementation}`);
// 実装の変更は origin/master との合流点から作業ツリーまでの差で見る（コミット済みの変更も含む）。
const base = spawnSync("git", ["merge-base", "origin/master", "HEAD"], { cwd: frontendRoot, encoding: "utf-8" });
if (base.status !== 0) {
  console.log(`① 実装の変更: **測れない**（origin/master との合流点が取れない: ${base.stderr.trim()}）`);
} else {
  const diff = spawnSync("git", ["diff", "--stat", base.stdout.trim(), "--", implementation], {
    cwd: frontendRoot,
    encoding: "utf-8",
  }).stdout.trim();
  console.log(`① 実装の変更（origin/master との合流点から）: ${diff ? `**あり** → ${diff}` : "なし"}`);
}
console.log(
  `母集団（${implementationIsTest ? "実装のテストファイルそのもの" : givenTests.length > 0 ? "渡したもの" : "import の指定子で集めたもの"}）:`,
);
let totalLines = 0;
tests.forEach((test, i) => {
  const lineCount = readFileSync(path.join(frontendRoot, lineSources[i]), "utf-8").trimEnd().split("\n").length;
  totalLines += lineCount;
  console.log(`  ${test}（${lineCount}行）`);
});

const whole = runVitest(files, measured);
const hits = lineHits(whole.coverage);
const coveredLines = [...hits].filter(([, count]) => count > 0).map(([line]) => line);
const uncoveredLines = [...hits].filter(([, count]) => count === 0).map(([line]) => line);
const branches = Object.entries(whole.coverage.branchMap).flatMap(([id, branch]) =>
  whole.coverage.b[id].map((count, index) => ({
    line: branch.line ?? branch.loc.start.line,
    type: branch.type,
    index,
    count,
  })),
);
const uncoveredBranches = branches.filter((branch) => branch.count === 0);

console.log(`テストの本数（実行した数）: ${whole.executed.length}`);
console.log(`テストの行数: ${totalLines}`);
console.log(`行カバレッジ: ${coveredLines.length}/${hits.size}（${percent(coveredLines.length, hits.size)}）`);
console.log(
  `分岐カバレッジ: ${branches.length - uncoveredBranches.length}/${branches.length}（${percent(branches.length - uncoveredBranches.length, branches.length)}）`,
);
console.log(`届いていない行: ${ranges(uncoveredLines)}`);
console.log(
  `届いていない分岐: ${uncoveredBranches.map((b) => `行${b.line} ${b.type} の${b.index + 1}つ目`).join("、") || "なし"}`,
);

if (values.summary) process.exit(0);

const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const reachedBy = whole.executed.map((test) => {
  const alone = runVitest([test.file], measured, `^${escape(test.name)}$`);
  if (alone.executed.length !== 1)
    fail(`1本に絞れない（${alone.executed.length}本流れた）: ${test.file} > ${test.name}`);
  return { test, lines: new Set([...lineHits(alone.coverage)].filter(([, count]) => count > 0).map(([line]) => line)) };
});
console.log("そのテストだけが届く行:");
for (const { test, lines } of reachedBy) {
  const only = [...lines].filter((line) => reachedBy.every((other) => other.test === test || !other.lines.has(line)));
  console.log(`  ${implementationIsTest ? implementation : test.file} > ${test.name}: ${ranges(only)}`);
}
