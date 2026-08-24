import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
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

  it("クリックするとonClickが呼ばれる", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>押す</Button>);

    await user.click(screen.getByRole("button", { name: "押す" }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("disabled指定時はクリックできずaria状態も反映される", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        押す
      </Button>
    );

    const button = screen.getByRole("button", { name: "押す" });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("variant/sizeに応じたクラスが付与される", () => {
    render(
      <Button variant="primary" size="sm">
        押す
      </Button>
    );
    const button = screen.getByRole("button", { name: "押す" });
    expect(button.className).toContain("bg-[var(--color-accent)]");
    expect(button.className).toContain("px-2");
  });

  it("classNameを渡すと合成される(tailwind-mergeで同種プロパティは後勝ち)", () => {
    render(<Button className="px-10">押す</Button>);
    const button = screen.getByRole("button", { name: "押す" });
    expect(button.className).toContain("px-10");
    expect(button.className).not.toMatch(/px-\[0\.9rem\]/);
  });
});
