import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearDebugLog, debugLog, setDebugEnabled } from "@/lib/debugLog";
import DebugConsole from "./DebugConsole";

// システム状況（commit・起動日時・外部API呼出サマリ）はSystemStatusPanelへ分離済み
// （2026-08-16、ユーザーFB「中身が混ざって見にくい」）。DebugConsoleはログ本文のみを
// 扱うことを確認する。
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

  it("記録済みのログ本文のみを表示し、システム状況は含まない", () => {
    setDebugEnabled(true);
    act(() => debugLog("map", "タイル要求", { z: 14 }));

    render(<DebugConsole open onClose={() => {}} />);

    expect(screen.getByText("デバッグログ[1/1件]")).toBeInTheDocument();
    expect(screen.getByText("タイル要求")).toBeInTheDocument();
    expect(screen.queryByText("システム状況")).not.toBeInTheDocument();
    expect(screen.queryByText(/engine/)).not.toBeInTheDocument();
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
