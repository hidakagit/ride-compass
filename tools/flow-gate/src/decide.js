// タスクのあるべき姿を、事実だけから1つの決め方で決める（CLAUDE.md「原則」の3）。GitHub に触れない。facts は src/facts.js: readFacts が組む。
// 返すのは、ゲートが保つ値の全部（ステータス・開き閉じ・種類・担当者・本文・ボード・優先度・PR をレビュー可能にするか・出す問い・
// 取り消す実行）。ゲートは今の値と違う所だけを書くので、同じ事実からは何度決めても同じになる。
import { bodyRest, CONFIRM, splitBody, withButton } from "./questions.js";

const HELD = { 作る: "進行中", 確かめる: "検証中" }; // 担当が持っている間のステータス
const WAIT = ["回答待ち", "保留"]; // ユーザーの番（担当者の欄にユーザーを入れる）
const DIALOG = ["未着手", ...WAIT, "完了"]; // 対話作業のボードのステータス（開発機のセッションが触っていることは持たない）

export function decide(f, config) {
  const board = f.board ?? (f.type === config.dialogType ? "dialog" : "actions");
  // 種類は作るときに決まり、対話作業の境目をまたいで変わらない。境目の向こうへ変わったら、こちら側の最後の種類へ戻す。
  const mine = (t) => (t === config.dialogType) === (board === "dialog");
  const type = mine(f.type) ? f.type : (f.types.findLast(mine) ?? (board === "dialog" ? config.dialogType : null));
  const s = status(f, config);
  if (board === "dialog" && !DIALOG.includes(s.status)) s.status = "未着手";
  let body = bodyRest(f.body);
  for (const line of s.check ?? []) body = body.replace(`- [ ] ${line}`, `- [x] ${line}`);
  const missing = (s.fix ?? []).filter((l) => !body.includes(`] ${l}`));
  if (missing.length) body = `${body.trimEnd()}\n${missing.map((l) => `- [ ] ${l}`).join("\n")}\n`;
  return { board, type, status: s.status, open: s.status !== "完了", closeAs: s.closeAs, ask: s.ask ?? null, cancel: s.cancel ?? [],
    notice: notice(f, s.status),
    ready: s.status === "検証待ち" && Boolean(f.pr?.draft), assignees: WAIT.includes(s.status) ? [config.user] : [], priority: f.priority ?? f.parentPriority,
    body: s.status === "回答待ち" || (f.question && !f.question.answer) ? withButton(body, config, f.number) : body };
}

// 受け入れなかった書き込みは、黙らずに1つのコメントで知らせる（形に合わない問い・印の間の見知らぬ行・形の合わない着手可能日時・
// 事実へ戻したユーザーのボードの移動）。直るまで同じ知らせを重ねないよう、最新のコメントが同じ知らせなら書かない。
function notice(f, status) {
  const text = [f.badQuestion.length && `この問いは形に合わないので、問いとして読みません: ${f.badQuestion.join("・")}`,
    splitBody(f.body).foreign.length && "本文の先頭の印の間に、ゲートの書かない行があったので、消さずに印の外へ出しました。",
    // 直るまで続く知らせは、最近のコメントに同じ知らせがあれば重ねない（値が変われば新しく知らせる）。
    f.badStart && !f.comments.some((c) => c.includes(`「${f.badStart}」`)) &&
      `着手可能日時「${f.badStart}」の形が合わないので受け付けず、その間は振り出しません（\`YYYY-MM-DD HH:MM\` か \`YYYY-MM-DD\`。日本時間）。`,
    f.moved && f.status && status !== f.status && `ボードで「${f.status}」へ動かしましたが、事実から「${status}」にしました（ユーザーが直接決められるのは、保留と、完了（完了の条件が全部済んだときの完成か、見送り）だけです）。`,
  ].filter(Boolean).join("\n\n");
  return text && text !== f.comments.at(-1) ? text : null;
}

function status(f, config) {
  // 完了は、完成（完了の条件が全部済んだ）か見送りでだけ受ける。条件が残ったまま完成で閉じたら、誰が閉じても開き直して決め直す。
  // ボードで完了へ動かしても、開いているなら下で事実から決め直す。
  if (!f.open && !(f.closedAs === "COMPLETED" && f.remaining.length)) return { status: "完了" };
  // 持たれている間は決め直さない。ユーザーが保留へ置いたら、持っている実行を取り消す。
  if (f.runs.length) return f.status === "保留" ? { status: "保留", cancel: f.runs.map((r) => r.id).filter(Boolean) } : { status: HELD[f.runs.some((r) => r.kind === "作る") ? "作る" : "確かめる"] };
  if (f.status === "保留") return { status: "保留" }; // ユーザーが置いた保留は、ユーザーが出すまで保つ
  // 入口: Claude が起こした要望（段階でないもの）だけ採否を問い、ほかは未着手。
  if (!f.status) return f.author === config.claude && f.type === "要望" && !f.parent ? { status: "回答待ち", ask: "採否" } : { status: "未着手" };
  const q = f.question;
  if (q && !q.answer) return { status: "回答待ち" };
  if (!q || f.status !== "回答待ち") return table(f); // 答えは、ユーザーの番（回答待ち）のときだけ受ける
  if (q.answer.decision === "見送り") return { status: "完了", closeAs: "NOT_PLANNED" };
  if (q.answer.decision === "保留") return { status: "保留" };
  if (q.kind !== "確かめ") return table(f);
  const bad = q.answer.items.filter((i) => !i.ok);
  if (bad.length) return { status: "未着手", fix: bad.map((i) => `直す: ${i.note || i.text}`) };
  const check = f.remaining.filter((l) => CONFIRM.test(l) && q.answer.items.some((i) => i.ok && i.text === l));
  return { ...table({ ...f, remaining: f.remaining.filter((l) => !check.includes(l)) }), check };
}

// 手放したあとの表。作業のステータスなのに持たれていないのが、担当が手放した事実。
const IRREGULAR = { status: "回答待ち", ask: "イレギュラー" };
function table(f) {
  const pr = f.pr;
  if (pr) {
    if (pr.backToDraft) return { status: "未着手" }; // 確かめる担当の差し戻し
    if (!pr.checks || pr.checks === "PENDING") return { status: "CI待ち" }; // 下書きかどうかによらず、CI の結果を待つ間は手放す
    if (pr.checks === "FAILURE" || pr.newSurvivors) return { status: "未着手" };
    // 確かめる担当が、マージも差し戻しも問いもせずに手放した（同じ PR を確かめ直し続けない）。
    return f.status === HELD.確かめる ? IRREGULAR : { status: "検証待ち" };
  }
  // マージのあとの残りは、マージのコミットの master の CI（デプロイを含む）が終わってから扱う（本番に出る前に確かめを問わない。原則2）。
  if (!f.remaining.length) return { status: "完了", closeAs: "COMPLETED" };
  if (f.merged && f.mergeChecks !== "SUCCESS") return { status: "CI待ち" };
  if (f.remaining.every((l) => CONFIRM.test(l))) return { status: "回答待ち", ask: "確かめ" };
  if (f.blocked || f.future) return { status: "未着手" };
  const released = Object.values(HELD).includes(f.status);
  return released && !f.merged ? IRREGULAR : { status: "未着手" };
}
