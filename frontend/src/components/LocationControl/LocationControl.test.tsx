import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { LocationSource } from "@/types/route";
import LocationControl from "./LocationControl";

function baseProps() {
  return {
    location: { latitude: 35.123456, longitude: 139.654321 },
    source: "geolocation" as LocationSource,
  };
}

describe("LocationControl", () => {
  it.each([
    ["geolocation" as LocationSource, "現在地[取得済み]"],
    ["default" as LocationSource, "初期地点[東京・王子]"],
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
});
