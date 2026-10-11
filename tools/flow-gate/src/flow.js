// 出来事1件の処理。担当の実行の知らせは見回りへ、ほかはゲートへ渡し、見回りが起こしたタスクはその場で決め直す（持った。順番待ちを含む）。
// 定時は、時刻が事実になるもの（着手可能日時・利用の上限の止めが解ける）の振り出しと、状況の更新。
import { runOf } from "./facts.js";
import { ignored, reportHealth, route, settle } from "./gate.js";

export async function handle(gh, { patrol, inbox }, config, name, payload) {
  if (name === "schedule") {
    const sent = await dispatch(gh, patrol, config, [], Object.keys(config.slots), true);
    await reportHealth(gh, config, { stopped: sent.stopped, failed: await inbox.failed() });
    return inbox.clear();
  }
  if (ignored(config, name, payload)) return;
  const w = payload.workflow_run;
  const run = name === "workflow_run" && w.path.endsWith(config.workflow) && runOf(w.display_title);
  if (run) await patrol.observe({ ...run, id: w.id, state: payload.action });
  const { numbers, moved } = run ? { numbers: [run.number] } : await route(gh, config, name, payload);
  const record = await patrol.all();
  const settled = await Promise.all(numbers.map((n) => settle(gh, config, n, record, moved)));
  await dispatch(gh, patrol, config, settled, run && payload.action === "completed" ? [run.kind] : []);
}

async function dispatch(gh, patrol, config, settled, kinds, always) {
  const sent = await patrol.dispatch(gh, config, settled, kinds, always);
  const record = await patrol.all();
  await Promise.all(sent.picked.map((p) => settle(gh, config, p.number, record)));
  return sent;
}
