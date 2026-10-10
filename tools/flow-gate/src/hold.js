// 開発機の対話のセッションがタスクを持つ・手放す（bin/hold.js）。持つのは、そのタスクの担当のワークフローのグループ
// （.github/workflows/claude-task.yml の concurrency）で動いている種類「開発機」の実行。
import { readActive, runOf } from "./dispatch.js";
import { again } from "./github.js";

// 実行（GitHub の実行の形のまま）が、その番号の種類「開発機」のものか。
const isHold = (run, number) => {
  const [n, kind] = runOf(run.display_title);
  return Number(n) === Number(number) && kind === "開発機";
};

// その番号の種類「開発機」の終わっていない実行。
const holds = async (gh, config, number) => (await readActive((path) => gh.rest("GET", path), config)).filter((r) => isHold(r, number));

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

// 持った実行（id）の取り消しを頼み、頼む前に読んだ実行を返す（もう終わっていれば頼まない）。状態で絞った一覧は起きた直後の実行を
// まだ出さないことがあり（持ってから十数秒で手放すと、in_progress の一覧に無く取り消しが空振りした）、一覧で探さずに id で打つ。
// 読み直してから取り消すので、一時的な失敗なら丸ごと打ち直しても二重にならない。取り消しが受け付けられなければ（409 等）、その応答で
// 落ちる。止まるまでは待たない——止まりきるまでの間もそのグループに終わっていない実行があるので、見回りはその番号へ振り出さない
// （src/dispatch.js: ready）。
export async function release(gh, config, number, id) {
  const path = `/repos/${config.code.repository}/actions/runs/${id}`;
  if (!isHold(await gh.rest("GET", path), number)) throw new Error(`実行 ${id} は #${number} の種類「開発機」の実行ではない`);
  return again(true, async () => {
    const run = await gh.rest("GET", path);
    if (run.status !== "completed") await gh.rest("POST", `${path}/cancel`);
    return run;
  });
}
