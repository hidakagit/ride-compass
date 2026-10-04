// 道具と部品の静的な誤り（構文・存在しない import・無い名前の import）を動かさずに落とす。
// 規則はプラグインの errors（実行すれば必ず落ちるものだけを集めた既定の組）をそのまま使う。
import importPlugin from "eslint-plugin-import";

export default [importPlugin.flatConfigs.errors];
