// 公開の直後に、開いた issue を全部、今のゲートの規則の姿（担当者・本文の先頭）へ揃える（hidakagit-bot の名義）。
import { Gate } from "../src/gate.js";
import { args, config } from "./cli.js";

const { dry } = args("node tools/flow-gate/bin/refresh.js [--dry-run]", (a) => !a.length);
const gate = await Gate.open({ GITHUB_TOKEN: process.env.FLOW_BOT_TOKEN }, config);
console.log(`${dry ? "（試し）揃える" : "揃えた"}: ${(await gate.refreshAll({ dry })).map((n) => `#${n}`).join(" ") || "無し"}`);
