// 振り出しが止まっていないかを見張る（GitHub Actions の定期実行 .github/workflows/coordinator-watch.yml が呼ぶ）。
// 起動役の最後の状況の更新が古ければ Off track を足す（hidakagit-bot の名義）。
// 使い方: node tools/flow-gate/bin/watch.js
import config from "../flow.config.json" with { type: "json" };
import { GitHub } from "../src/github.js";
import { watchCoordinator } from "../src/status.js";
import { botToken } from "./token.js";

console.log(await watchCoordinator(new GitHub(botToken()), config));
