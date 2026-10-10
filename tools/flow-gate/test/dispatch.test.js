// 見回りの判断（src/dispatch.js: ready・pick・mismatches と src/github.js: readActive）を確かめる。設定は架空のもの（fake-github.js: config）を渡す。
// 確かめるのは結果（振り出す番号・決め直しを頼む番号）。
// ここで見ないもの: 見回りのワークフローの止める（無効・止める時刻。bin/dispatch.js が読む値で決まる）・同じタスクの実行が1本ずつ動くこと
// （担当のワークフローの concurrency。GitHub の動き）・決め直しの頼みを受けたゲートの決め方（gate.test.js）。
import assert from "node:assert/strict";
import { test } from "node:test";
import { mismatches, pick, ready } from "../src/dispatch.js";
import { readActive } from "../src/github.js";
import { config } from "./fake-github.js";

const S = config.status;
const task = (number, status, extra = {}) => ({ number, status, blocked: false, labels: [], urgent: false, priority: null, start: null, ...extra });
const board = (...tasks) => ({ tasks, ranks: ["上", "並", "下"] });
const now = new Date("2026-10-03T15:30:00Z"); // 日本時間の 2026-10-04 00:30

test("枠は種類ごと: 作るは未着手から、確かめるは検証待ちから、上限から動いている数を引いた分だけ上から起こし、貸し借りしない", () => {
  const { 作る: make, 確かめる: check } = config.coordinator.slots;
  const tasks = [...Array.from({ length: make + 2 }, (_, k) => task(100 + k, S.todo)), ...Array.from({ length: check + 2 }, (_, k) => task(200 + k, S.ready)),
    task(300, S.review), task(301, S.ci), task(302, S.hold)];
  const running = [{ number: 1, kind: "確かめる" }];
  const kinds = pick(config, ready(config, board(...tasks), running, now), running).map((t) => t.kind);
  assert.deepEqual([kinds.filter((k) => k === "作る").length, kinds.filter((k) => k === "確かめる").length], [make, check - 1]);
});

test("作るは前提が閉じ・着手可能日時が今（日本時間の分）以前の未着手だけ。確かめるは前提・日時を問わない。並びは急ぎ・優先度（空は既定の位置）・番号", () => {
  const tasks = [task(1, S.todo, { blocked: true }), task(3, S.todo, { start: "2026-10-04 00:31" }), task(4, S.todo, { start: "2026-10-04 00:30" }),
    task(5, S.todo, { priority: "下" }), task(6, S.todo, { priority: "上" }), task(7, S.todo, { urgent: true }), task(8, S.ready, { blocked: true, start: "2026-10-05" }), task(10, S.todo),
    task(14, S.todo, { start: "2026-10-05" }), task(15, S.todo, { start: "2026-10-04" }), task(16, S.todo, { start: "2026-10-04 0:30" })];
  assert.deepEqual(ready(config, board(...tasks), [{ number: 10, kind: "作る" }], now).map((t) => t.number), [7, 6, 4, 8, 15, 5]);
});

test("突き合わせ: 担当が持つのにその種類のステータスでない・作業の状態なのに担当がいない・CI待ちなのに CI が動いていないタスクの決め直しを頼む", () => {
  const tasks = [task(1, S.working), task(2, S.review), task(3, S.todo), task(4, S.working), task(5, S.review), task(6, S.ci), task(7, S.ci), task(8, S.todo)];
  const active = [{ number: 1, kind: "作る" }, { number: 2, kind: "確かめる" }, { number: 3, kind: "作る" }, { number: 5, kind: "作る" }];
  assert.deepEqual(mismatches(config, tasks, active, new Set([7])), [3, 4, 5, 7]);
});

test("動いている実行は、終わっていない状態ごとに全部のページを読む: 新しい順の先頭100件より後ろの実行も落とさない", async () => {
  // 新しい順に、終わった150件・前の実行を待つ120件（2ページ）・長く動く1件（全体の271件目）。
  const all = [...Array.from({ length: 150 }, (_, k) => ({ id: k, status: "completed" })), ...Array.from({ length: 120 }, (_, k) => ({ id: 1000 + k, status: "pending" })), { id: 9999, status: "in_progress" }];
  const get = async (path) => {
    const q = new URL(path, "https://api.example").searchParams;
    const [n, p] = [Number(q.get("per_page")), Number(q.get("page"))];
    return { workflow_runs: all.filter((r) => r.status === q.get("status")).slice((p - 1) * n, p * n) };
  };
  assert.deepEqual((await readActive(get, config)).map((r) => r.id).sort((a, b) => a - b), all.filter((r) => r.status !== "completed").map((r) => r.id));
});
