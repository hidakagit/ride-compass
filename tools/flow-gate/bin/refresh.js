// 開いた issue を全部、今のゲートの規則が書くはずの姿へ揃える（hidakagit-bot の名義。src/refresh.js）。ゲートを公開した直後に
// CI（ci.yml の deploy-gate）が流す。手で流してもよい。
// 使い方: node tools/flow-gate/bin/refresh.js [--dry-run]（--dry-run は揃える issue と理由を出すだけで、書かない）
import config from "../flow.config.json" with { type: "json" };
import { refreshAll } from "../src/refresh.js";
import { botToken } from "./token.js";

const dry = process.argv.includes("--dry-run");
const changed = await refreshAll({ GITHUB_TOKEN: botToken() }, config, { dry });
for (const c of changed) console.log(`#${c.number}: ${c.why.join("・")}を${dry ? "揃える" : "揃えた"}`);
console.log(`${dry ? "揃える" : "揃えた"} issue: ${changed.length} 件`);
