/**
 * `lib/debugLog.ts`——デバッグモードのオン/オフと、オンの間の記録を持つシングルトン。
 *
 * 状態はモジュールが持ち、初期のオン/オフは読み込んだ時点の保存値で決まる。テストごとにモジュールを読み込み直し
 * （ページの再読み込みにあたる）、localStorageはテスト環境のものを使う。ブラウザのコンソールは外への出口なので、
 * 差し替えて何が出たかを見る。
 *
 * ここで見ないもの:
 * - localStorageが使えない環境での読み書き → `lib/safeStorage.test.ts`
 * - 状態を画面へ届けること（`useSyncExternalStore`） → `hooks/useDebugLog.ts`を使う部品のテスト
 * - 何をいつ記録するか → 記録する側（`lib/apiClient.test.ts`等）
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

async function loadDebugLog() {
  vi.resetModules();
  return import("@/lib/debugLog");
}

let consoleDebug: ReturnType<typeof vi.spyOn>;
let consoleWarn: ReturnType<typeof vi.spyOn>;
let consoleError: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  consoleDebug = vi.spyOn(console, "debug").mockImplementation(() => {});
  consoleWarn = vi.spyOn(console, "warn").mockImplementation(() => {});
  consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("オン/オフ", () => {
  it("保存が無ければオフで始まり、記録もコンソールへの出力もしない", async () => {
    const log = await loadDebugLog();

    log.debugLog("cat_a", "記録A");

    expect(log.isDebugEnabled()).toBe(false);
    expect(log.getDebugLogEntries()).toEqual([]);
    expect(consoleDebug).not.toHaveBeenCalled();
  });

  it("切り替えた状態は、ページを読み込み直しても続く", async () => {
    (await loadDebugLog()).setDebugEnabled(true);
    const reloaded = await loadDebugLog();
    expect(reloaded.isDebugEnabled()).toBe(true);

    reloaded.setDebugEnabled(false);
    expect((await loadDebugLog()).isDebugEnabled()).toBe(false);
  });

  it("切り替えると購読者の全員へ知らせ、購読をやめた購読者にだけ知らせなくなる", async () => {
    const log = await loadDebugLog();
    const kept = vi.fn();
    const dropped = vi.fn();
    log.subscribeDebugLog(kept);
    const unsubscribe = log.subscribeDebugLog(dropped);

    log.setDebugEnabled(true);
    expect(kept).toHaveBeenCalledTimes(1);
    expect(dropped).toHaveBeenCalledTimes(1);

    unsubscribe();
    log.setDebugEnabled(false);
    expect(kept).toHaveBeenCalledTimes(2);
    expect(dropped).toHaveBeenCalledTimes(1);
  });
});

describe("オンの間の記録", () => {
  it("1件ごとに、通し番号・時刻・分類・文言・詳細・重さを持つ記録を足し、購読者へ知らせる", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 0, 2, 9, 8, 7, 5));
    const log = await loadDebugLog();
    log.setDebugEnabled(true);
    const listener = vi.fn();
    log.subscribeDebugLog(listener);

    log.debugLog("cat_a", "記録A", { n: 1 });
    log.debugLog("cat_b", "記録B", undefined, "warn");

    const [first, second] = log.getDebugLogEntries();
    expect(first).toEqual({
      id: first.id,
      time: "09:08:07.005",
      category: "cat_a",
      message: "記録A",
      detail: { n: 1 },
      level: "info",
    });
    expect(second).toMatchObject({ category: "cat_b", message: "記録B", level: "warn" });
    expect(second.id).toBe(first.id + 1);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["info", () => consoleDebug],
    ["warn", () => consoleWarn],
    ["error", () => consoleError],
  ] as const)("重さ%sの記録は、それに合うコンソールの出口へ分類と文言を出す", async (level, consoleFn) => {
    const log = await loadDebugLog();
    log.setDebugEnabled(true);

    log.debugLog("cat_a", "記録A", { n: 1 }, level);

    expect(consoleFn()).toHaveBeenCalledWith("[RideCompass Debug] [cat_a] 記録A", { n: 1 });
    const outputs = consoleDebug.mock.calls.length + consoleWarn.mock.calls.length + consoleError.mock.calls.length;
    expect(outputs).toBe(1);
  });

  it("詳細が無ければ、コンソールへは空文字を添える", async () => {
    const log = await loadDebugLog();
    log.setDebugEnabled(true);

    log.debugLog("cat_a", "記録A");

    expect(consoleDebug).toHaveBeenCalledWith("[RideCompass Debug] [cat_a] 記録A", "");
  });

  it("記録が変わるたびに新しい一覧を返し、変わらなければ同じ一覧を返す", async () => {
    const log = await loadDebugLog();
    log.setDebugEnabled(true);
    const before = log.getDebugLogEntries();

    log.debugLog("cat_a", "記録A");
    const after = log.getDebugLogEntries();

    expect(after).not.toBe(before);
    expect(before).toEqual([]);
    expect(log.getDebugLogEntries()).toBe(after);
  });

  it("溜まりすぎたら古い記録から捨て、件数を保つ", async () => {
    const log = await loadDebugLog();
    log.setDebugEnabled(true);
    for (let i = 0; i < 1000; i += 1) log.debugLog("cat_a", `記録${i}`);
    const kept = log.getDebugLogEntries();
    expect(kept.length).toBeLessThan(1000);

    log.debugLog("cat_a", "最新");

    const next = log.getDebugLogEntries();
    expect(next).toHaveLength(kept.length);
    expect(next[0].id).toBe(kept[0].id + 1);
    expect(next.at(-1)?.message).toBe("最新");
  });

  it("消すと一覧が空になり、購読者へ知らせる", async () => {
    const log = await loadDebugLog();
    log.setDebugEnabled(true);
    log.debugLog("cat_a", "記録A");
    const listener = vi.fn();
    log.subscribeDebugLog(listener);

    log.clearDebugLog();

    expect(log.getDebugLogEntries()).toEqual([]);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
