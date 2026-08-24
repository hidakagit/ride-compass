import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DialogContent, DialogRoot, DialogTrigger } from "./Dialog";

describe("Dialog", () => {
  it("初期状態ではContentが表示されない", () => {
    render(
      <DialogRoot>
        <DialogTrigger>開く</DialogTrigger>
        <DialogContent title="設定">中身</DialogContent>
      </DialogRoot>
    );
    expect(screen.queryByText("中身")).not.toBeInTheDocument();
  });

  it("Triggerを押すとContentが表示され、titleがaccessible nameになる", async () => {
    const user = userEvent.setup();
    render(
      <DialogRoot>
        <DialogTrigger>開く</DialogTrigger>
        <DialogContent title="設定">中身</DialogContent>
      </DialogRoot>
    );

    await user.click(screen.getByRole("button", { name: "開く" }));

    expect(screen.getByRole("dialog", { name: "設定" })).toBeInTheDocument();
    expect(screen.getByText("中身")).toBeInTheDocument();
  });

  it("閉じるボタンを押すとContentが閉じる", async () => {
    const user = userEvent.setup();
    render(
      <DialogRoot>
        <DialogTrigger>開く</DialogTrigger>
        <DialogContent title="設定">中身</DialogContent>
      </DialogRoot>
    );

    await user.click(screen.getByRole("button", { name: "開く" }));
    await user.click(screen.getByRole("button", { name: "閉じる" }));

    expect(screen.queryByText("中身")).not.toBeInTheDocument();
  });

  it("hideTitle指定時もaccessible nameは維持される(視覚的にのみ隠れる)", async () => {
    const user = userEvent.setup();
    render(
      <DialogRoot>
        <DialogTrigger>開く</DialogTrigger>
        <DialogContent title="設定" hideTitle>
          中身
        </DialogContent>
      </DialogRoot>
    );

    await user.click(screen.getByRole("button", { name: "開く" }));

    expect(screen.getByRole("dialog", { name: "設定" })).toBeInTheDocument();
  });
});
