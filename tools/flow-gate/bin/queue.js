// Claude が振り出すタスク（ステータスが coordinator.order のもの。誰の番かはステータスで決まる）を、振り出す順
// （src/dispatch.js: queueOf）に並べて出す。前提が開いたままの未着手・着手可能日を待つものには印を付ける。
// 使い方: node tools/flow-gate/bin/queue.js [--json]
import config from "../flow.config.json" with { type: "json" };
import { queueOf, readBoard } from "../src/dispatch.js";
import { GitHub } from "../src/github.js";
import { waitsUntil } from "../src/rules.js";
import { botToken } from "./token.js";

if (process.argv.slice(2).some((a) => a !== "--json")) {
  console.error("使い方: node tools/flow-gate/bin/queue.js [--json]");
  process.exit(2);
}
const tasks = queueOf(config, await readBoard(new GitHub(botToken()), config));

if (process.argv.includes("--json")) console.log(JSON.stringify(tasks, null, 2));
else if (!tasks.length) console.log("振り出すタスクは無い");
else
  for (const t of tasks)
    console.log(
      `#${t.number} ${t.status}${t.urgent ? ` ${config.project.urgentLabel}` : ""}${t.priority ? ` ${config.project.priorityField}:${t.priority}` : ""}` +
        `${t.waitingFor.length ? ` 前提待ち（${t.waitingFor.map((n) => `#${n}`).join("・")}）` : ""}${t.openChildren.length ? ` 段階待ち（${t.openChildren.length}件）` : ""}${waitsUntil(t.startOn) ? ` 着手可能日待ち（${t.startOn}）` : ""} ${t.title}`,
    );
