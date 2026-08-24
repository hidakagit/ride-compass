import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Input } from "./Input";

describe("Input", () => {
  it("type='number'を指定すればspinbuttonロールになる", () => {
    render(<Input type="number" aria-label="距離" />);
    expect(screen.getByRole("spinbutton", { name: "距離" })).toBeInTheDocument();
  });

  it("type='text'では入力値の変更がonChangeへ伝わる", async () => {
    const user = userEvent.setup();
    render(<Input type="text" aria-label="名前" />);

    const input = screen.getByRole("textbox", { name: "名前" });
    await user.type(input, "abc");

    expect(input).toHaveValue("abc");
  });

  it("invalidを指定するとaria-invalidが付与される", () => {
    render(<Input aria-label="値" invalid />);
    expect(screen.getByRole("textbox", { name: "値" })).toHaveAttribute("aria-invalid", "true");
  });

  it("invalid未指定時はaria-invalidが付かない", () => {
    render(<Input aria-label="値" />);
    expect(screen.getByRole("textbox", { name: "値" })).not.toHaveAttribute("aria-invalid");
  });
});
