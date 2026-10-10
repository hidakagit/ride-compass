// 担当のワークフロー（.github/workflows/claude-task.yml）の最初の段。持つ印を取ってから、作るなら未着手 → 進行中へ動かせたときだけ、
// 確かめるなら検証中のときだけ進み、issue に着手を書く（src/hold.js: claim）。進むなら 0、進まなければ 1 で終わる。印は後始末が手放す。
import { claim } from "../src/hold.js";
import { args, bot, config, holds, isNumber } from "./cli.js";

const { rest: [number, kind, url] } = args("node tools/flow-gate/bin/claim.js <issue の番号> <作る|確かめる> <実行の URL>",
  (a) => a.length === 3 && isNumber(a[0]) && Object.keys(config.coordinator.slots).includes(a[1]));
try {
  console.log(await claim(bot(), holds(), config, Number(number), kind, url));
} catch (e) {
  console.log(`引き受けずに終わる（${e.message}）`);
  process.exit(1);
}
