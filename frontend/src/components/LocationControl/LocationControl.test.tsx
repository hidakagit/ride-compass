import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { LocationSource } from "@/types/route";
import LocationControl from "./LocationControl";

function baseProps() {
  return {
    location: { latitude: 35.123456, longitude: 139.654321 },
    source: "geolocation" as LocationSource,
    manualLat: "",
    manualLng: "",
    showManualInput: false,
    onManualLatChange: vi.fn(),
    onManualLngChange: vi.fn(),
    onToggleManualInput: vi.fn(),
    onManualSubmit: vi.fn(),
  };
}

describe("LocationControl", () => {
  it.each([
    ["geolocation" as LocationSource, "現在地（取得済み）"],
    ["manual" as LocationSource, "手動入力"],
    ["default" as LocationSource, "デフォルト（東京・王子）"],
  ])("sourceが%sのとき「%s」が表示される", (source, label) => {
    render(<LocationControl {...baseProps()} source={source} />);
    // selectorをspanに絞る: 「手動入力」等のラベルは「緯度経度を手動入力」ボタンの
    // テキストとも部分一致してしまうため、位置情報を表示するspan要素に限定する。
    expect(screen.getByText(new RegExp(label), { selector: "span" })).toBeInTheDocument();
  });

  it("緯度経度が小数点以下5桁でフォーマットされて表示される", () => {
    render(<LocationControl {...baseProps()} />);
    expect(screen.getByText(/35\.12346, 139\.65432/)).toBeInTheDocument();
  });

  it("showManualInput=falseのとき手動入力フォームが表示されない", () => {
    render(<LocationControl {...baseProps()} showManualInput={false} />);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("「緯度経度を手動入力」ボタンをクリックするとonToggleManualInputが呼ばれる", async () => {
    const user = userEvent.setup();
    const onToggleManualInput = vi.fn();
    render(<LocationControl {...baseProps()} onToggleManualInput={onToggleManualInput} />);

    await user.click(screen.getByRole("button", { name: "緯度経度を手動入力" }));

    expect(onToggleManualInput).toHaveBeenCalled();
  });

  it("showManualInput=trueのとき手動入力フォームが表示されmanualLat/manualLngの値が反映される", () => {
    render(<LocationControl {...baseProps()} showManualInput={true} manualLat="35.5" manualLng="139.5" />);

    const textboxes = screen.getAllByRole("textbox") as HTMLInputElement[];
    expect(textboxes).toHaveLength(2);
    expect(textboxes[0]).toHaveValue("35.5");
    expect(textboxes[1]).toHaveValue("139.5");
  });

  it("緯度・経度inputへの入力でそれぞれonManualLatChange/onManualLngChangeが呼ばれる", async () => {
    const user = userEvent.setup();
    const onManualLatChange = vi.fn();
    const onManualLngChange = vi.fn();
    render(
      <LocationControl
        {...baseProps()}
        showManualInput={true}
        onManualLatChange={onManualLatChange}
        onManualLngChange={onManualLngChange}
      />,
    );

    const [latInput, lngInput] = screen.getAllByRole("textbox");
    await user.type(latInput, "1");
    await user.type(lngInput, "2");

    expect(onManualLatChange).toHaveBeenCalledWith("1");
    expect(onManualLngChange).toHaveBeenCalledWith("2");
  });

  it("フォーム送信でonManualSubmitが呼ばれる", async () => {
    const user = userEvent.setup();
    const onManualSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    render(<LocationControl {...baseProps()} showManualInput={true} onManualSubmit={onManualSubmit} />);

    await user.click(screen.getByRole("button", { name: "設定" }));

    expect(onManualSubmit).toHaveBeenCalled();
  });
});
