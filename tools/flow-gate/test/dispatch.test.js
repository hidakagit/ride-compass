// 振り出す仕事の選び方（src/dispatch.js）を、本物の設定で確かめる。
import assert from "node:assert/strict";
import { test } from "node:test";
import config from "../flow.config.json" with { type: "json" };
import { pick, runIssue } from "../src/dispatch.js";

const task = (number, status, extra = {}) => ({ number, status, waitingFor: [], labels: [], ...extra });

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

test("担当のワークフローの実行の名前から issue の番号を読む", () => {
  assert.equal(runIssue("#58 確かめる"), 58);
  assert.equal(runIssue("Claude Task"), null);
});
