// 担当のワークフロー（.github/workflows/claude-task.yml）の後始末。担当が落ちても止められても走る。利用の上限・認証で止まったなら
// 振り出しを止め（コードのリポジトリの変数 coordinator.pauseVariable に止める時刻を置き。src/after.js: pauseOf）、手番の記録を置き場の
// リリースへ置いて、issue に終わりを書く。ステータスは書かない（実行の終わりを受けたゲートが決める）。
import { existsSync, readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { endReport, keepLog, pauseOf } from "../src/after.js";
import { args, bot, code, config, isNumber } from "./cli.js";

const { dry, rest: [number, kind, file, url, jobStatus] } = args("node tools/flow-gate/bin/after.js [--dry-run] <issue の番号> <作る|確かめる> <実行のファイル（無ければ空）> <実行の URL> <ジョブの結果>",
  (a) => a.length === 5 && isNumber(a[0]) && Object.keys(config.coordinator.slots).includes(a[1]));
const raw = file && existsSync(file) ? readFileSync(file) : null;
const messages = raw ? JSON.parse(raw.toString("utf8")) : null;
const gh = bot();
const done = [];
const note = (line) => (console.log(line), done.push(line));

const quota = pauseOf(messages, jobStatus);
if (quota) {
  const { pauseVariable: name, pauseMinutes } = config.coordinator;
  const until = new Date(Date.now() + pauseMinutes * 60e3).toISOString();
  const path = `/repos/${config.code.repository}/actions/variables`;
  const repo = code();
  note(dry ? `（試し）振り出しを ${until} まで止めた（${quota}）` : await repo.rest("PATCH", `${path}/${name}`, { name, value: until })
    .catch(() => repo.rest("POST", path, { name, value: until }))
    .then(() => `Claude の利用の上限か認証で止まった（${quota}）ので、振り出しを ${until} まで止めた`, (e) => `振り出しを止められなかった（${e.message}）`));
}

if (!raw) note("手番の記録は無い（実行のファイルが無い）");
else if (dry) note("（試し）手番の記録を置き場のリリースへ置く");
else {
  const name = `tasks-${number}-${url.split("/").pop()}-${new Date().toISOString().replace(/\D/g, "").slice(0, 14)}.json.gz`;
  note(await keepLog(gh, config.repository, { gz: gzipSync(raw), name }).then((link) => `手番の記録を置いた: ${link}`, (e) => `手番の記録を置けなかった（${e.message}）`));
}

const body = endReport({ kind, url, messages, done });
if (dry) console.log(body);
else await gh.rest("POST", `/repos/${config.repository}/issues/${number}/comments`, { body });
