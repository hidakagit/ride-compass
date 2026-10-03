// 担当のワークフロー（.github/workflows/claude-task.yml）の最初の段。作るなら未着手 → 進行中が通ったときだけ、
// 確かめるなら検証中のときだけ引き受け、issue に着手を書く（src/after.js: startReport）。引き受けたら 0、引き受けなければ 1 で終わる。
// 使い方: node tools/flow-gate/bin/claim.js <issue の番号> <作る|確かめる> <実行の URL>
import config from "../flow.config.json" with { type: "json" };
import { startReport } from "../src/after.js";
import { GitHub, readTask } from "../src/github.js";
import { moveTask } from "../src/move.js";
import { botToken } from "./token.js";

const [number, kind, url, ...rest] = process.argv.slice(2);
if (!/^\d+$/.test(number ?? "") || !["作る", "確かめる"].includes(kind) || !url || rest.length) {
  console.error("使い方: node tools/flow-gate/bin/claim.js <issue の番号> <作る|確かめる> <実行の URL>");
  process.exit(2);
}
const gh = new GitHub(botToken());
if (kind === "作る") {
  try {
    console.log(await moveTask(gh, config, Number(number), config.working));
  } catch (e) {
    console.log(`未着手ではないので、作らずに終わる（${e.message}）`);
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
