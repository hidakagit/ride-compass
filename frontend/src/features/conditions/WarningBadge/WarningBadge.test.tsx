import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import WarningBadgeList, { type WarningBadgeItem } from "./WarningBadge";

// UI改善（2026-08-24）: 天候ヘッダーが常に1行に収まるよう、常時表示は「最高警戒度+件数の
// サマリーボタン1個」のみへ変更した（以前は警報・注意報の全件を常時バッジとして並べており、
// 件数によってヘッダーが2行以上に折り返る問題があった）。個々の警報の内訳・補足（title）は
// サマリーボタンを押して開くPopover内でのみ見える。

describe("WarningBadgeList（改善計画T205、UI改善2026-08-24でサマリーボタン化）", () => {
  it("itemsが空の場合は何も描画しない", () => {
    const { container } = render(<WarningBadgeList items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("取得に失敗した出所があれば、バッジが0件でも印を出し、開くと何が取れていないかを読める", async () => {
    const user = userEvent.setup();
    render(
      <WarningBadgeList
        items={[]}
        failures={[{ id: "jma", label: "警報・注意報", detail: "警報・注意報の取得に失敗しました[通信エラー]" }]}
      />,
    );

    await user.click(screen.getByRole("button", { name: /警報・注意報を取得できていません/ }));
    expect(screen.getByText("警報・注意報を取得できていません")).toBeInTheDocument();
    expect(screen.getByText(/警報・注意報の取得に失敗しました\[通信エラー\]/)).toBeInTheDocument();
  });

  it("取得に失敗した出所が無ければ、失敗の印は出さない", () => {
    const items: WarningBadgeItem[] = [{ id: "14", label: "雷注意報", level: "advisory", source: "jma" }];
    render(<WarningBadgeList items={items} failures={[]} />);

    expect(screen.queryByRole("button", { name: /取得できていません/ })).not.toBeInTheDocument();
  });

  it("1件のときはそのレベルの名称だけをボタンに表示する", () => {
    const items: WarningBadgeItem[] = [{ id: "14", label: "雷注意報", level: "advisory", source: "jma" }];
    render(<WarningBadgeList items={items} />);

    const button = screen.getByRole("button", { name: /気象警報・注意報あり: 注意報/ });
    expect(button).toHaveTextContent("注意報");
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

  // 暑さ指数の「警戒」は気象庁の「警報」と別の基準のため、同じ段階でも色を分ける（色の値はbackendの宣言が持つ）。
  it("詳細パネル内で、同じwarningレベルでもWBGT項目とJMA項目の背景色は違う", async () => {
    const user = userEvent.setup();
    const items: WarningBadgeItem[] = [
      { id: "43", label: "大雨警報", level: "warning", source: "jma" },
      { id: "wbgt", label: "暑さ指数警戒", level: "warning", source: "wbgt" },
    ];
    render(<WarningBadgeList items={items} />);

    await user.click(screen.getByRole("button", { name: /警報2件/ }));

    const jma = screen.getByText("大雨警報").style.backgroundColor;
    const wbgt = screen.getByText("暑さ指数警戒").style.backgroundColor;
    expect(jma).not.toBe("");
    expect(wbgt).not.toBe("");
    expect(wbgt).not.toBe(jma);
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
    expect(screen.getByText("付随事項: 竜巻")).toBeInTheDocument();
    expect(screen.getByText("大雨危険警報")).toBeInTheDocument();
  });
});
