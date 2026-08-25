import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DialogContent, DialogRoot } from "./Dialog";

// DialogTrigger（RadixDialog.Triggerの再export）は削除済み（唯一の利用者AxisStudioが
// 制御コンポーネント方式で使っているため不要）。テストもAxisStudioと同じ
// <DialogRoot open={...} onOpenChange={...}>の制御パターンで開閉する。
function ControlledDialog({ title, hideTitle }: { title: string; hideTitle?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>開く</button>
      <DialogRoot open={open} onOpenChange={setOpen}>
        <DialogContent title={title} hideTitle={hideTitle}>
          中身
        </DialogContent>
      </DialogRoot>
    </>
  );
}

describe("Dialog", () => {
  it("初期状態ではContentが表示されない", () => {
    render(<ControlledDialog title="設定" />);
    expect(screen.queryByText("中身")).not.toBeInTheDocument();
  });

  it("openをtrueにするとContentが表示され、titleがaccessible nameになる", async () => {
    const user = userEvent.setup();
    render(<ControlledDialog title="設定" />);

    await user.click(screen.getByRole("button", { name: "開く" }));

    expect(screen.getByRole("dialog", { name: "設定" })).toBeInTheDocument();
    expect(screen.getByText("中身")).toBeInTheDocument();
  });

  it("閉じるボタンを押すとContentが閉じる", async () => {
    const user = userEvent.setup();
    render(<ControlledDialog title="設定" />);

    await user.click(screen.getByRole("button", { name: "開く" }));
    await user.click(screen.getByRole("button", { name: "閉じる" }));

    expect(screen.queryByText("中身")).not.toBeInTheDocument();
  });

  it("hideTitle指定時もaccessible nameは維持される(視覚的にのみ隠れる)", async () => {
    const user = userEvent.setup();
    render(<ControlledDialog title="設定" hideTitle />);

    await user.click(screen.getByRole("button", { name: "開く" }));

    expect(screen.getByRole("dialog", { name: "設定" })).toBeInTheDocument();
  });
});
