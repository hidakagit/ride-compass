// 担当のワークフロー（.github/workflows/claude-task.yml）の最初の段。作るなら、未着手で前提（blocked by）が全部閉じていて、未着手 → 進行中が通ったときだけ、
// 確かめるなら検証中のときだけ引き受け、issue に着手を書く（src/after.js: startReport）。引き受けたら 0、引き受けなければ 1 で終わる。
// 使い方: node tools/flow-gate/bin/claim.js <issue の番号> <作る|確かめる> <実行の URL>
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import config from "../flow.config.json" with { type: "json" };
import { refusal, startReport } from "../src/after.js";
import { GitHub, readTask } from "../src/github.js";
import { openBlockers } from "../src/rules.js";
import { botToken } from "./token.js";

const [number, kind, url, ...rest] = process.argv.slice(2);
if (!/^\d+$/.test(number ?? "") || !["作る", "確かめる"].includes(kind) || !url || rest.length) {
  console.error("使い方: node tools/flow-gate/bin/claim.js <issue の番号> <作る|確かめる> <実行の URL>");
  process.exit(2);
}
const gh = new GitHub(botToken());
if (kind === "作る") {
  const { issue } = await readTask(gh, config, { number: Number(number) });
  const open = issue ? openBlockers(issue.blockedBy.nodes) : [];
  if (issue?.status !== config.todo || open.length) {
    console.log(`作らずに終わる（${issue?.status ?? "置き場に無い"}${open.length ? `・前提 ${open.map((b) => `#${b.number}`).join("・")} が開いている` : ""}）`);
    process.exit(1);
  }
  try {
    console.log(execFileSync(process.execPath, [join(dirname(fileURLToPath(import.meta.url)), "move.js"), number, config.working], { encoding: "utf8" }).trim());
  } catch (e) {
    console.log(`未着手ではないので、作らずに終わる（${refusal(e)}）`);
    process.exit(1);
  }
} else {
  const { issue } = await readTask(gh, config, { number: Number(number) });
  if (issue?.state !== "OPEN" || issue.status !== "検証中") {
    console.log("検証中ではないので、確かめずに終わる");
    process.exit(1);
  }
}
// 引き受けたあとに書けなくても 0 で終わる。1 で終わると後始末の段が走らず、作るなら進行中のまま残る。
try {
  await gh.rest("POST", `/repos/${config.repository}/issues/${number}/comments`, { body: startReport({ kind, url }) });
  console.log(`#${number} へ着手を書いた`);
} catch (e) {
  console.log(`#${number} へ着手を書けなかった（${e.message}）`);
}
