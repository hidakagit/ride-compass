// 担当のワークフロー（.github/workflows/claude-task.yml）の後始末。担当が落ちても止められても走る。
// 担当の外の失敗（src/after.js: classify）なら、作る担当のタスクを未着手へ戻し（戻す）、利用の上限・認証なら振り出しを
// coordinator.pauseMinutes の間止める（リポジトリの変数 coordinator.pauseVariable に止める時刻を置く。振り出しが読む）。
// それ以外で作る担当のタスクが進行中のまま（PR も問いも出さずに終わった）なら、落ちたとみなして保留にする。
// 使い方: node tools/flow-gate/bin/after.js <issue の番号> <作る|確かめる> <実行のファイル（無ければ空）> <実行の URL> <ジョブの結果>
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import config from "../flow.config.json" with { type: "json" };
import { classify } from "../src/after.js";
import { GitHub } from "../src/github.js";
import { codeToken } from "./token.js";

const [number, kind, file, url, status, ...rest] = process.argv.slice(2);
if (!/^\d+$/.test(number ?? "") || !["作る", "確かめる"].includes(kind) || rest.length) {
  console.error("使い方: node tools/flow-gate/bin/after.js <issue の番号> <作る|確かめる> <実行のファイル> <実行の URL> <ジョブの結果>");
  process.exit(2);
}
const here = dirname(fileURLToPath(import.meta.url));
const messages = file && existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : null;
// 持ち時間を超えた・手で Cancel された（ジョブの結果 cancelled）は担当の側の止まりなので、上限と見分けて落ちたとして扱う。
const verdict = status === "cancelled" ? { outside: false, pause: false, reason: "" } : classify(messages);
const move = (on, reason) => {
  try {
    console.log(execFileSync(process.execPath, [join(here, "move.js"), number, on, reason], { encoding: "utf8" }).trim());
  } catch (e) {
    console.log(`動かさなかった（${String(e.stderr || e.message).trim().split("\n").at(-1)}）`);
  }
};

if (verdict.pause) {
  const { pauseVariable, pauseMinutes } = config.coordinator;
  const until = new Date(Date.now() + pauseMinutes * 60000).toISOString();
  const code = new GitHub(codeToken());
  const path = `/repos/${config.code.repository}/actions/variables`;
  try {
    await code.rest("PATCH", `${path}/${pauseVariable}`, { name: pauseVariable, value: until });
  } catch {
    await code.rest("POST", path, { name: pauseVariable, value: until });
  }
  console.log(`振り出しを ${until} まで止めた（${verdict.reason}）`);
}
if (kind === "作る") {
  if (verdict.outside) move("戻す", `Actions の作る担当（実行 ${url}）が${verdict.reason}。担当の仕事の外の失敗なので未着手へ戻す`);
  else move("落ちた", `Actions の作る担当（実行 ${url}）が、Pull Request も問いも出さずに終わった（結果: ${status}${status === "cancelled" ? "。持ち時間を超えたか、Cancel された" : ""}）`);
}
