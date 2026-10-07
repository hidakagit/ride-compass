import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CLIENT_TUNING_IDS } from "@/lib/axisCatalog";
import { getQueryClient } from "@/lib/queryClient";
import { serveAxisCatalog } from "@/testing/backendServer";
import { catalogResponse, dedicatedEntry } from "@/testing/catalogAxes";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";

import RideConditionBar from "./RideConditionBar";

// 時刻のルーラーのドラッグはEmbla（ライブラリ）の持ち物。ここでは位置合わせを受けるだけの代役にする。
vi.mock("embla-carousel-react", () => ({
  default: () => [() => {}, { scrollTo: vi.fn(), on: vi.fn(), off: vi.fn(), selectedScrollSnap: () => 0 }],
}));
vi.mock("embla-carousel-wheel-gestures", () => ({ WheelGesturesPlugin: () => ({}) }));
// 速度を変える条件の並びはbackendの走行モデルの宣言。架空の並びへ差し替え、説明がそれを書くことを見る。
vi.mock("@/types/generated/route-generate-config.json", async (importOriginal) => {
  const original = await importOriginal<{ default: typeof routeGenerateConfig }>();
  return { default: { ...original.default, segment_speed_conditions: ["条件ア", "条件イ"] } };
});

const jst = (text: string) => new Date(`${text}+09:00`);
const NOW = jst("2026-09-24T09:07");
const { max_assumed_speed_kmh: MAX } = routeGenerateConfig;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  serveAxisCatalog(catalogResponse([]));
});

afterEach(() => {
  vi.useRealTimers();
});

type Props = React.ComponentProps<typeof RideConditionBar>;

function renderBar(overrides: Partial<Props> = {}) {
  const props: Props = {
    departureTime: jst("2026-09-24T09:05"),
    onDepartureTimeChange: vi.fn(),
    onDepartureNow: vi.fn(),
    speedKmh: 20,
    onSpeedKmhChange: vi.fn(),
    ...overrides,
  };
  render(<RideConditionBar {...props} />);
  return props;
}

describe("RideConditionBar 出発時刻", () => {
  it.each([
    ["今日は時刻だけを1行", "2026-09-24T09:05", "9:05", ["9:05"]],
    ["別の日は日付と時刻を2行に分けて（列の幅に収める）", "2026-09-25T13:00", "9/25 13:00", ["9/25", "13:00"]],
  ])("出発時刻を、%s出す", (_case, departure, label, lines) => {
    renderBar({ departureTime: jst(departure) });
    const button = screen.getByRole("button", { name: `出発時刻: ${label}（タップで変更）` });
    expect([...button.lastElementChild!.children].map((line) => line.textContent)).toEqual(lines);
  });

  it("開くと、日時の入力欄に日本時間で今の出発時刻を入れて出し、直接指定した日時を日本時間として渡す", async () => {
    const props = renderBar();
    await userEvent.click(screen.getByRole("button", { name: /^出発時刻:/ }));
    const input = await screen.findByLabelText("出発日時を直接指定");
    expect(input).toHaveValue("2026-09-24T09:05");
    fireEvent.change(input, { target: { value: "2026-09-26T07:30" } });
    expect(props.onDepartureTimeChange).toHaveBeenCalledWith(jst("2026-09-26T07:30"));
  });

  it.each([
    [
      "出発時刻で値の変わる評価があれば、その名前で",
      ["at", "bearing_deg"],
      "ルートの「評価A」の評価・到達予想の時刻に使います。",
    ],
    ["無ければ評価に触れずに", ["bearing_deg"], "ルートの到達予想の時刻に使います。"],
  ] as const)("出発時刻の説明は、%s何に使うかを書く", async (_case, conditions, tail) => {
    serveAxisCatalog(
      catalogResponse([dedicatedEntry("a", [1], { label: "評価A", dynamic_way_value_conditions: [...conditions] })]),
    );
    renderBar();
    await waitFor(() => expect(getQueryClient().isFetching()).toBe(0));
    expect(screen.getByRole("button", { name: /^出発時刻:/ })).toHaveAttribute(
      "data-usage",
      `出発する日時を決めます。地図の気象の表示の時刻と、${tail}`,
    );
  });

  it("入力欄を空にしても、出発時刻は変えない", async () => {
    const props = renderBar();
    await userEvent.click(screen.getByRole("button", { name: /^出発時刻:/ }));
    fireEvent.change(await screen.findByLabelText("出発日時を直接指定"), { target: { value: "" } });
    expect(props.onDepartureTimeChange).not.toHaveBeenCalled();
  });

  it("開いた時刻から作った目盛りで、今の出発時刻に最も近いコマを選んだ状態にする", async () => {
    renderBar({ departureTime: jst("2026-09-24T09:17") });
    await userEvent.click(screen.getByRole("button", { name: /^出発時刻:/ }));
    // 目盛りは開いた時刻（9:07）を5分刻みへ切り下げた9:05から始まる。9:17に最も近いのは9:15。
    expect(await screen.findByRole("slider", { name: "出発時刻" })).toHaveAttribute("aria-valuetext", "9/24 09:15");
  });

  it("閉じて開き直すと、開き直した時刻から目盛りを作り直す", async () => {
    renderBar({ departureTime: jst("2026-09-24T09:05") });
    const trigger = screen.getByRole("button", { name: /^出発時刻:/ });
    await userEvent.click(trigger);
    await userEvent.click(trigger);
    vi.setSystemTime(jst("2026-09-24T10:02"));
    await userEvent.click(trigger);
    // 目盛りは開き直した10:00から始まり、9:05に最も近いのは先頭の10:00。
    expect(await screen.findByRole("slider", { name: "出発時刻" })).toHaveAttribute("aria-valuetext", "9/24 10:00");
  });

  it("「今」の目盛りを選び直したら、その時刻に固定せず「今」への追従へ戻す（放置して過去になり、予報から外れないように）", async () => {
    const props = renderBar({ departureTime: jst("2026-09-24T09:10") });
    await userEvent.click(screen.getByRole("button", { name: /^出発時刻:/ }));
    // 開いた9:07の「今」の目盛りは9:05。9:10から1つ前へ戻すとそこに当たる。
    await userEvent.click(await screen.findByRole("button", { name: "出発時刻を1つ前へ" }));
    expect(props.onDepartureNow).toHaveBeenCalled();
    expect(props.onDepartureTimeChange).not.toHaveBeenCalled();
  });

  it("目盛りで選んだコマの時刻を出発時刻にする", async () => {
    const props = renderBar({ departureTime: jst("2026-09-24T09:15") });
    await userEvent.click(screen.getByRole("button", { name: /^出発時刻:/ }));
    await userEvent.click(await screen.findByRole("button", { name: "出発時刻を1つ次へ" }));
    expect(props.onDepartureTimeChange).toHaveBeenCalledWith(jst("2026-09-24T09:20"));
  });
});

