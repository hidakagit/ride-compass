// Pull Request へ画像を1枚ずつ貼る（.claude/skills/task-work/SKILL.md「作る担当」の5の「貼り方」）。gh は画像を順に上げて最初の失敗で止まり、上がった分だけで
// コメントを書く（gh のソース internal/attachments/attach.go）ので、1枚ずつ打てば落ちた打ちは何も書かない。貼れなければ止まり、
// それまでに貼った分と出た文言を返す。

// run(引数) は gh を打って { status, stdout, stderr } を返す。images は "<画像>#<見出し>" の並びで、見出しをコメントの文にする。
// 返すのは貼った先の行の並び。
export function attach({ run, code, pr, images }) {
  const said = [];
  for (const image of images) {
    const title = image.slice(image.indexOf("#") + 1);
    const r = run(["pr", "comment", String(pr), "-R", code, "--body", title, "--attach", image]);
    if (r.status !== 0) throw new Error([`${image} を貼れなかった（${r.stderr.trim()}）`, ...said.map((l) => `貼った: ${l}`)].join("\n"));
    said.push(`${title}: ${r.stdout.trim()}`);
  }
  return said;
}
