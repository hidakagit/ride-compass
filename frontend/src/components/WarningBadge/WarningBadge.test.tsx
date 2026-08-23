import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import WarningBadgeList, { type WarningBadgeItem } from "./WarningBadge";

// CSS Modulesはテスト環境でも"_<クラス名>_<ハッシュ>"の形にハッシュ化されるため（例:
// "warning"→"_warning_e85858"）、単純な部分一致だと"wbgt_warning"が"warning"を部分文字列
// として含んでしまい区別できない。クラストークンの先頭が完全に一致するかで判定する。
function hasColorClass(className: string, colorClassName: string): boolean {
  return className.split(" ").some((token) => new RegExp(`^_?${colorClassName}_`).test(token));
}

// UI改善（2026-08-24）: 天候ヘッダーが常に1行に収まるよう、常時表示は「最高警戒度+件数の
// サマリーボタン1個」のみへ変更した（以前は警報・注意報の全件を常時バッジとして並べており、
// 件数によってヘッダーが2行以上に折り返る問題があった）。個々の警報の内訳・補足（title）は
// サマリーボタンを押して開くPopover内でのみ見える。

describe("WarningBadgeList（改善計画T205、UI改善2026-08-24でサマリーボタン化）", () => {
  it("itemsが空の場合は何も描画しない", () => {
    const { container } = render(<WarningBadgeList items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("1件のときはそのレベルの名称だけをボタンに表示する", () => {
    const items: WarningBadgeItem[] = [{ id: "14", label: "雷注意報", level: "advisory", source: "jma" }];
    render(<WarningBadgeList items={items} />);

    const button = screen.getByRole("button", { name: /気象警報・注意報あり: 注意報/ });
    expect(button).toHaveTextContent("注意報");
    expect(button.className).toMatch(/advisory/);
    // 個々のitemのlabelは開く前は見えない。
    expect(screen.queryByText("雷注意報")).not.toBeInTheDocument();
  });

  it("複数件のときは最も警戒度が高いレベル+件数をボタンに表示する（advisoryとwarningが混在→warning側）", () => {
    const items: WarningBadgeItem[] = [
      { id: "14", label: "雷注意報", level: "advisory", source: "jma" },
      { id: "43", label: "大雨危険警報", level: "warning", source: "jma" },
    ];
    render(<WarningBadgeList items={items} />);

    const button = screen.getByRole("button", { name: /気象警報・注意報あり: 警報2件/ });
    expect(button).toHaveTextContent("警報2件");
    expect(button.className).toMatch(/warning/);
  });

  it("severe_warning（厳重警戒）が混在すると厳重警戒側が選ばれる", () => {
    const items: WarningBadgeItem[] = [
      { id: "10", label: "大雨注意報", level: "advisory", source: "jma" },
      { id: "wbgt", label: "厳重警戒", level: "severe_warning", source: "wbgt" },
    ];
    render(<WarningBadgeList items={items} />);
    expect(screen.getByRole("button", { name: /厳重警戒2件/ })).toBeInTheDocument();
  });

  it("emergency_warning（特別警報）が混在すると特別警報側が選ばれる", () => {
    const items: WarningBadgeItem[] = [
      { id: "10", label: "大雨注意報", level: "advisory", source: "jma" },
      { id: "33", label: "大雨特別警報", level: "emergency_warning", source: "jma" },
    ];
    render(<WarningBadgeList items={items} />);
    expect(screen.getByRole("button", { name: /特別警報2件/ })).toBeInTheDocument();
  });

  // 2026-08-24回帰テスト: 実機で「WBGT暑さ指数25（warningレベル）がサマリーボタンで
  // “警報”と表示される」という指摘を受けて修正。WBGTのwarningは正しくは「警戒」
  // （JMAの「警報」とは別の語彙、domain/wbgt.py参照）であるべき。
  it("WBGT単独（warningレベル）はJMAの「警報」ではなく「警戒」と表示する", () => {
    const items: WarningBadgeItem[] = [{ id: "wbgt", label: "暑さ指数警戒", level: "warning", source: "wbgt" }];
    render(<WarningBadgeList items={items} />);

    const button = screen.getByRole("button", { name: /気象警報・注意報あり: 警戒/ });
    expect(button).toHaveTextContent("警戒");
    expect(button).not.toHaveTextContent("警報");
  });

  // 2026-08-24回帰テスト: 実機フィードバック「WBGTの“警戒”がJMAの“警報”と同じ赤色なのが
  // 気になる」を受けて色もsource別に分離。同じwarningレベルでもWBGTはJMAと異なる
  // クラス（wbgt_warning）を持つことを確認する（JMAの.warningクラスと誤って重複しない）。
  it("WBGT単独（warningレベル）はJMAの.warningクラスではなくwbgt_warningクラスを持つ", () => {
    const items: WarningBadgeItem[] = [{ id: "wbgt", label: "暑さ指数警戒", level: "warning", source: "wbgt" }];
    render(<WarningBadgeList items={items} />);

    const button = screen.getByRole("button", { name: /警戒/ });
    expect(hasColorClass(button.className, "wbgt_warning")).toBe(true);
    expect(hasColorClass(button.className, "warning")).toBe(false);
  });

  it("JMA（warningレベル）は従来どおり.warningクラスを持つ（wbgt_接頭辞は付かない）", () => {
    const items: WarningBadgeItem[] = [{ id: "43", label: "大雨警報", level: "warning", source: "jma" }];
    render(<WarningBadgeList items={items} />);

    const button = screen.getByRole("button", { name: /警報/ });
    expect(hasColorClass(button.className, "warning")).toBe(true);
    expect(hasColorClass(button.className, "wbgt_warning")).toBe(false);
  });

  it("詳細パネル内でもWBGT項目とJMA項目で異なる色クラスが付く", async () => {
    const user = userEvent.setup();
    const items: WarningBadgeItem[] = [
      { id: "43", label: "大雨警報", level: "warning", source: "jma" },
      { id: "wbgt", label: "暑さ指数警戒", level: "warning", source: "wbgt" },
    ];
    render(<WarningBadgeList items={items} />);

    await user.click(screen.getByRole("button", { name: /警報2件/ }));

    expect(hasColorClass(screen.getByText("大雨警報").className, "warning")).toBe(true);
    expect(hasColorClass(screen.getByText("大雨警報").className, "wbgt_warning")).toBe(false);
    expect(hasColorClass(screen.getByText("暑さ指数警戒").className, "wbgt_warning")).toBe(true);
  });

  it("JMAとWBGTが同じwarningレベルで混在すると、最初に見つかった方（JMA）の語彙が使われる", () => {
    const items: WarningBadgeItem[] = [
      { id: "43", label: "大雨危険警報", level: "warning", source: "jma" },
      { id: "wbgt", label: "暑さ指数警戒", level: "warning", source: "wbgt" },
    ];
    render(<WarningBadgeList items={items} />);
    expect(screen.getByRole("button", { name: /警報2件/ })).toBeInTheDocument();
  });

  it("ボタンを押すと全件の詳細（label・補足）がPopoverで見える", async () => {
    const user = userEvent.setup();
    const items: WarningBadgeItem[] = [
      { id: "14", label: "雷注意報", level: "advisory", source: "jma", title: "付随事項: 竜巻" },
      { id: "43", label: "大雨危険警報", level: "warning", source: "jma" },
    ];
    render(<WarningBadgeList items={items} />);

    await user.click(screen.getByRole("button", { name: /気象警報・注意報あり/ }));

    expect(screen.getByRole("list", { name: "気象警報・注意報の詳細" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("雷注意報")).toBeInTheDocument();
    expect(screen.getByText("雷注意報").className).toMatch(/advisory/);
    expect(screen.getByText("付随事項: 竜巻")).toBeInTheDocument();
    expect(screen.getByText("大雨危険警報")).toBeInTheDocument();
    expect(screen.getByText("大雨危険警報").className).toMatch(/warning/);
  });
});
