// 本番の操作（.github/workflows/prod-ops.yml）を起こし、実行の URL を出す。本番へ入る段はユーザーの承認を待つので、起こした者は
// 問い（「承認:」）を置いて終える（docs/conventions/flow.md「自動で進めないもの」）。操作とソースの選択肢はワークフローの入力だけが持ち、
// 合わない値は GitHub が断る。担当は gh workflow を打てない（tools/flow-gate/settings.json の拒否）ので、この道具の中から起こす。
// gh の既定のトークン（担当では CODE_TOKEN、開発機ではログイン済みの hidakagit）で打つ。
import { execFileSync } from "node:child_process";
import { GitHub } from "../src/github.js";
import { args, config, isNumber } from "./cli.js";

const usage = "node tools/flow-gate/bin/prod.js <issue の番号> <操作> [--source <ソース>] [--commit <コミット>] [--probe <スクリプト>]";
const { rest: [number, operation, ...options] } = args(usage, (a) => isNumber(a[0]) && a[1] && a.length % 2 === 0
  && a.slice(2).every((x, i) => i % 2 || ["--source", "--commit", "--probe"].includes(x)));
const inputs = { issue: number, operation };
for (let i = 0; i < options.length; i += 2) inputs[options[i].slice(2)] = options[i + 1];

const gh = new GitHub(execFileSync("gh", ["auth", "token"], { encoding: "utf8" }).trim());
const { repository, base, prodOps } = config.code;
// return_run_details で、起こした実行の URL が返る（公式の文書「Create a workflow dispatch event」）。起こす要求は打ち直さない（github.js: again）。
const run = await gh.rest("POST", `/repos/${repository}/actions/workflows/${prodOps}/dispatches`, { ref: base, inputs, return_run_details: true });
console.log(`#${number} の本番の操作「${operation}」を起こした。承認を待っている: ${run.html_url}`);
