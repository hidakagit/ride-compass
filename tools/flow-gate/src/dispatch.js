// 振り出す仕事を選ぶ。queue は bin/queue.js の並び（振り出す順）、running は担当のワークフローで動いている（待っているものを含む）
// issue の番号。動いているものと合わせて coordinator.parallel を超えない数だけ、上から選ぶ。動いている番号・前提が開いたままの
// 未着手・開発機で扱うタスク（ラベル coordinator.devLabel）は飛ばす。担当の種類はステータスで決まる（未着手は作る、検証中は確かめる）。
export function pick(config, queue, running) {
  const { parallel, devLabel } = config.coordinator;
  const todo = config.transitions.find((t) => t.on === "振り出し").from[0];
  return queue
    .filter((t) => !running.has(t.number) && !t.waitingFor.length && !t.labels.includes(devLabel))
    .slice(0, Math.max(0, parallel - running.size))
    .map((t) => ({ number: t.number, status: t.status, kind: t.status === todo ? "作る" : "確かめる" }));
}

// 担当のワークフローの実行の名前（run-name）は「#<番号> <種類>」。名前から番号を読む。
export const runIssue = (title) => Number(/^#(\d+) /.exec(title ?? "")?.[1]) || null;
