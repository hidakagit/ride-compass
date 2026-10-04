/**
 * `lib/researchMode.ts`——研究モードのオン/オフを持つシングルトン。
 *
 * 状態はモジュールが持ち、初期値は読み込んだ時点の保存値で決まる。テストごとにモジュールを読み込み直し
 * （ページの再読み込みにあたる）、localStorageはテスト環境のものを使う。
 *
 * ここで見ないもの:
 * - localStorageが使えない環境での読み書き → `lib/safeStorage.test.ts`
 * - 状態を画面へ届けること（`useSyncExternalStore`）と、研究モードで出るもの → `hooks/useResearchMode.ts`を使う部品のテスト
 */
import { afterEach, describe, expect, it, vi } from "vitest";

async function loadResearchMode() {
  vi.resetModules();
  return import("@/lib/researchMode");
}

afterEach(() => {
  window.localStorage.clear();
});

describe("研究モード", () => {
  it("保存が無ければオフで始まる", async () => {
    expect((await loadResearchMode()).isResearchEnabled()).toBe(false);
  });

  it("切り替えた状態は、ページを読み込み直しても続く", async () => {
    (await loadResearchMode()).setResearchEnabled(true);
    const reloaded = await loadResearchMode();
    expect(reloaded.isResearchEnabled()).toBe(true);

    reloaded.setResearchEnabled(false);
    expect((await loadResearchMode()).isResearchEnabled()).toBe(false);
  });

  it("切り替えると購読者の全員へ知らせ、購読をやめた購読者にだけ知らせなくなる", async () => {
    const mode = await loadResearchMode();
    const kept = vi.fn();
    const dropped = vi.fn();
    mode.subscribeResearchMode(kept);
    const unsubscribe = mode.subscribeResearchMode(dropped);

    mode.setResearchEnabled(true);
    expect(kept).toHaveBeenCalledTimes(1);
    expect(dropped).toHaveBeenCalledTimes(1);

    unsubscribe();
    mode.setResearchEnabled(false);
    expect(kept).toHaveBeenCalledTimes(2);
    expect(dropped).toHaveBeenCalledTimes(1);
  });
});
