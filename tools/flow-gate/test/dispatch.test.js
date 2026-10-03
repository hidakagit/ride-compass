// 振り出しの見回りの判断（src/dispatch.js）と状況の更新の書き方（src/status.js）を、本物の設定で確かめる。差し替えるのは GitHub（網）だけ。
import assert from "node:assert/strict";
import { test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import { dated, free, pick, queueOf, runIssue, stuck, summary } from "../src/dispatch.js";
import { GitHub, Mutations, readTask, setField } from "../src/github.js";
import { putStatus } from "../src/status.js";
import { fakeGitHub } from "./fake-github.js";

const task = (number, status, extra = {}) => ({ number, status, waitingFor: [], labels: [], urgent: false, priority: null, startOn: null, ...extra });

const run = (number, kind) => ({ number, kind });
const full = (kind, from = 100) => Array.from({ length: config.coordinator.parallel[kind] }, (_, i) => run(from + i, kind));

test("種類ごとに空いた枠の数だけキューの上から選び、未着手は作る・検証中は確かめる担当にする", () => {
  const { parallel } = config.coordinator;
  const queue = [...Array.from({ length: parallel["確かめる"] + 1 }, (_, i) => task(i + 1, "検証中")), ...Array.from({ length: parallel["作る"] + 1 }, (_, i) => task(50 + i, "未着手"))];
  const chosen = pick(config, queue, [run(99, "作る")]);
  assert.equal(chosen.filter((t) => t.kind === "確かめる").length, parallel["確かめる"]);
  assert.equal(chosen.filter((t) => t.kind === "作る").length, parallel["作る"] - 1);
  assert.deepEqual(chosen[0], { number: 1, status: "検証中", kind: "確かめる" });
  assert.deepEqual(chosen.find((t) => t.kind === "作る"), { number: 50, status: "未着手", kind: "作る" });
  assert.deepEqual(pick(config, queue, [...full("作る"), ...full("確かめる", 200)]), [], "どの種類も上限まで動いていれば選ばない");
});

test("作る枠が全部埋まっていても検証中は確かめる担当に起こし、確かめる枠は作るに使わない", () => {
  const queue = [task(1, "検証中"), task(2, "未着手")];
  assert.deepEqual(pick(config, queue, full("作る")).map((t) => t.number), [1]);
  assert.deepEqual(pick(config, queue, full("確かめる")).map((t) => t.number), [2]);
});

test("未着手は動いている番号・前提が開いたままのもの・開発機で扱うものを飛ばし、検証中は前提・開発機・着手可能日があっても飛ばさない", () => {
  const queue = [
    task(1, "検証中"),
    task(2, "未着手", { waitingFor: [9] }),
    task(3, "未着手", { labels: [config.coordinator.devLabel] }),
    task(4, "未着手"),
    task(5, "検証中", { waitingFor: [9], labels: [config.coordinator.devLabel], startOn: "2999-01-01" }),
  ];
  assert.deepEqual(pick(config, queue, [run(1, "確かめる")]).map((t) => t.number), [4, 5]);
});

// 2026-10-03T15:30Z は日本時間で 10-04 の 00:30。日付の境目を日本時間で取ることを確かめる時刻。
const now = new Date("2026-10-03T15:30:00Z");

test("着手可能日が今日（日本時間）より先のものは振り出さず、今日・過ぎた日・無いものは振り出す", () => {
  const queue = [task(1, "未着手", { startOn: "2026-10-05" }), task(2, "未着手", { startOn: "2026-10-04" }), task(3, "未着手", { startOn: "2026-10-03" }), task(4, "未着手")];
  assert.deepEqual(pick(config, queue, [], now).map((t) => t.number), [2, 3, 4]);
  assert.deepEqual(dated(config, queue, new Set(), now).map((t) => t.number), [1]);
  assert.deepEqual(pick(config, queue, [], new Date("2026-10-04T15:00:00Z")).map((t) => t.number), [1, 2, 3, 4], "その日（日本時間）になれば振り出す");
});

test("着手可能日の欄を日付で書き、「消す」にあたる null で消す。日付の形でない値は断る", async () => {
  const gh = fakeGitHub({ issue: { number: 3, status: "未着手" } });
  const bot = new GitHub("bot-token");
  const name = config.project.startField;
  const read = () => readTask(bot, config, { number: 3 });
  let { project, issue } = await read();
  await setField(new Mutations(), project, issue.item, name, "2026-10-05").send(bot);
  ({ project, issue } = await read());
  assert.equal(issue.fields[name], "2026-10-05");
  assert.equal(issue.status, "未着手");
  assert.throws(() => setField(new Mutations(), project, issue.item, name, "明日"), /YYYY-MM-DD/);
  await setField(new Mutations(), project, issue.item, name, null).send(bot);
  ({ issue } = await read());
  assert.equal(issue.fields[name], undefined);
  assert.equal(gh.issue.status, "未着手", "日付の欄を消してもステータスは消えない");
});

test("担当のワークフローの実行の名前から issue の番号を読む", () => {
  assert.equal(runIssue("#58 確かめる"), 58);
  assert.equal(runIssue("Claude Task"), null);
});

test("キューは振り出すステータスのものだけを、ステータスの順・急ぎ・優先度の欄の選択肢の順・番号の順に並べる", () => {
  const [review, todo] = config.coordinator.order;
  const tasks = [
    task(1, todo, { priority: "低" }),
    task(2, todo, { priority: "高" }),
    task(3, todo, { priority: "低", urgent: true }),
    task(4, review),
    task(5, "保留"),
    task(6, todo),
  ];
  assert.deepEqual(queueOf(config, { tasks, ranks: ["高", "中", "低"] }).map((t) => t.number), [4, 3, 2, 1, 6]);
});

const calmRound = { tasks: [], timeoutMinutes: 240, waiting: [], left: free(config, []), failed: [], stop: false, pause: null, now };
const at = (minutesAgo) => new Date(now - minutesAgo * 60000).toISOString();

test("止まっているもの: 進行中・検証中のまま持ち時間を超えて動きの無いタスクを出し、持ち時間のうち・着手可能日を待つもの・ほかのステータスは出さない", () => {
  const tasks = [
    task(1, "進行中", { updatedAt: at(239) }),
    task(2, "進行中", { updatedAt: at(241) }),
    task(3, "検証中", { updatedAt: at(500) }),
    task(4, "進行中", { updatedAt: at(500), startOn: "2026-10-05" }),
    task(5, "未着手", { updatedAt: at(500) }),
  ];
  const found = stuck(config, { ...calmRound, tasks });
  assert.equal(found.length, 2);
  assert.match(found[0], /^#2 進行中のまま、240分を超えて動きが無い/);
  assert.match(found[1], /^#3 検証中のまま/);
});

test("止まっているもの: 止めている間に振り出せる仕事があれば、種類ごとの空いた枠と理由を出す。止めていなければ出さない", () => {
  const waiting = [task(1, "検証中"), task(2, "未着手"), task(3, "未着手")];
  const left = free(config, full("作る"));
  const paused = stuck(config, { ...calmRound, waiting, left, pause: "2026-10-03T16:00:00Z" });
  assert.deepEqual(paused, [`確かめる担当の枠が${config.coordinator.parallel["確かめる"]}つ空いているのに、振り出せる仕事1件を起こしていない（10-04 01:00 まで止めている）`]);
  assert.match(stuck(config, { ...calmRound, waiting, left, stop: true })[0], /見回りのワークフローが無効/);
  assert.deepEqual(stuck(config, { ...calmRound, waiting, left }), []);
});

test("止まっているもの: 失敗で終わった担当の実行を、番号とリンクつきで出す", () => {
  const found = stuck(config, { ...calmRound, failed: [{ number: 37, kind: "作る", url: "https://run/37" }] });
  assert.deepEqual(found, ["#37 作る担当の実行が失敗で終わった [実行](https://run/37)"]);
});

test("状況の更新の中身: 止まっているものがあれば At risk、無ければ On track。止めている理由（見回りのワークフローが無効・止める時刻）を書く。この周で起こした仕事も種類ごとの動いている担当に数える", () => {
  const base = { watcher: "https://run/1", runs: [{ number: 7, kind: "作る", url: "https://run/7", startedAt: "2026-10-03T00:00:00Z" }], started: [{ number: 9, kind: "確かめる" }], waiting: [task(2, "未着手"), task(3, "未着手")], held: 3, dated: [], stuck: [], stop: null, pause: null };
  const { parallel } = config.coordinator;
  const calm = summary(config, base);
  assert.equal(calm.status, "ON_TRACK");
  assert.match(calm.body, /#7 作る（10-03 09:00 から）\[実行\]\(https:\/\/run\/7\)/);
  assert.match(calm.body, /#9 確かめる（いま起こした）/);
  assert.match(calm.body, new RegExp(`動いている担当（作る 1/${parallel["作る"]}・確かめる 1/${parallel["確かめる"]}）`));
  assert.match(calm.body, /振り出しを待つ仕事: 作る 2件・確かめる 0件（ほかに前提・段階・開発機を待つもの 3件）/);
  assert.doesNotMatch(calm.body, /着手可能日/);
  const later = summary(config, { ...base, dated: ["2026-10-09", "2026-10-05"] });
  assert.equal(later.status, "ON_TRACK", "着手可能日を待つものは止まっているものに数えない");
  assert.match(later.body, /着手可能日を待つ仕事: 2件（最も近い日 2026-10-05）/);
  const risk = summary(config, { ...base, stuck: ["#8 進行中のまま、240分を超えて動きが無い（最後の動き 10-03 08:00）"], stop: true, pause: "2026-10-03T01:00:00Z" });
  assert.equal(risk.status, "AT_RISK");
  assert.match(risk.body, /- #8 進行中のまま/);
  assert.match(risk.body, /見回りのワークフローが無効/);
  assert.match(risk.body, /10-03 10:00 まで/);
});

test("状況の更新は、中身が同じなら書かず、状態が同じなら書き換え、状態が変わるかほかの者の更新が最新なら足す", async () => {
  const gh = fakeGitHub({ issue: { number: 1 }, updates: [{ id: "SU_0", status: "AT_RISK", body: "ほかの者の更新", by: "gate" }] });
  const bot = new GitHub("bot-token");
  const calm = summary(config, { watcher: null, runs: [], started: [], waiting: [], held: 0, dated: [], stuck: [], stop: null, pause: null });
  assert.equal(await putStatus(bot, config, calm), "created");
  assert.equal(await putStatus(bot, config, calm), null);
  assert.equal(await putStatus(bot, config, { ...calm, body: `${calm.body}\n変わった` }), "updated");
  assert.equal(await putStatus(bot, config, { ...calm, status: "AT_RISK" }), "created");
  assert.deepEqual(gh.updates.map((u) => [u.status, u.by]), [["AT_RISK", config.claude], ["ON_TRACK", config.claude], ["AT_RISK", "gate"]]);
});
