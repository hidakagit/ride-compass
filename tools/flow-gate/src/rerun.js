// 直すもの無しに取り消された実行の見分け。GitHub Actions の障害の間は、ジョブがランナーを待ったあと段を1つも走らせずに
// 取り消しで終わることがある。持ち時間（ci.yml の timeout-minutes）を超えたジョブも取り消しで終わり、持ち時間はふだんの所要の
// 2倍から決めてあるので、超えたのは段が止まった（ランナーの側の止まり）と読む。どちらも落ちたものに当てず流し直す（flow.md「作る担当」の5）。
// 段が走ってから取り消されたジョブのうち、持ち時間を超えたものは注記で見分ける（2026-10 の実例の注記は
// 「The job has exceeded the maximum execution time of 6h0m0s」。超えた時間の書き方は持ち時間で変わるので、その前までを見る）。
export const NOT_ACQUIRED = "The job was not acquired by Runner";
export const TIMED_OUT = "The job has exceeded the maximum execution time";
export const RERUNS = 3; // 実行ごとに流し直す上限

// run は実行（GitHub の「Get a workflow run」の応答）、jobs は最後の試みのジョブ、notes はジョブの id → 注記の文の並び。
// gather は needs の結果だけを見る必須のジョブの名前（前のジョブが取り消されると、段を走らせて落ちる）。
// 返すのは kind（流す・落ちた・使い切った・終わっていない）と理由。流し直した回数は、試みの番号（run_attempt）から1を引いたもの。
export function verdict(run, jobs, notes, gather) {
  if (run.status !== "completed") return { kind: "終わっていない", reason: `実行はまだ ${run.status}。gh run watch で終わるのを待つ` };
  const bad = jobs.filter((j) => j.conclusion !== "success" && j.conclusion !== "skipped");
  const cancelled = bad.filter((j) => j.conclusion === "cancelled");
  const failed = bad.filter((j) => j.conclusion !== "cancelled" && j.name !== gather);
  const noted = (j, text) => (notes[j.id] ?? []).some((m) => m.includes(text));
  const cause = (j) => (!j.steps.length && noted(j, NOT_ACQUIRED) ? "ランナーが付かなかった" : noted(j, TIMED_OUT) ? "持ち時間を超えた" : null);
  const name = (js) => js.map((j) => `${j.name}（${j.conclusion}・段=${j.steps.length}${cause(j) ? `・${cause(j)}` : ""}）`).join("・");
  if (!cancelled.length || failed.length || !cancelled.every(cause))
    return { kind: "落ちた", reason: `直すもの無しに取り消されたものではない: ${name(bad) || "落ちたジョブが無い"}` };
  if (run.run_attempt > RERUNS)
    return { kind: "使い切った", reason: `${RERUNS}回流し直しても同じ取り消しで終わった（試み ${run.run_attempt}）: ${name(cancelled)}` };
  return { kind: "流す", reason: `直すもの無しに取り消された（流し直し ${run.run_attempt}回目）: ${name(cancelled)}` };
}
