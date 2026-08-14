import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import RoadFilterDialog from "./RoadFilterDialog";

function baseProps() {
  return {
    open: true,
    onClose: vi.fn(),
    roadHiddenKeysByMode: { surface: [], highway: [] } as Record<"surface" | "highway", readonly string[]>,
    onSave: vi.fn(),
  };
}

describe("RoadFilterDialog", () => {
  it("open=falseのときは何も描画しない", () => {
    const { container } = render(<RoadFilterDialog {...baseProps()} open={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("open=trueでdialogとして表示され、2軸（路面の種類・道路の種類）分のチェックボックスが並ぶ（色分けの選択は無い）", () => {
    render(<RoadFilterDialog {...baseProps()} />);
    expect(screen.getByRole("dialog", { name: "路面の表示設定" })).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /自転車・歩行者道/ })).toBeInTheDocument();
  });

  it("チェックボックスを操作しただけではonSaveは呼ばれない（下書きのまま）", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(<RoadFilterDialog {...baseProps()} onSave={onSave} />);

    await user.click(screen.getByRole("checkbox", { name: /アスファルト/ }));

    expect(onSave).not.toHaveBeenCalled();
  });

  it("保存を押すと、2軸分の下書き状態がまとめてonSaveへ渡りダイアログが閉じる（路面の種類=砂利を外す かつ 道路の種類=自転車・歩行者道のみ、のような組み合わせ）", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(<RoadFilterDialog {...baseProps()} onSave={onSave} onClose={onClose} />);

    await user.click(screen.getByRole("checkbox", { name: /砂利・締固め/ }));
    await user.click(screen.getByRole("checkbox", { name: /幹線道路/ }));
    await user.click(screen.getByRole("button", { name: "保存" }));

    expect(onSave).toHaveBeenCalledWith({
      surface: ["gravel"],
      highway: ["arterial"],
    });
    expect(onClose).toHaveBeenCalled();
  });

  it("キャンセルを押すとonSaveを呼ばずonCloseだけ呼ばれる（編集は破棄）", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(<RoadFilterDialog {...baseProps()} onSave={onSave} onClose={onClose} />);

    await user.click(screen.getByRole("checkbox", { name: /アスファルト/ }));
    await user.click(screen.getByRole("button", { name: "キャンセル" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("×ボタン・背景クリック・Escapeキーいずれでも保存せずonCloseが呼ばれる", async () => {
    const user = userEvent.setup();

    const onCloseX = vi.fn();
    const { unmount: unmountX } = render(<RoadFilterDialog {...baseProps()} onClose={onCloseX} />);
    await user.click(screen.getByRole("button", { name: "閉じる" }));
    expect(onCloseX).toHaveBeenCalled();
    unmountX();

    const onCloseBackdrop = vi.fn();
    const { unmount: unmountBackdrop } = render(<RoadFilterDialog {...baseProps()} onClose={onCloseBackdrop} />);
    await user.click(screen.getByRole("dialog").parentElement as HTMLElement);
    expect(onCloseBackdrop).toHaveBeenCalled();
    unmountBackdrop();

    const onCloseEscape = vi.fn();
    render(<RoadFilterDialog {...baseProps()} onClose={onCloseEscape} />);
    await user.keyboard("{Escape}");
    expect(onCloseEscape).toHaveBeenCalled();
  });

  it("ダイアログ内のクリックは背景クリック扱いにならない（誤って閉じない）", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<RoadFilterDialog {...baseProps()} onClose={onClose} />);

    await user.click(screen.getByRole("dialog"));

    expect(onClose).not.toHaveBeenCalled();
  });

  it("保存済みの状態を初期値として下書きを作る（前回保存分が反映されている）", () => {
    render(
      <RoadFilterDialog {...baseProps()} roadHiddenKeysByMode={{ surface: ["gravel"], highway: [] }} />,
    );

    expect(screen.getByRole("checkbox", { name: /砂利・締固め/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeChecked();
  });

  it("開き直すと、前回キャンセルした未保存の編集は残らず保存済み状態に戻る", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<RoadFilterDialog {...baseProps()} />);

    // 保存済み状態(全チェックON)から1つ外す→キャンセルで閉じる
    await user.click(screen.getByRole("checkbox", { name: /アスファルト/ }));
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).not.toBeChecked();
    rerender(<RoadFilterDialog {...baseProps()} open={false} />);

    // 再度開く（保存されていないので実状態=roadHiddenKeysByModeは変わっていない）
    rerender(<RoadFilterDialog {...baseProps()} open={true} />);

    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeChecked();
  });
});
