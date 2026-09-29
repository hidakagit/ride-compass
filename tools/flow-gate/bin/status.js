// 司令塔の様子を Project の「状況の更新」に書く（hidakagit-bot の名義）。司令塔の1回の最後に呼ぶ。
// スロット（slots.js）・キュー（queue.js）・検証中の Pull Request・ほかが書いた状況の更新を読み、異常を機械で見つける。
// キューの長さは異常に数えない（スロットより多い仕事は待つのが普通で、振り出しが止まったことは起きた時刻の古さに出る）。
// 異常が1つでもあれば At risk、無ければ On track。最新の更新が自分の書いたもので状態が同じなら書き換え、違えば新しく足す
// （起きるたびに履歴を増やさず、状態が変わった所だけが履歴に残る）。閾値は flow.config.json: coordinator。
// 使い方: node tools/flow-gate/bin/status.js [--found <司令塔が見つけた異常と、したこと>]...
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import config from "../flow.config.json" with { type: "json" };
import { GitHub } from "../src/github.js";
import { latestPr } from "../src/review.js";
import { AT_RISK, OFF_TRACK, ON_TRACK, clock, coordinatorUpdate, putUpdate, readUpdates } from "../src/status.js";
import { botToken, codeToken } from "./token.js";

const args = process.argv.slice(2);
const found = [];
for (let i = 0; i < args.length; i += 2) {
  if (args[i] !== "--found" || !args[i + 1]?.trim()) {
    console.error("使い方: node tools/flow-gate/bin/status.js [--found <司令塔が見つけた異常と、したこと>]...");
    process.exit(2);
  }
  found.push(args[i + 1].trim());
}

const { dropMinutes, order } = config.coordinator;
const here = dirname(fileURLToPath(import.meta.url));
const json = (script) => JSON.parse(execFileSync(process.execPath, [join(here, script), "--json"], { encoding: "utf8" }));
const issue = (n) => `[#${n}](https://github.com/${config.repository}/issues/${n})`;
const now = Date.now();
const span = (m) => (m >= 60 ? `${Math.floor(m / 60)}時間${m % 60}分` : `${m}分`);

const gh = new GitHub(botToken());
const code = new GitHub(codeToken());
const slots = json("slots.js");
const queue = json("queue.js");
const { projectId, updates } = await readUpdates(gh, config);
const me = config.claude;
const mine = coordinatorUpdate(config, updates);

const anomalies = [...found];
for (const s of slots) {
  if (s.state === "無い") anomalies.push(`スロット ${s.slot} の作業ツリーが無い`);
  else if (s.state === "未コミットの変更あり") anomalies.push(`スロット ${s.slot} に、鍵を外したあとの未コミットの変更が残っている`);
  else if (s.state === "鍵の無い枝") anomalies.push(`スロット ${s.slot} が、鍵の無いまま枝 ${s.branch} にいる`);
  else if (s.state === "使用中" && !s.number) anomalies.push(`スロット ${s.slot} に知らない鍵（${s.reason}）が掛かっている`);
  else if (s.state === "使用中" && s.minutes > dropMinutes)
    anomalies.push(`スロット ${s.slot} の${s.kind}担当（${issue(s.number)}）が、鍵を掛けてから${Math.floor(s.minutes / 60)}時間を超えて動いている`);
}
// 検証中は Pull Request が開いたときだけ入り、閉じると出る。開いた Pull Request の無い検証中は、ゲートが出来事を受け損ねたもの。
const verifying = config.transitions.find((t) => t.on === "PR が開いた").to[0];
for (const t of queue.filter((t) => t.status === verifying)) {
  const pr = await latestPr(code, config, t.number);
  if (pr?.state !== "open")
    anomalies.push(`${issue(t.number)} が検証中なのに、開いた Pull Request が無い（ゲートが出来事を受け損ねたなら、コードのリポジトリの Webhooks から Redeliver）`);
}
// 前回の自分の更新のあとに、ほか（ゲートの失敗・見張りの Off track）が足した At risk・Off track。今回の At risk で一度は見出しに出す。
for (const u of updates)
  if (u !== mine && [AT_RISK, OFF_TRACK].includes(u.status) && (!mine || u.createdAt > mine.updatedAt))
    anomalies.push(
      u.by === me
        ? `司令塔が止まっていた（見張りが ${clock(new Date(u.createdAt))} に Off track の状況の更新を足した）`
        : `${u.by ?? "だれか"} が ${clock(new Date(u.createdAt))} に ${u.status === AT_RISK ? "At risk" : "Off track"} の状況の更新を足した（下の履歴）`,
    );

const count = (status, pick = () => true) => queue.filter((t) => t.status === status && pick(t)).length;
const waiting = count("未着手", (t) => t.waitingFor.length);
const body = [
  `**司令塔が最後に起きた時刻**: ${clock(new Date(now))}（日本時間）`,
  "",
  "### 異常",
  ...(anomalies.length ? anomalies.map((a) => `- ${a}`) : ["無し"]),
  "",
  "### スロット",
  "| スロット | 状態 | 担当 | 鍵を掛けてから |",
  "|---|---|---|---|",
  ...slots.map((s) =>
    s.state === "使用中"
      ? `| ${s.slot} | 使用中 | ${s.number ? `${s.kind} ${issue(s.number)}` : s.reason} | ${s.number ? span(s.minutes) : ""} |`
      : `| ${s.slot} | ${s.state} | | |`,
  ),
  "",
  "### キュー（Claude の番）",
  `${order.map((s) => `${s} ${count(s)}`).join("・")}${waiting ? `（未着手のうち前提待ち ${waiting}）` : ""}`,
].join("\n");

const status = anomalies.length ? AT_RISK : ON_TRACK;
const target = updates[0] && updates[0] === mine && mine.status === status ? mine : null;
await putUpdate(gh, projectId, target, status, body);
console.log(`${target ? "書き換えた" : "足した"}: ${status === AT_RISK ? "At risk" : "On track"}（異常 ${anomalies.length}）`);
for (const a of anomalies) console.log(`- ${a}`);
