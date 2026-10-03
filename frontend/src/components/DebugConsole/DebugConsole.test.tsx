/**
 * `components/DebugConsole/DebugConsole.tsx`——デバッグモードの間だけ浮かべる、記録したログの一覧。
 *
 * 見るもの: デバッグモードでないときは何も出さないこと、見出しの件数（出している数/全数）、記録が無いとき・
 * 絞って0件のときの案内、レベルの下限での絞り込み、1行の中身、コピーで渡る文字（出している行だけ）と
 * コピーの結果・失敗の表示、クリア、閉じる操作。
 *
 * ここで見ないもの:
 * - 記録の上限・記録の時刻の書式・デバッグモードの保存 → `lib/debugLog.ts`
 * - コピー済みの表示が戻るまでの時間・失敗の文言の組み立て → `hooks/useCopyToClipboard.ts`
 * - パネルの置き方と閉じるボタン → `components/FloatingPanel/FloatingPanel.tsx`（本物を描く）
 * - 新しい行が来たら一番下まで送ること——送り先の高さはテスト環境に無いレイアウトの実寸で、常に0になる
 *
 * 記録は本物の`lib/debugLog.ts`へ書く。状態はモジュールが持つので、テストごとに空にしてデバッグモードを戻す。
 * 記録の時刻を決めるため、時計（`Date`）だけを止める。クリップボードはテスト環境のものを使う。
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearDebugLog, debugLog, setDebugEnabled } from "@/lib/debugLog";
import DebugConsole from "./DebugConsole";

const AT = new Date(2026, 9, 1, 9, 5, 7, 42);
const TIME = "09:05:07.042";

function renderConsole(open = true) {
  const onClose = vi.fn();
  const view = render(<DebugConsole open={open} onClose={onClose} />);
  return { onClose, view };
}

function logThree() {
  debugLog("map", "タイルを読んだ", { z: 12 });
  debugLog("api", "応答が遅い", undefined, "warn");
  debugLog("api", "生成に失敗", null, "error");
}

function heading(): string {
  return screen.getByText(/^デバッグログ\[/).textContent ?? "";
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(AT);
  vi.spyOn(console, "debug").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
  vi.spyOn(console, "error").mockImplementation(() => {});
  setDebugEnabled(true);
});

afterEach(() => {
  setDebugEnabled(false);
  clearDebugLog();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("DebugConsole", () => {
  it("デバッグモードでなければ、開いていても何も出さない", () => {
    setDebugEnabled(false);

    const { view } = renderConsole();

    expect(view.container).toBeEmptyDOMElement();
  });

  it("閉じている間は何も出さない", () => {
    const { view } = renderConsole(false);

    expect(view.container).toBeEmptyDOMElement();
  });

  it("記録が無いときは待っている旨を出し、コピーは押せない", () => {
    renderConsole();

    expect(heading()).toBe("デバッグログ[0/0件]");
    expect(screen.getByText("イベント待機中...[地図を操作するかAPIを呼び出してください]")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "表示中のログをコピー" })).toBeDisabled();
  });

  it("1行に時刻・分類・文言と、詳細があればその中身を出す", () => {
    logThree();

    renderConsole();

    expect(heading()).toBe("デバッグログ[3/3件]");
    expect(screen.getByText("タイルを読んだ").parentElement?.textContent).toBe(`${TIME} [map] タイルを読んだ {"z":12}`);
    expect(screen.getByText("応答が遅い").parentElement?.textContent).toBe(`${TIME} [api] 応答が遅い`);
    expect(screen.getByText("生成に失敗").parentElement?.textContent).toBe(`${TIME} [api] 生成に失敗`);
  });

  it("開いている間に記録された行も出す", () => {
    renderConsole();

    act(() => debugLog("map", "移動した"));

    expect(screen.getByText("移動した")).toBeInTheDocument();
    expect(heading()).toBe("デバッグログ[1/1件]");
  });

  it.each([
    ["警告以上", ["応答が遅い", "生成に失敗"], "デバッグログ[2/3件]"],
    ["エラーのみ", ["生成に失敗"], "デバッグログ[1/3件]"],
  ])("下限を「%s」にすると、そのレベル以上の行だけを出す", async (option, shown, title) => {
    logThree();
    renderConsole();

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "表示するログレベルの下限" }), option);

    for (const message of ["タイルを読んだ", "応答が遅い", "生成に失敗"]) {
      if (shown.includes(message)) expect(screen.getByText(message)).toBeInTheDocument();
      else expect(screen.queryByText(message)).not.toBeInTheDocument();
    }
    expect(heading()).toBe(title);
  });

  it("絞って1行も残らなければ、全数を添えて戻し方を出し、コピーは押せない", async () => {
    debugLog("map", "タイルを読んだ");
    debugLog("map", "移動した");
    renderConsole();

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "表示するログレベルの下限" }), "エラーのみ");

    expect(
      screen.getByText("条件に一致するログがありません[フィルタを「すべて」に戻すと2件表示されます]"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "表示中のログをコピー" })).toBeDisabled();
  });

  it("コピーすると出している行だけを1行ずつ渡し、コピーしたことを名前で出す", async () => {
    logThree();
    renderConsole();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "表示するログレベルの下限" }), "警告以上");

    await userEvent.click(screen.getByRole("button", { name: "表示中のログをコピー" }));

    expect(await navigator.clipboard.readText()).toBe(`${TIME} [api] 応答が遅い\n${TIME} [api] 生成に失敗`);
    expect(await screen.findByRole("button", { name: "表示中のログをコピーしました" })).toHaveAttribute(
      "title",
      "コピーしました",
    );
  });

  it("コピーの詳細は中身をJSONで渡す", async () => {
    debugLog("map", "タイルを読んだ", { z: 12, ok: true });
    renderConsole();

    await userEvent.click(screen.getByRole("button", { name: "表示中のログをコピー" }));

    await waitFor(async () =>
      expect(await navigator.clipboard.readText()).toBe(`${TIME} [map] タイルを読んだ {"z":12,"ok":true}`),
    );
  });

  it("コピーに失敗すると、その理由を出す", async () => {
    debugLog("map", "タイルを読んだ");
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("書き込みを拒否"));
    renderConsole();

    await userEvent.click(screen.getByRole("button", { name: "表示中のログをコピー" }));

    expect(await screen.findByText(/書き込みを拒否/)).toBeInTheDocument();
  });

  it("クリアを押すと記録が空になり、待っている旨に戻る", async () => {
    logThree();
    renderConsole();

    await userEvent.click(screen.getByRole("button", { name: "クリア" }));

    expect(heading()).toBe("デバッグログ[0/0件]");
    expect(screen.getByText("イベント待機中...[地図を操作するかAPIを呼び出してください]")).toBeInTheDocument();
  });

  it("閉じるボタンを押すと、閉じる操作が上がる", async () => {
    const { onClose } = renderConsole();

    await userEvent.click(screen.getByRole("button", { name: /を閉じる$/ }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
