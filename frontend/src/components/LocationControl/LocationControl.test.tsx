import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { LocationSource } from "@/types/route";
import LocationControl from "./LocationControl";

function baseProps() {
  return {
    location: { latitude: 35.123456, longitude: 139.654321 },
    source: "geolocation" as LocationSource,
    originState: "unset" as const,
    onOriginButtonClick: vi.fn(),
  };
}

describe("LocationControl", () => {
  it.each([
    ["geolocation" as LocationSource, "現在地[取得済み]"],
    ["default" as LocationSource, "初期地点[東京・王子]"],
    ["manual" as LocationSource, "指定地点"],
  ])("sourceが%sのとき「%s」が表示される", (source, label) => {
    render(<LocationControl {...baseProps()} source={source} />);
    // ラベルに含まれる[]は正規表現の特殊文字（文字クラス）のためエスケープしてから使う
    const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    expect(screen.getByText(new RegExp(escaped), { selector: "span" })).toBeInTheDocument();
  });

  it("緯度経度が小数点以下5桁でフォーマットされて表示される", () => {
    render(<LocationControl {...baseProps()} />);
    expect(screen.getByText(/35\.12346, 139\.65432/)).toBeInTheDocument();
  });

  it("手動入力欄は表示されない", () => {
    render(<LocationControl {...baseProps()} />);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  describe("compact", () => {
    it("座標を省いた1行表示になり、詳細はtitle属性に残る", () => {
      render(<LocationControl {...baseProps()} compact />);
      expect(screen.getByText(/出発: 現在地\[取得済み\]/)).toBeInTheDocument();
      expect(screen.queryByText(/35\.12346, 139\.65432/)).not.toBeInTheDocument();
      expect(screen.getByText(/出発: 現在地\[取得済み\]/)).toHaveAttribute(
        "title",
        "出発地点: 現在地[取得済み] (35.12346, 139.65432)"
      );
    });
  });

  describe("改善計画T366: 出発地点の手動指定ボタン", () => {
    it.each([
      ["unset" as const, "出発地点を指定（地図をタップ）"],
      ["armed" as const, "地図をタップして出発地点を指定（タップでキャンセル）"],
      ["manual" as const, "現在地に戻す"],
    ])("originStateが%sのときボタンのアクセシブルネームが「%s」になる", (originState, label) => {
      render(<LocationControl {...baseProps()} originState={originState} />);
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    });

    it("ボタン押下でonOriginButtonClickが呼ばれる", async () => {
      const user = userEvent.setup();
      const onOriginButtonClick = vi.fn();
      render(<LocationControl {...baseProps()} onOriginButtonClick={onOriginButtonClick} />);

      await user.click(screen.getByRole("button", { name: "出発地点を指定（地図をタップ）" }));

      expect(onOriginButtonClick).toHaveBeenCalledTimes(1);
    });
  });
});
