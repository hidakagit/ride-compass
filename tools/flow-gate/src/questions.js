// 問いと答えの形（.claude/skills/ask/SKILL.md「問い」）。問いの頭は「## 問い（種類）」で、種類の無い「## 問い」は判断として読む。
const KINDS = ["採否", "判断", "確かめ", "イレギュラー"];
export const norm = (t) => (t ?? "").replace(/\r\n/g, "\n");
const sections = (text) => [...text.matchAll(/^\*\*([^*]+)\*\*:/gm)].map((m) => m[1]); // 判断材料の節の名前
const BLOCK = /^<!-- flow-gate -->\n([\s\S]*?)<!-- \/flow-gate -->\n*/;
const BUTTON = /^\[!\[回答する\]\([^)]*\/button\.svg\)\]\([^)]*\/answer\?issue=\d+\)$/;

// 本文の頭の回答のボタン（GitHub の画面にボタンは足せないので、リンク付きの画像。画像とフォームの道は src/index.js が開ける）。
export const answerUrl = (config, number) => `${config.urls.form}/answer?issue=${number}`;
// 印の間にゲートの書かない行があれば、黙って消さずに印の外の先頭へ出す。foreign はその行。
export function splitBody(body) {
  const foreign = (BLOCK.exec(norm(body))?.[1] ?? "").split("\n").filter((l) => l.trim() && !BUTTON.test(l.trim()));
  const rest = norm(body).replace(BLOCK, "");
  return { foreign, rest: foreign.length ? `${foreign.join("\n")}\n\n${rest}` : rest };
}
export const bodyRest = (body) => splitBody(body).rest;
export const withButton = (body, config, number) =>
  `<!-- flow-gate -->\n[![回答する](${config.urls.gate}/button.svg)](${answerUrl(config, number)})\n<!-- /flow-gate -->\n\n${bodyRest(body)}`;
export const CONFIRM = /^ユーザーが確かめる/;
export const confirmItems = (body) => remaining(body).filter((l) => CONFIRM.test(l));
export const remaining = (body) => [...bodyRest(body).matchAll(/^\s*- \[ \] (.+)$/gm)].map((m) => m[1].trim());

// 問い: 頭の行・問いの文1行・（あれば）「### 案」と1行1案・（あれば）<details> の判断材料。ほかの行があれば null。
export function parseQuestion(text) {
  const all = norm(text);
  const cut = all.indexOf("<details>");
  const [head, ...lines] = (cut < 0 ? all : all.slice(0, cut)).split("\n");
  const kind = /^## 問い(?:（(.+)）)?\s*$/.exec(head)?.[1] ?? (/^## 問い\s*$/.test(head) ? "判断" : null);
  if (!KINDS.includes(kind)) return null;
  const [question, header, ...plans] = lines.map((l) => l.trim()).filter(Boolean);
  if (!question || /^(#|- )/.test(question)) return null;
  if (header !== undefined && (header !== "### 案" || !plans.length || plans.some((l) => !l.startsWith("- ")))) return null;
  const material = cut < 0 ? "" : /^<details>\s*<summary>[^<]*<\/summary>([\s\S]*?)<\/details>\s*$/.exec(all.slice(cut))?.[1].trim();
  return material === undefined ? null : { kind, text: question, plans: plans.map((l) => l.slice(2).trim()), material };
}

// 判断材料が形（question_template.md）の節を、形の順に1つずつ埋めて持つか。合わない所を返す（空なら合う）。
export function checkQuestion(template, text) {
  const q = parseQuestion(text);
  if (!q) return ["頭の行・問いの文（1行）・「### 案」と1行1案・<details> の判断材料のほかに行がある"];
  const want = sections(template);
  const got = sections(q.material);
  return JSON.stringify(got) === JSON.stringify(want) ? [] : [`判断材料の節は ${want.join("・")} をこの順に1つずつ`];
}

// 答え: 決定（続ける・保留・見送り）と、確かめなら項目ごとの「問題なし・問題あり」。前の形の「次のステータス:」の行も読む。
export function parseAnswer(text) {
  const all = norm(text);
  if (!/^## 回答\n/.test(all)) return null;
  const picked = /^(?:回答|次のステータス): (.+)$/m.exec(all)?.[1] ?? "";
  const decision = /見送/.test(picked) ? "見送り" : /保留/.test(picked) ? "保留" : "続ける";
  const items = [...all.matchAll(/^- (問題なし|問題あり): (.+?)(?: — (.+))?$/gm)].map((m) => ({ ok: m[1] === "問題なし", text: m[2], note: m[3] ?? "" }));
  return { decision, items };
}

// コメントの並びから今の問いと、その答え（無ければ null）。形（template）に合わない問いは問いとして読まない（残す守り: 問いの形の検査）。
export function latestQuestion(comments, template) {
  const i = comments.findLastIndex((c) => /^## 問い/.test(norm(c)));
  if (i < 0) return null;
  const q = !template || !checkQuestion(template, comments[i]).length ? parseQuestion(comments[i]) : null;
  const a = comments.slice(i + 1).map(parseAnswer).find(Boolean) ?? null;
  return q && { ...q, answer: a };
}

// ゲートが出す問い（採否・確かめ・イレギュラー）。判断材料は形（question_template.md）の節を埋める。答えの選び方は回答フォームが種類で出す。
const ASKS = {
  採否: ["このタスクに着手しますか？", "Claude が起こした要望です。着手するかはユーザーが決めます。", "決めたことだけを Claude が進める。",
    "決めないまま進めると、要らないものを作る。", "ユーザーの起票・改善・段階（決めずに進める）。", "着手する: 未着手になり担当が振り出される。保留する: 保留へ。見送る: 閉じる。", "着手するかの判断は本文で決まる。"],
  確かめ: ["完成にしてよいですか？", "完了の条件のうち、ユーザーが確かめる行だけが残っています。項目ごとに見て、問題の有無を答えてください。",
    "完成は、完了の条件が全部満たされたときだけ。", "見ないまま完成にすると、思ったものと違うまま閉じる。", "条件がユーザーの確かめを持たないとき。",
    "全部問題なし: 印を付けて完成。問題ありの項目がある: 直す行を条件に足して未着手。", "本文の完了の条件の「ユーザーが確かめる」の行。"],
  イレギュラー: ["担当が、問いも Pull Request も出さず、条件も満たさずに終わりました。どうしますか？", "直前の「担当の終わり」のコメントに、実行へのリンクと担当の最後の発言があります。",
    "落ちた担当を黙って振り出し直さず、ユーザーが次を決める。", "同じ形で何度も落ちる。", "担当が問いか Pull Request を出したとき。",
    "やり直す: 未着手へ戻し振り出す。保留する: 保留へ。見送る: 閉じる。", "直前の「担当の終わり」のコメント。"],
};
export function askText(kind, template) {
  const [question, ...facts] = ASKS[kind];
  const material = sections(template).map((n, i) => `**${n}**: ${facts[i] ?? "なし"}`).join("\n\n");
  return `## 問い（${kind}）\n${question}\n\n<details><summary>判断材料</summary>\n\n${material}\n</details>`;
}
