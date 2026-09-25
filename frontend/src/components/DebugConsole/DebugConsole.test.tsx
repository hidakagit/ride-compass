import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearDebugLog, debugLog, setDebugEnabled } from "@/lib/debugLog";
import DebugConsole from "./DebugConsole";

describe("DebugConsole", () => {
  beforeEach(() => {
    setDebugEnabled(false);
    clearDebugLog();
  });

  it("デバッグモードOFFのときは何も描画しない", () => {
    setDebugEnabled(true); // ログを積めるようにしてから記録し、その後OFFにする
    act(() => debugLog("test", "イベント"));
    setDebugEnabled(false);
    const { container } = render(<DebugConsole open onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("open:falseのときは何も描画しない", () => {
    setDebugEnabled(true);
    const { container } = render(<DebugConsole open={false} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("記録済みのログを、見出しに表示中と全体の件数を添えて出す", () => {
    setDebugEnabled(true);
    act(() => debugLog("map", "タイル要求", { z: 14 }));

    render(<DebugConsole open onClose={() => {}} />);

    expect(screen.getByText("デバッグログ[1/1件]")).toBeInTheDocument();
    expect(screen.getByText("タイル要求")).toBeInTheDocument();
  });

  it("ログが1件も無い間は、待っていることを出し、コピーは押せない", () => {
    setDebugEnabled(true);
    render(<DebugConsole open onClose={() => {}} />);

    expect(screen.getByText(/イベント待機中/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "表示中のログをコピー" })).toBeDisabled();
  });

  it("絞り込みで1件も見えなくなったら、戻せば見える件数を添えて知らせ、コピーは押せない", () => {
    setDebugEnabled(true);
    act(() => debugLog("map", "通常イベント", undefined, "info"));
    render(<DebugConsole open onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText("表示するログレベルの下限"), { target: { value: "error" } });

    expect(screen.getByText(/条件に一致するログがありません.*1件表示されます/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "表示中のログをコピー" })).toBeDisabled();
  });

  it("表示中のログを、行の形そのままでクリップボードへ渡す", async () => {
    setDebugEnabled(true);
    act(() => debugLog("map", "タイル要求", { z: 14 }));
    act(() => debugLog("api", "失敗", undefined, "error"));
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    render(<DebugConsole open onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "表示中のログをコピー" }));

    expect(writeText).toHaveBeenCalledTimes(1);
    const text = writeText.mock.calls[0][0] as string;
    expect(text.split("\n")).toHaveLength(2);
    expect(text).toContain('[map] タイル要求 {"z":14}');
    expect(text).toContain("[api] 失敗");
    expect(await screen.findByRole("button", { name: "表示中のログをコピーしました" })).toBeInTheDocument();
  });

  it("絞り込み中は、見えている行だけを渡す（絞って見つけた数行を渡せるようにする）", () => {
    setDebugEnabled(true);
    act(() => debugLog("map", "ふつうの行"));
    act(() => debugLog("api", "エラーの行", undefined, "error"));
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    render(<DebugConsole open onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("表示するログレベルの下限"), { target: { value: "error" } });
    fireEvent.click(screen.getByRole("button", { name: "表示中のログをコピー" }));

    const text = writeText.mock.calls[0][0] as string;
    expect(text).toContain("エラーの行");
    expect(text).not.toContain("ふつうの行");
  });

  it("クリアボタンでログが消える", () => {
    setDebugEnabled(true);
    act(() => debugLog("map", "タイル要求"));
    render(<DebugConsole open onClose={() => {}} />);
    expect(screen.getByText("デバッグログ[1/1件]")).toBeInTheDocument();

    act(() => screen.getByRole("button", { name: "クリア" }).click());

    expect(screen.getByText("デバッグログ[0/0件]")).toBeInTheDocument();
  });

  it("ログレベルの下限でフィルタできる", () => {
    setDebugEnabled(true);
    act(() => {
      debugLog("map", "通常イベント", undefined, "info");
      debugLog("weather", "警告イベント", undefined, "warn");
      debugLog("weather", "失敗イベント", undefined, "error");
    });
    render(<DebugConsole open onClose={() => {}} />);
    expect(screen.getByText("デバッグログ[3/3件]")).toBeInTheDocument();
    expect(screen.getByText("通常イベント")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("表示するログレベルの下限"), { target: { value: "error" } });

    expect(screen.getByText("デバッグログ[1/3件]")).toBeInTheDocument();
    expect(screen.queryByText("通常イベント")).not.toBeInTheDocument();
    expect(screen.queryByText("警告イベント")).not.toBeInTheDocument();
    expect(screen.getByText("失敗イベント")).toBeInTheDocument();
  });

  it("閉じるボタンでonCloseが呼ばれる", () => {
    setDebugEnabled(true);
    const onClose = vi.fn();
    render(<DebugConsole open onClose={onClose} />);
    screen.getByRole("button", { name: /デバッグログ.*件.*を閉じる/ }).click();
    expect(onClose).toHaveBeenCalledOnce();
  });
});
