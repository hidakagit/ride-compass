// Pull Request の本文が .github/pull_request_template.md の形（「名前: 中身」の節がこの順に1つずつ、空でもテンプレートのままでもない）に
// 沿うかを照らし、沿わなければ落ちる。担当が出す前と、claude-gate.yml の flow-gate が打つ。GitHub に触れない。
import { readFileSync } from "node:fs";

const [file] = process.argv.slice(2);
if (!file) process.exit((console.error("使い方: node scripts/pr-body.js <本文のファイル>"), 2));
const sections = (text, names) => {
  const out = [];
  for (const line of text.replace(/\r\n/g, "\n").split("\n")) {
    const name = /^([^\s:<]+):(?: |$)/.exec(line)?.[1];
    if (name && (!names || names.includes(name))) out.push({ name, text: line.slice(name.length + 1).trim() });
    else if (out.length) out.at(-1).text += `\n${line}`;
  }
  return out.map((s) => ({ ...s, text: s.text.trim() }));
};
const template = sections(readFileSync(new URL("../.github/pull_request_template.md", import.meta.url), "utf8"));
const names = template.map((s) => s.name);
const got = sections(readFileSync(file, "utf8"), names);
const problems = got.map((s) => s.name).join("・") === names.join("・") ? [] : [`節は「${names.join("・")}」をこの順に1つずつ置く`];
for (const s of got) if (!s.text || s.text === template.find((t) => t.name === s.name)?.text) problems.push(`節「${s.name}:」が空か、テンプレートのまま`);
if (problems.length) process.exit((console.error([...problems, "本文は .github/pull_request_template.md を写して節を埋める"].join("\n")), 1));
console.log("本文の形は .github/pull_request_template.md に沿っている");
