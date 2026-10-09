// Pull Request の本文の形（.github/pull_request_template.md）を照らす。GitHub に触れない純粋な関数だけを置く。
import { normalize } from "./rules.js";

// 節は行の頭の「<名前>:」から次の節の頭の前まで。名前はテンプレートの節の頭の行から取り、ほかの「名前: 」の行は節の中身とする。
const HEAD = /^([^\s:<>`]+):(.*)$/;
const split = (text, names) => {
  const out = [];
  for (const line of normalize(text).split("\n")) {
    const m = HEAD.exec(line);
    if (m && (!names || names.includes(m[1]))) out.push({ name: m[1], lines: [m[2]] });
    else if (out.length) out.at(-1).lines.push(line);
    else if (line.trim()) out.push({ name: null, lines: [line] });
  }
  return out.map(({ name, lines }) => ({ name, text: lines.join("\n").trim() }));
};

// 本文の形の誤りを1件1行で返す（無ければ空）。
export function checkBody(template, body) {
  const want = split(template).filter((s) => s.name);
  const names = want.map((s) => s.name);
  const got = split(body, names);
  const problems = [];
  if (got[0]?.name === null) problems.push(`最初の節「${names[0]}:」より前に行がある: ${got[0].text.split("\n")[0]}`);
  const order = got.filter((s) => s.name).map((s) => s.name);
  if (order.join("・") !== names.join("・")) problems.push(`節は「${names.join("・")}」をこの順に1つずつ置く（本文の節: 「${order.join("・")}」）`);
  for (const s of got.filter((s) => s.name)) {
    if (!s.text) problems.push(`節「${s.name}:」が空`);
    else if (s.text === want.find((w) => w.name === s.name).text) problems.push(`節「${s.name}:」がテンプレートのまま`);
  }
  return problems;
}
