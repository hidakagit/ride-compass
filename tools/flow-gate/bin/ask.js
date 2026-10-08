// Claude がユーザーに問う。問いの形（docs/conventions/flow.md「問い」）を確かめて、src/move.js: askTask で書く。
// --deployed <Pull Request の番号> を付けると、そのマージのコミットが本番に出るまで問いを置かない（src/deployed.js: askDeployed）。
// 本番に出たかは、frontend は /api/version の commit がマージを含むか、backend は /health の commit から見て
// scripts/deploy_backend_gate.py が「出さない」と言うか（backend のイメージに届く変更が無いマージは待たない）で見る。
// 宛先はコードのリポジトリの変数 coordinator.frontendVariable・backendVariable から取る（docs/architecture/tech-stack.md「本番の宛先」）。
// 終わりの値: 0 問うた（試しなら本番を1回見ただけ）・3 上限を過ぎて保留へ動かした（問いを置かずに終える）・4 まだ出ていない（打ち直す）。
import { execFileSync, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { askDeployed, withDeployed } from "../src/deployed.js";
import { askTask } from "../src/move.js";
import { normalize, parseQuestion } from "../src/rules.js";
import { args, bot, code, config, git, isNumber, repo } from "./cli.js";

const usage = "node tools/flow-gate/bin/ask.js [--deployed <Pull Request の番号> [--dry-run]] <issue の番号> <問いのファイル>";
const { dry, rest } = args(usage, (a) => (a[0] === "--deployed" ? a.length === 4 && isNumber(a[1]) && isNumber(a[2]) : a.length === 2 && isNumber(a[0])));
const [pr, number, file] = rest[0] === "--deployed" ? rest.slice(1) : [null, ...rest];
const question = normalize(readFileSync(file, "utf8")).trim();
if (!parseQuestion(question)) throw new Error("問いが形（docs/conventions/flow.md「問い」）に合いません。");
if (!pr) {
  console.log(await askTask(bot(), config, Number(number), question));
  process.exit(0);
}

const codeRepo = code();
const { repository, base } = config.code;
const got = await codeRepo.rest("GET", `/repos/${repository}/pulls/${pr}`);
if (!got.merged_at) throw new Error(`Pull Request #${pr} はマージされていません。`);
const merge = { number: Number(pr), sha: got.merge_commit_sha, mergedAt: got.merged_at };
const origin = async (name) => (await codeRepo.rest("GET", `/repos/${repository}/actions/variables/${name}`)).value.replace(/\/$/, "");
const [frontendOrigin, backendOrigin] = [await origin(config.coordinator.frontendVariable), await origin(config.coordinator.backendVariable)];
const commitAt = (url) => fetch(url, { signal: AbortSignal.timeout(30e3) }).then((r) => (r.ok ? r.json() : {})).then((j) => j.commit ?? null, () => null);

async function look() {
  const [frontend, backend] = await Promise.all([commitAt(`${frontendOrigin}/api/version`), commitAt(`${backendOrigin}/health`)]);
  try {
    git("fetch", "-q", "origin", base); // 本番のコミットはマージより後の master のことがある
  } catch {
    // 取れなければ手元にある分で見る（本番のコミットが手元に無ければ、出ていないと見て待つ）
  }
  const frontendHas = Boolean(frontend) && spawnSync("git", ["-C", repo, "merge-base", "--is-ancestor", merge.sha, frontend]).status === 0;
  // GITHUB_OUTPUT を空にして、担当の段の出力へ判定を書かせない。
  const backendHas = Boolean(backend) && execFileSync("python", [join(repo, "scripts/deploy_backend_gate.py"), backend, merge.sha],
    { cwd: repo, encoding: "utf8", env: { ...process.env, GITHUB_OUTPUT: "" } }).startsWith("出さない");
  return { ok: frontendHas && backendHas, frontend, backend };
}

if (dry) {
  const seen = await look();
  console.log(`（試し）#${number}: 本番に${seen.ok ? "出ている" : "まだ出ていない"}（frontend ${seen.frontend ?? "読めない"}・backend ${seen.backend ?? "読めない"}・マージ ${merge.sha}）`);
  if (seen.ok) console.log(withDeployed(question, seen, merge, Date.now()));
  process.exit(0);
}
// Bash の1回の上限（10分）の中で返す。
const { kind, text } = await askDeployed(bot(), config, Number(number), question, { merge, look, stopAt: Date.now() + 9 * 60e3 });
console.log(text);
process.exit({ 問うた: 0, 上限: 3, まだ: 4 }[kind]);
