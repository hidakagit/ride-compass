// 担当のワークフロー（.github/workflows/claude-task.yml）の最初の段。作るなら未着手 → 進行中へ動かせたときだけ、確かめるなら
// 検証中のときだけ進み、issue に着手を書く。進むなら 0、進まなければ 1 で終わる。
import { readTask } from "../src/github.js";
import { moveTask } from "../src/move.js";
import { notes } from "../src/rules.js";
import { args, bot, config, isNumber } from "./cli.js";

const { rest: [number, kind, url] } = args("node tools/flow-gate/bin/claim.js <issue の番号> <作る|確かめる> <実行の URL>",
  (a) => a.length === 3 && isNumber(a[0]) && ["作る", "確かめる"].includes(a[1]));
const gh = bot();
const start = notes.start(kind, url);
try {
  if (kind === "作る") console.log(await moveTask(gh, config, Number(number), config.working, { comment: start }));
  else if ((await readTask(gh, config, { number: Number(number) })).issue?.status === config.review) await gh.rest("POST", `/repos/${config.repository}/issues/${number}/comments`, { body: start });
  else throw new Error("検証中ではない");
} catch (e) {
  console.log(`引き受けずに終わる（${e.message}）`);
  process.exit(1);
}
