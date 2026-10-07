// Pull Request へ画像を1枚ずつ貼る（flow.md「作る担当」の5の「貼り方」）。gh は画像を順に上げて最初の失敗で止まり、上がった分だけで
// コメントを書く（gh のソース internal/attachments/attach.go）ので、1枚ずつ打てば落ちた打ちは何も書かず、打ち直しても重ならない。
// 失敗は gh の文言（同じソースの client.go）で分ける。
export const TRIES = 3; // 1枚を打つ上限。使い切ったら置き場の issue へ貼る
// rate limited に待つ時間が付かないときに待つ秒数（GitHub の公式の文書「Rate limits for the REST API」: retry-after が無ければ1分以上待つ）。
export const WAIT = 60;

// 落ちた打ちの文言から、止める（名義の誤り）か、次を打つまで何秒待つかを決める。
export function classify(stderr, now = Date.now()) {
  if (stderr.includes("attaching files requires write access to the repository"))
    return { stop: "名義の誤り（上がり先は書く権限の無いトークンに 404 を返す）。GH_TOKEN を見直す" };
  const limited = /rate limited; (?:retry after (.+)|wait and try again)/.exec(stderr);
  if (!limited) return { wait: 0 };
  if (!limited[1]) return { wait: WAIT };
  // retry-after は秒の数なら「N seconds」、日時ならそのままの値で出る。
  const seconds = /^(\d+) seconds/.exec(limited[1]);
  return { wait: seconds ? Number(seconds[1]) : Math.max(0, Math.ceil((Date.parse(limited[1]) - now) / 1e3)) };
}

// run(引数, 名義) は gh を打って { status, stdout, stderr } を返す（名義は "code" か "bot"）。sleep(秒) は待つ。images は
// "<画像>#<見出し>" の並びで、見出しをコメントの文にする。返すのは貼った先の行の並び。
export async function attach({ run, sleep, code, tasks, pr, issue, images }) {
  const said = [];
  for (const image of images) {
    const title = image.slice(image.indexOf("#") + 1);
    const errors = [];
    while (errors.length < TRIES) {
      const r = run(["pr", "comment", String(pr), "-R", code, "--body", title, "--attach", image], "code");
      if (r.status === 0) {
        said.push(`${title}: ${r.stdout.trim()}`);
        break;
      }
      const c = classify(r.stderr);
      if (c.stop) throw new Error(`${image}: ${c.stop}（${r.stderr.trim()}）`);
      errors.push(r.stderr.trim());
      if (errors.length < TRIES) await sleep(c.wait);
    }
    if (errors.length < TRIES) continue;
    // 使い切ったら、置き場の issue へ貼り、Pull Request にそのコメントへのリンクを書く。
    const kept = run(["issue", "comment", String(issue), "-R", tasks, "--body", title, "--attach", image], "bot");
    if (kept.status !== 0) throw new Error(`${image}: Pull Request へ ${TRIES}回、置き場の issue へも貼れなかった（${kept.stderr.trim()}）`);
    const url = kept.stdout.trim();
    const note = [`「${title}」は ${TRIES}回打っても貼れなかったので、置き場の issue に貼った: ${url}`, "", "出た文言:", ...errors.map((e) => `- \`${e}\``)].join("\n");
    const told = run(["pr", "comment", String(pr), "-R", code, "--body", note], "code");
    if (told.status !== 0) throw new Error(`${image}: 置き場の issue に貼った（${url}）が、Pull Request にリンクを書けなかった（${told.stderr.trim()}）`);
    said.push(`${title}: ${url}（Pull Request に貼れず、置き場の issue へ）`);
  }
  return said;
}
