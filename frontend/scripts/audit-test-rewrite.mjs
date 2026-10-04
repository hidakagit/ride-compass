// 起こし直したテストを外から測る（docs/conventions/testing.md「既存テストを直さず、実装から起こし直す」の手順3）。
//
//   node scripts/audit-test-rewrite.mjs <実装のファイル> [テストのファイル...] [--ref <git の版>]
//
// 出すもの: テストの本数（実行した数。it.each は展開した後）・テストの行数・行と分岐のカバレッジ・届いていない行と分岐・
// テストごとの「そのテストだけが届く行」。パスは frontend からの相対で渡す。
// テストを渡さなければ、母集団を集める: src の *.test.ts(x) のうち、import の指定子が「/<実装のファイル名から拡張子を除いたもの>」
// で終わるもの（間接に通すテストは入らないので、要れば並べて渡す）。
// --ref は「前」の値を測る（例: --ref origin/master）。母集団をその版から集め、その版のテストを元のテストの隣へ一時の名前で
// 書き出して流し、終わったら消す。実装はその版と同じでなければならない（起こし直しは実装を変えない）。
// 1本だけ流すのは、vitest の -t が describe と題名を「 > 」でつないだ名前に当てるため、その形で絞る。
// 絞って1本も流れなければ（どれも skipped）、0行とせずに落とす。

import { execFileSync, spawnSync } from "node:child_process";
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
  options: { ref: { type: "string" } },
});
const [implementation, ...givenTests] = positionals.map((p) => p.replaceAll("\\", "/"));
if (!implementation)
  fail("<実装のファイル> が要る（frontend からの相対。例: src/components/ui/Checkbox/Checkbox.tsx）");
if (!existsSync(path.join(frontendRoot, implementation))) fail(`実装のファイルが無い: ${implementation}`);

function git(args) {
  return execFileSync("git", args, { cwd: frontendRoot, encoding: "utf-8", maxBuffer: 1 << 30 });
}

/** 版 ref（無ければ作業ツリー）で、実装の名前を import の指定子の末尾に持つテスト。 */
function collectPopulation(ref) {
  const name = path.basename(implementation).replace(/\.[^.]+$/, "");
  const pattern = `/${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["']`;
  // 作業ツリーでは、まだ追跡していない起こし直したテストも拾う。
  const args = [
    "grep",
    ...(ref ? [] : ["--untracked"]),
    "-lE",
    pattern,
    ...(ref ? [ref] : []),
    "--",
    "src/**/*.test.ts",
    "src/**/*.test.tsx",
  ];
  const result = spawnSync("git", args, { cwd: frontendRoot, encoding: "utf-8" });
  if (result.status !== 0 && result.status !== 1) fail(`母集団を集められない: ${result.stderr}`);
  // git grep は版を付けると「<版>:<frontend からのパス>」で返す。
  return result.stdout
    .split("\n")
    .filter(Boolean)
    .map((line) => (ref ? line.slice(ref.length + 1) : line));
}

/** --ref の版のテストを元の隣へ書き出し、流すパスの並びを返す。書き出したものは終わるときに消す。 */
function writeRefTests(ref, tests) {
  try {
    git(["diff", "--quiet", ref, "--", implementation]);
  } catch {
    fail(`実装が ${ref} と違う。前の値は実装を変える前に測る: ${implementation}`);
  }
  const written = [];
  process.on("exit", () => written.forEach((file) => rmSync(path.join(frontendRoot, file), { force: true })));
  for (const test of tests) {
    const temporary = test.replace(/\.test\.(tsx?)$/, ".audit-before.test.$1");
    if (!existsSync(path.dirname(path.join(frontendRoot, test))))
      fail(`${ref} のテストの置き場が作業ツリーに無い: ${test}`);
    writeFileSync(path.join(frontendRoot, temporary), git(["show", `${ref}:frontend/${test}`]));
    written.push(temporary);
  }
  process.on("SIGINT", () => process.exit(130));
  return written;
}

const workDir = mkdtempSync(path.join(os.tmpdir(), "ridecompass-audit-"));
process.on("exit", () => rmSync(workDir, { recursive: true, force: true }));

/** テストを流し、実行した（passed・failed の）テストと、対象のカバレッジを返す。 */
function runVitest(files, namePattern) {
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
      `--coverage.include=${implementation}`,
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

const tests = givenTests.length > 0 ? givenTests : collectPopulation(values.ref);
if (tests.length === 0) fail(`母集団が空: ${implementation} を import するテストが無い`);
const missing = values.ref
  ? tests.filter(
      (test) =>
        spawnSync("git", ["cat-file", "-e", `${values.ref}:frontend/${test}`], { cwd: frontendRoot }).status !== 0,
    )
  : tests.filter((test) => !existsSync(path.join(frontendRoot, test)));
if (missing.length > 0) fail(`テストが無い${values.ref ? `（${values.ref}）` : ""}: ${missing.join(" ")}`);
const files = values.ref ? writeRefTests(values.ref, tests) : tests;

console.log(`対象: ${implementation}`);
console.log(`版:   ${values.ref ? `${values.ref} のテスト（実装は同じ）` : "作業ツリー"}`);
console.log(`母集団（${givenTests.length > 0 ? "渡したもの" : "import の指定子で集めたもの"}）:`);
let totalLines = 0;
tests.forEach((test, i) => {
  const lineCount = readFileSync(path.join(frontendRoot, files[i]), "utf-8").trimEnd().split("\n").length;
  totalLines += lineCount;
  console.log(`  ${test}（${lineCount}行）`);
});

const whole = runVitest(files);
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

const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const reachedBy = whole.executed.map((test) => {
  const alone = runVitest([test.file], `^${escape(test.name)}$`);
  if (alone.executed.length !== 1)
    fail(`1本に絞れない（${alone.executed.length}本流れた）: ${test.file} > ${test.name}`);
  return { test, lines: new Set([...lineHits(alone.coverage)].filter(([, count]) => count > 0).map(([line]) => line)) };
});
console.log("そのテストだけが届く行:");
for (const { test, lines } of reachedBy) {
  const only = [...lines].filter((line) => reachedBy.every((other) => other.test === test || !other.lines.has(line)));
  const label = values.ref ? test.file.replace(".audit-before.test.", ".test.") : test.file;
  console.log(`  ${label} > ${test.name}: ${ranges(only)}`);
}
