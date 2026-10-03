// 振り出しの見回りの判断（src/dispatch.js）と状況の更新の書き方（src/status.js）を、本物の設定で確かめる。差し替えるのは GitHub（網）だけ。
import assert from "node:assert/strict";
import { test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import { dated, pick, queueOf, runIssue, stuck, summary } from "../src/dispatch.js";
import { GitHub, Mutations, readTask, setField } from "../src/github.js";
import { putStatus } from "../src/status.js";
import { fakeGitHub } from "./fake-github.js";

const task = (number, status, extra = {}) => ({ number, status, waitingFor: [], labels: [], urgent: false, priority: null, startOn: null, ...extra });

test("動いている担当と合わせて上限まで、キューの上から選び、未着手は作る・検証中は確かめる担当にする", () => {
  const { parallel } = config.coordinator;
  const queue = Array.from({ length: parallel + 2 }, (_, i) => task(i + 1, i % 2 ? "未着手" : "検証中"));
  const chosen = pick(config, queue, new Set([99]));
  assert.equal(chosen.length, parallel - 1);
  assert.deepEqual(chosen.slice(0, 2), [
    { number: 1, status: "検証中", kind: "確かめる" },
    { number: 2, status: "未着手", kind: "作る" },
  ]);
  assert.deepEqual(pick(config, queue, new Set(Array.from({ length: parallel }, (_, i) => 100 + i))), [], "上限まで動いていれば選ばない");
});

test("動いている番号・前提が開いたままのもの・開発機で扱うものは飛ばす", () => {
  const queue = [
    task(1, "検証中"),
    task(2, "未着手", { waitingFor: [9] }),
    task(3, "未着手", { labels: [config.coordinator.devLabel] }),
    task(4, "未着手"),
  ];
  assert.deepEqual(pick(config, queue, new Set([1])).map((t) => t.number), [4]);
});

// 2026-10-03T15:30Z は日本時間で 10-04 の 00:30。日付の境目を日本時間で取ることを確かめる時刻。
const now = new Date("2026-10-03T15:30:00Z");

test("着手可能日が今日（日本時間）より先のものは振り出さず、今日・過ぎた日・無いものは振り出す", () => {
  const queue = [task(1, "未着手", { startOn: "2026-10-05" }), task(2, "未着手", { startOn: "2026-10-04" }), task(3, "未着手", { startOn: "2026-10-03" }), task(4, "未着手")];
  assert.deepEqual(pick(config, queue, new Set(), now).map((t) => t.number), [2, 3, 4]);
  assert.deepEqual(dated(queue, new Set(), now).map((t) => t.number), [1]);
  assert.deepEqual(pick(config, queue, new Set(), new Date("2026-10-04T15:00:00Z")).map((t) => t.number), [1, 2, 3, 4], "その日（日本時間）になれば振り出す");
});

test("着手可能日を待つ進行中は、担当が動いていなくても止まっているものに数えない", () => {
  const tasks = [task(1, "進行中", { startOn: "2026-10-05" }), task(2, "進行中", { startOn: "2026-10-04" })];
  assert.deepEqual(stuck(config, tasks, new Set(), new Set(), now).map((s) => s.number), [2]);
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

test("止まっているもの: 進行中なのに担当が動いていない・検証中なのに開いた Pull Request が無い", () => {
  const tasks = [task(1, "進行中"), task(2, "進行中"), task(4, "検証中"), task(5, "検証中"), task(6, "未着手")];
  const found = stuck(config, tasks, new Set([2]), new Set([`${config.code.branchPrefix}5`]));
  assert.deepEqual(found.map((s) => s.number), [1, 4]);
});

test("状況の更新の中身: 止まっているものがあれば At risk、無ければ On track。止めの印と止める時刻を書く。この周で起こした仕事も動いている担当に数える", () => {
  const base = { watcher: "https://run/1", runs: [{ number: 7, title: "#7 作る", url: "https://run/7", startedAt: "2026-10-03T00:00:00Z" }], started: [{ number: 9, kind: "確かめる" }], waiting: 2, held: 3, dated: [], stuck: [], stop: null, pause: null };
  const calm = summary(config, base);
  assert.equal(calm.status, "ON_TRACK");
  assert.match(calm.body, /#7 作る（10-03 09:00 から）\[実行\]\(https:\/\/run\/7\)/);
  assert.match(calm.body, /#9 確かめる（いま起こした）/);
  assert.match(calm.body, new RegExp(`動いている担当（2/${config.coordinator.parallel}）`));
  assert.doesNotMatch(calm.body, /着手可能日/);
  const later = summary(config, { ...base, dated: ["2026-10-09", "2026-10-05"] });
  assert.equal(later.status, "ON_TRACK", "着手可能日を待つものは止まっているものに数えない");
  assert.match(later.body, /着手可能日を待つ仕事: 2件（最も近い日 2026-10-05）/);
  const risk = summary(config, { ...base, stuck: [{ number: 8, reason: "進行中なのに、担当が動いていない" }], stop: 12, pause: "2026-10-03T01:00:00Z" });
  assert.equal(risk.status, "AT_RISK");
  assert.match(risk.body, /#8 進行中なのに/);
  assert.match(risk.body, new RegExp(`#12 にラベル「${config.coordinator.stopLabel}」`));
  assert.match(risk.body, /10-03 10:00 まで/);
});

test("状況の更新は、中身が同じなら書かず、状態が同じなら書き換え、状態が変わるかほかの者の更新が最新なら足す", async () => {
  const gh = fakeGitHub({ issue: { number: 1 }, updates: [{ id: "SU_0", status: "AT_RISK", body: "ほかの者の更新", by: "gate" }] });
  const bot = new GitHub("bot-token");
  const calm = summary(config, { watcher: null, runs: [], started: [], waiting: 0, held: 0, dated: [], stuck: [], stop: null, pause: null });
  assert.equal(await putStatus(bot, config, calm), "created");
  assert.equal(await putStatus(bot, config, calm), null);
  assert.equal(await putStatus(bot, config, { ...calm, body: `${calm.body}\n変わった` }), "updated");
  assert.equal(await putStatus(bot, config, { ...calm, status: "AT_RISK" }), "created");
  assert.deepEqual(gh.updates.map((u) => [u.status, u.by]), [["AT_RISK", config.claude], ["ON_TRACK", config.claude], ["AT_RISK", "gate"]]);
});
