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

// 改善計画T368: 「出発地点: …」の常時表示テキスト＋緯度経度は撤去し、出発地点を
// 手動指定するアイコンボタン1つだけを持つ（状態の説明はaria-label/titleへ退避）。
// GPS取得済みかフォールバックかの視覚的区別は現在地マーカーの色（MapView.tsx）が担う。
describe("LocationControl", () => {
  it("手動入力欄・常時表示テキストは表示されない", () => {
    render(<LocationControl {...baseProps()} />);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/出発地点/)).not.toBeInTheDocument();
    expect(screen.queryByText(/35\.12346, 139\.65432/)).not.toBeInTheDocument();
  });

  it.each([
    ["unset" as const, "geolocation" as LocationSource, "出発地点を指定（現在: 現在地[取得済み] 35.12346, 139.65432）"],
    ["unset" as const, "default" as LocationSource, "出発地点を指定（現在: 初期地点[東京・王子] 35.12346, 139.65432）"],
    ["armed" as const, "geolocation" as LocationSource, "地図をタップして出発地点を指定（タップでキャンセル）"],
    ["manual" as const, "manual" as LocationSource, "現在地に戻す（現在の出発地点: 指定地点 35.12346, 139.65432）"],
  ])("originStateが%s・sourceが%sのときボタンのアクセシブルネームが「%s」になる", (originState, source, label) => {
    render(<LocationControl {...baseProps()} originState={originState} source={source} />);
    expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
  });

  it("ボタン押下でonOriginButtonClickが呼ばれる", async () => {
    const user = userEvent.setup();
    const onOriginButtonClick = vi.fn();
    render(<LocationControl {...baseProps()} onOriginButtonClick={onOriginButtonClick} />);

    await user.click(screen.getByRole("button"));

    expect(onOriginButtonClick).toHaveBeenCalledTimes(1);
  });
});
