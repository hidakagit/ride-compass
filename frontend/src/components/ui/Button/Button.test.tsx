import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "./Button";

describe("Button", () => {
  it("type未指定時はtype=buttonになる(フォーム内での誤送信を防ぐ)", () => {
    render(<Button>押す</Button>);
    expect(screen.getByRole("button", { name: "押す" })).toHaveAttribute("type", "button");
  });

  it("type='submit'を明示すればそのまま反映される", () => {
    render(<Button type="submit">送信</Button>);
    expect(screen.getByRole("button", { name: "送信" })).toHaveAttribute("type", "submit");
  });
});
