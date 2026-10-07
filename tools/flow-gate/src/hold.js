// 開発機の対話のセッションがタスクを持つ・手放す（bin/hold.js）。持つのは、そのタスクの担当のワークフローのグループ
// （.github/workflows/claude-task.yml の concurrency）で動いている種類「開発機」の実行。
import { readActive, runOf } from "./dispatch.js";
import { again } from "./github.js";

// その番号の種類「開発機」の終わっていない実行（GitHub の実行の形のまま）。
const holds = async (gh, config, number) => (await readActive((path) => gh.rest("GET", path), config))
  .filter((r) => { const [n, kind] = runOf(r.display_title); return Number(n) === Number(number) && kind === "開発機"; });

// 動いている種類「開発機」の実行があれば、それを held で返す（誰の実行かは道具には分からないので、どうするかは打った者が決める）。
// 無ければ持つ実行を mine で返す: 待っている種類「開発機」の実行があれば、前に打って落ちたときに起こしたものとみて、起こし直さずに
// それを待つ（起こし直すと2本目が待ちに残り、手放したあとに誰も触らないまま持つ）。無ければ起こす。待つのは、動き始めるか
// 終わるまで（wait を挟んで読み直す）。起こす要求は打ち直さない（github.js: again）。落ちたら打ち直せば、起きていた実行を待つ。
export async function hold(gh, config, number, wait) {
  const { repository, base } = config.code;
  const runs = await holds(gh, config, number);
  const held = runs.find((r) => r.status === "in_progress");
  if (held) return { held };
  let id = runs[0]?.id;
  if (!id) {
    // return_run_details で、起こした実行の id が返る（公式の文書「Create a workflow dispatch event」）。
    ({ workflow_run_id: id } = await gh.rest("POST", `/repos/${repository}/actions/workflows/${config.coordinator.workflow}/dispatches`,
      { ref: base, inputs: { issue: String(number), kind: "開発機" }, return_run_details: true }));
  }
  for (;;) {
    const mine = await gh.rest("GET", `/repos/${repository}/actions/runs/${id}`);
    if (mine.status === "in_progress" || mine.status === "completed") return { mine };
    await wait();
  }
}

// その番号の種類「開発機」の終わっていない実行を全部取り消す。読み直してから取り消すので、一時的な失敗なら丸ごと打ち直しても
// 二重にならない。
export async function release(gh, config, number) {
  await again(true, async () => {
    for (const r of await holds(gh, config, number)) await gh.rest("POST", `/repos/${config.code.repository}/actions/runs/${r.id}/cancel`);
  });
}
