import type { HardFilterOverride } from "@/types/route";

// 保存された0次ハードフィルタのキー集合を、現在の正本へ合わせる。
//
// backendの`_check_filter_keys`はキー集合の**完全一致**を要求する（domain/evaluation.py）。
// localStorageの保存値はそれを書き込んだ時点のキー集合を持つため、デプロイでフィルタが
// 増減すると、復元した値をそのまま送ってルート生成が全て422になる。正本
// （`routeGenerateConfig.hard_filters`から導出した`DEFAULT_HARD_FILTERS`）のキーだけを
// 持つ形へ整合させることで、保存値をまたいだデプロイでも送信が成立する。
//
// `route_preference`側の同じ問題は`routePreferenceSync.ts`が扱う（あちらは軸カタログが
// 実行時フェッチのため、復元時ではなくマウント時と送信時に補正する）。
export function syncHardFilterKeys(
  stored: HardFilterOverride,
  canonical: HardFilterOverride
): HardFilterOverride {
  const synced: HardFilterOverride = {};
  for (const [key, defaultEnabled] of Object.entries(canonical)) {
    // 保存値にあるキーは利用者の選択を尊重し、無いキー（新設されたフィルタ）は既定値。
    synced[key] = typeof stored[key] === "boolean" ? stored[key] : defaultEnabled;
  }
  return synced;
}
