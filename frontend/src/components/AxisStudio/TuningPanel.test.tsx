import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TuningPanel from "./TuningPanel";
import { listTuningParameters, updateTuningParameter, type TuningParameter } from "@/services/tuningApi";

vi.mock("@/services/tuningApi", () => ({
  listTuningParameters: vi.fn(),
  updateTuningParameter: vi.fn(),
}));

function parameter(overrides: Partial<TuningParameter> = {}): TuningParameter {
  return {
    id: "turn.right_seconds",
    label: "右折",
    unit: "秒",
    description: "右折1回の時間損失。",
    default: 12,
    minimum: 0,
    maximum: 120,
    effect: "turn_structure",
    value: 12,
    overridden: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(listTuningParameters).mockReset();
  vi.mocked(updateTuningParameter).mockReset();
});

describe("TuningPanel", () => {
  it("backendが返した項目をそのまま並べる（画面側に一覧を持たない）", async () => {
    // 較正値を1つ足しても画面を変えなくてよいことを、返り値だけで確かめる。
    vi.mocked(listTuningParameters).mockResolvedValue([
      parameter(),
      parameter({ id: "stop.signal_seconds", label: "信号の待ち", effect: "immediate", default: 21, value: 21 }),
      parameter({ id: "zzz.brand_new", label: "まだ知らない値", effect: "immediate", default: 1, value: 1 }),
    ]);

    render(<TuningPanel />);

    expect(await screen.findByLabelText("右折")).toBeInTheDocument();
    expect(screen.getByLabelText("信号の待ち")).toBeInTheDocument();
    expect(screen.getByLabelText("まだ知らない値")).toBeInTheDocument();
  });

  it("効き方ごとに見出しを分ける（別の操作が要る群がそれと分かる）", async () => {
    // 同じ見た目で並べると「変えたのに効かない」に気づけない。
    vi.mocked(listTuningParameters).mockResolvedValue([
      parameter({ id: "signal.match_radius_m", label: "信号とみなす半径", effect: "node_attribute_batch" }),
      parameter({ id: "stop.signal_seconds", label: "信号の待ち", effect: "immediate" }),
    ]);

    render(<TuningPanel />);

    expect(await screen.findByText("交差点の事前計算をやり直すまで効かない")).toBeInTheDocument();
    expect(screen.getByText("次のルート生成から効く")).toBeInTheDocument();
  });

  it("知らない効き方が来ても落とさず「その他」へ出す", async () => {
    // backendが先に増えてもこの画面は動き続ける。
    vi.mocked(listTuningParameters).mockResolvedValue([
      parameter({ id: "zzz.unknown_effect", label: "未知の効き方", effect: "zzz_future" }),
    ]);

    render(<TuningPanel />);

    expect(await screen.findByText("その他")).toBeInTheDocument();
    expect(screen.getByLabelText("未知の効き方")).toBeInTheDocument();
  });

  it("確定したときだけ送る（1文字ごとには送らない）", async () => {
    const user = userEvent.setup();
    vi.mocked(listTuningParameters).mockResolvedValue([parameter()]);
    vi.mocked(updateTuningParameter).mockResolvedValue(parameter({ value: 30, overridden: true }));

    render(<TuningPanel />);
    const input = await screen.findByLabelText("右折");
    await user.clear(input);
    await user.type(input, "30");

    expect(updateTuningParameter).not.toHaveBeenCalled();

    await user.tab();

    await waitFor(() => expect(updateTuningParameter).toHaveBeenCalledWith("turn.right_seconds", 30));
  });

  it("既定から動かしてある行だけに「既定へ戻す」を出し、押すとnullを送る", async () => {
    const user = userEvent.setup();
    vi.mocked(listTuningParameters).mockResolvedValue([
      parameter({ value: 30, overridden: true }),
      parameter({ id: "stop.signal_seconds", label: "信号の待ち", effect: "immediate", value: 21 }),
    ]);
    vi.mocked(updateTuningParameter).mockResolvedValue(parameter());

    render(<TuningPanel />);
    await screen.findByLabelText("右折");

    const buttons = screen.getAllByRole("button", { name: /を既定へ戻す$/ });
    expect(buttons).toHaveLength(1);

    await user.click(buttons[0]);

    await waitFor(() => expect(updateTuningParameter).toHaveBeenCalledWith("turn.right_seconds", null));
  });

  it("更新に失敗したら理由を出し、入力を元の値へ戻す", async () => {
    const user = userEvent.setup();
    vi.mocked(listTuningParameters).mockResolvedValue([parameter()]);
    vi.mocked(updateTuningParameter).mockRejectedValue(new Error("較正値が宣言の範囲の外"));

    render(<TuningPanel />);
    const input = await screen.findByLabelText("右折");
    await user.clear(input);
    await user.type(input, "999");
    await user.tab();

    expect(await screen.findByText("較正値が宣言の範囲の外")).toBeInTheDocument();
    await waitFor(() => expect(input).toHaveValue(12));
  });

  it("取得に失敗したら理由を出し、読み込み直せる", async () => {
    const user = userEvent.setup();
    vi.mocked(listTuningParameters).mockRejectedValueOnce(new Error("較正値の取得に失敗しました"));
    vi.mocked(listTuningParameters).mockResolvedValueOnce([parameter()]);

    render(<TuningPanel />);

    expect(await screen.findByText("較正値の取得に失敗しました")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "読み込み直す" }));

    expect(await screen.findByLabelText("右折")).toBeInTheDocument();
  });

  it("説明と既定値・範囲は(i)の奥へ置く（21件が縦に並ぶため行に敷かない）", async () => {
    const user = userEvent.setup();
    vi.mocked(listTuningParameters).mockResolvedValue([parameter({ value: 30, overridden: true })]);

    render(<TuningPanel />);
    await screen.findByLabelText("右折");

    // 開く前は行に出ていない。
    expect(screen.queryByText("右折1回の時間損失。")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "右折の説明を表示" }));

    expect(await screen.findByText("右折1回の時間損失。")).toBeInTheDocument();
    expect(screen.getByText("既定 12秒（0〜120）")).toBeInTheDocument();
  });

  it("既定から動かしてある件数を出す", async () => {
    vi.mocked(listTuningParameters).mockResolvedValue([
      parameter({ value: 30, overridden: true }),
      parameter({ id: "stop.signal_seconds", label: "信号の待ち", effect: "immediate" }),
    ]);

    render(<TuningPanel />);

    expect(await screen.findByText("1件が既定から変更")).toBeInTheDocument();
  });
});
