// Claude がタスクを段階に分ける（src/github.js: createStage）。段階は親の子として親と同じ種類で作り、--dialog なら対話作業の種類で作る
// （開発機が要る作業を、開発機の対話のセッションへ渡す）。ボードへ入れて入口を通すのは、作られた出来事を受けたゲート。前の段階は段階の
// 前提に、段階は親の前提に張る（段階が全部閉じるまで、親は前提待ちで振り出されない）。
import { readFileSync } from "node:fs";
import { createStage, readTask } from "../src/github.js";
import { args, bot, config, isNumber } from "./cli.js";

const { rest } = args("node tools/flow-gate/bin/stage.js [--dialog] <親の番号> <題名> <本文のファイル> [前の段階の番号...]",
  (a) => { const r = a.filter((x) => x !== "--dialog"); return r.length >= 3 && isNumber(r[0]) && r.slice(3).every(isNumber); });
const dialog = rest.includes("--dialog");
const [parent, title, file, ...before] = rest.filter((x) => x !== "--dialog");
const gh = bot();
const [top, ...earlier] = await Promise.all([parent, ...before].map(async (k) => (await readTask(gh, config, { number: Number(k) })).issue));
const stage = await createStage(gh, config, top, { title, body: readFileSync(file, "utf8"), before: earlier, dialog });
console.log(`${dialog ? "対話作業の" : ""}段階 #${stage.number} ${stage.url}`);
