import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DialogContent, DialogRoot } from "./Dialog";

function ControlledDialog() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>開く</button>
      <DialogRoot open={open} onOpenChange={setOpen}>
        <DialogContent title="設定">中身</DialogContent>
      </DialogRoot>
    </>
  );
}

describe("Dialog", () => {
  it("閉じるボタンを押すとContentが閉じる", async () => {
    const user = userEvent.setup();
    render(<ControlledDialog />);

    await user.click(screen.getByRole("button", { name: "開く" }));
    await user.click(screen.getByRole("button", { name: "閉じる" }));

    expect(screen.queryByText("中身")).not.toBeInTheDocument();
  });
});