describe("RideConditionBar 想定速度", () => {
  it("スライダーで動かした値を渡す", async () => {
    const props = renderBar();
    await userEvent.click(screen.getByRole("button", { name: /^想定速度:/ }));
    fireEvent.change(await screen.findByRole("slider", { name: "想定速度スライダー" }), { target: { value: "24" } });
    expect(props.onSpeedKmhChange).toHaveBeenCalledWith(24);
  });

  it("数値欄の範囲の外の値は、範囲へ収めて渡す", async () => {
    const props = renderBar();
    await userEvent.click(screen.getByRole("button", { name: /^想定速度:/ }));
    const input = await screen.findByLabelText("想定速度（km/h）");
    await userEvent.clear(input);
    await userEvent.type(input, `${MAX + 10}{Enter}`);
    expect(props.onSpeedKmhChange).toHaveBeenCalledWith(MAX);
  });

  it("(i)の奥に、走行モデルが速度を変える条件として宣言する並びを書く", async () => {
    renderBar();
    await userEvent.click(screen.getByRole("button", { name: /^想定速度:/ }));
    await userEvent.click(await screen.findByRole("button", { name: "想定速度の説明を表示" }));
    expect(await screen.findByText(/区間ごとの条件ア・条件イで速度を変えて計算します/)).toBeInTheDocument();
  });

  it("(i)の奥に、軸カタログが配る体格・機材の標準値を書く", async () => {
    serveAxisCatalog(
      catalogResponse([], {
        client_tuning: {
          [CLIENT_TUNING_IDS.massKg]: 72,
          [CLIENT_TUNING_IDS.cdaM2]: 0.4,
          [CLIENT_TUNING_IDS.maxDescentKmh]: 50,
          [CLIENT_TUNING_IDS.walkingKmh]: 5,
        },
      }),
    );
    renderBar();
    await userEvent.click(screen.getByRole("button", { name: /^想定速度:/ }));
    await userEvent.click(await screen.findByRole("button", { name: "想定速度の説明を表示" }));
    expect(await screen.findByText(/総質量72kg.*CdA 0.4m².*下りは50km\/hまで.*5km\/h以下/)).toBeInTheDocument();
  });

  it("体格・機材の標準値を軸カタログから1つでも引けなければ、標準値の文を出さない", async () => {
    serveAxisCatalog(
      catalogResponse([], {
        client_tuning: {
          [CLIENT_TUNING_IDS.massKg]: 72,
          [CLIENT_TUNING_IDS.cdaM2]: 0.4,
          [CLIENT_TUNING_IDS.maxDescentKmh]: 50,
        },
      }),
    );
    renderBar();
    await userEvent.click(screen.getByRole("button", { name: /^想定速度:/ }));
    await userEvent.click(await screen.findByRole("button", { name: "想定速度の説明を表示" }));
    expect(await screen.findByText(/平らな道を風の無いときに巡航する速度です/)).toBeInTheDocument();
    // 軸カタログが届いてから確かめる（届く前も文を出さないので、届く前に見ると引けたかを見分けない）。
    await waitFor(() => expect(getQueryClient().isFetching()).toBe(0));
    expect(screen.queryByText(/標準値で計算します/)).not.toBeInTheDocument();
  });
});
