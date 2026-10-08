// 本番の実物で確かめてほしい問いを、マージのコミットが本番に出てから置く（docs/conventions/flow.md「確かめる担当」の3）。
// 問いを置くまで回答待ちにしないので、回答待ちのタスクはいつでも答えてよい。
import { askTask, moveTask } from "./move.js";
import { notes } from "./rules.js";

const short = (sha) => (sha ? sha.slice(0, 8) : "読めない");
const jst = (ms) => new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(ms);

// 判断材料の先頭に、本番に出たのを見た時刻と版を書き足す（判断材料が無ければ足す）。
export function withDeployed(question, { frontend, backend }, merge, at) {
  const line = `- 本番に出た: ${jst(at)}（日本時間）に見た時点で、本番の画面（frontend）は ${short(frontend)}、backend は ${short(backend)} で動いており、` +
    `どちらもこのマージ（${short(merge.sha)}）の変更を含む。`;
  const cut = /<details>\s*<summary>[^<]*<\/summary>\n*/.exec(question);
  return cut ? `${question.slice(0, cut.index + cut[0].length)}${line}\n\n${question.slice(cut.index + cut[0].length)}` : `${question}\n\n<details><summary>判断材料</summary>\n\n${line}\n\n</details>`;
}

// look は本番を1回見て { ok（frontend と backend のどちらもマージを含む）, frontend, backend（動いているコミット。読めなければ null） } を返す。
// 出ていれば問い（"問うた"）、マージから coordinator.deployWaitMinutes を過ぎても出ていなければ、問いを置かずに理由を書いて保留へ
// 動かし（"上限"。担当者がユーザーになって知らせが届く）、どちらでもなく stopAt を過ぎたら何も書かずに "まだ" を返す（担当は打ち直す）。
export async function askDeployed(gh, config, number, question, { merge, look, stopAt, now = Date.now, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) }) {
  const late = Date.parse(merge.mergedAt) + config.coordinator.deployWaitMinutes * 60e3;
  for (;;) {
    const seen = await look();
    if (seen.ok) return { kind: "問うた", text: await askTask(gh, config, number, withDeployed(question, seen, merge, now())) };
    const state = `本番の画面（frontend）は ${short(seen.frontend)}、backend は ${short(seen.backend)}`;
    if (now() >= late) {
      const why = `Pull Request #${merge.number} のマージ（${short(merge.sha)}、${jst(Date.parse(merge.mergedAt))} 日本時間）から ` +
        `${config.coordinator.deployWaitMinutes}分たっても本番に出ていない（${state}）。本番での確かめの問いを置かずに止める。` +
        `master の CI のデプロイを見て、本番に出たら未着手へ戻すと、次の担当が問う`;
      return { kind: "上限", text: await moveTask(gh, config, number, config.hold, { comment: notes.reason(config.hold, why) }) };
    }
    if (now() >= stopAt) return { kind: "まだ", text: `#${number}: まだ本番に出ていない（${state}。マージ ${short(merge.sha)}）` };
    await sleep(30e3);
  }
}
