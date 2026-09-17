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
    description: "右折1回の損失。",
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

  it("打っただけでは送らず、保存を押したときに送る", async () => {
    const user = userEvent.setup();
    vi.mocked(listTuningParameters).mockResolvedValue([parameter()]);
    vi.mocked(updateTuningParameter).mockResolvedValue(parameter({ value: 30, overridden: true }));

    render(<TuningPanel />);
    const input = await screen.findByLabelText("右折");
    await user.clear(input);
    await user.type(input, "30");
    await user.tab();

    expect(updateTuningParameter).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    await waitFor(() => expect(updateTuningParameter).toHaveBeenCalledWith("turn.right_seconds", 30));
  });

  it("保存できるのは値を変えた行があるときだけで、送るのもその行だけ", async () => {
    const user = userEvent.setup();
    vi.mocked(listTuningParameters).mockResolvedValue([
      parameter(),
      parameter({ id: "stop.signal_seconds", label: "信号の待ち", effect: "immediate", default: 21, value: 21 }),
    ]);
    vi.mocked(updateTuningParameter).mockResolvedValue(parameter({ value: 30, overridden: true }));

    render(<TuningPanel />);
    await screen.findByLabelText("右折");

    const save = screen.getByRole("button", { name: "DBへ保存" });
    expect(save).toBeDisabled();

    const input = screen.getByLabelText("右折");
    await user.clear(input);
    await user.type(input, "30");

    expect(screen.getByText("1件が未保存")).toBeInTheDocument();
    await user.click(save);

    await waitFor(() => expect(updateTuningParameter).toHaveBeenCalledTimes(1));
    expect(updateTuningParameter).toHaveBeenCalledWith("turn.right_seconds", 30);
  });

  it("既定と同じ値にして保存すると、上書きを消す（nullを送る）", async () => {
    // DBへ残すのは既定から動かしたぶんだけにする。
    const user = userEvent.setup();
    vi.mocked(listTuningParameters).mockResolvedValue([parameter({ value: 30, overridden: true })]);
    vi.mocked(updateTuningParameter).mockResolvedValue(parameter());

    render(<TuningPanel />);
    const input = await screen.findByLabelText("右折");
    await user.clear(input);
    await user.type(input, "12");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    await waitFor(() => expect(updateTuningParameter).toHaveBeenCalledWith("turn.right_seconds", null));
  });

  it("保存に失敗したら理由を出し、打った値は消さない", async () => {
    const user = userEvent.setup();
    vi.mocked(listTuningParameters).mockResolvedValue([parameter()]);
    vi.mocked(updateTuningParameter).mockRejectedValue(new Error("較正値が宣言の範囲の外"));

    render(<TuningPanel />);
    const input = await screen.findByLabelText("右折");
    await user.clear(input);
    await user.type(input, "999");
    await user.click(screen.getByRole("button", { name: "DBへ保存" }));

    expect(await screen.findByText("較正値が宣言の範囲の外")).toBeInTheDocument();
    expect(input).toHaveValue(999);
  });

  it("取得に失敗したときだけ読み込み直すボタンを出す", async () => {
    const user = userEvent.setup();
    vi.mocked(listTuningParameters).mockRejectedValueOnce(new Error("較正値の取得に失敗しました"));
    vi.mocked(listTuningParameters).mockResolvedValueOnce([parameter()]);

    render(<TuningPanel />);

    expect(await screen.findByText("較正値の取得に失敗しました")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "読み込み直す" }));

    expect(await screen.findByLabelText("右折")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "読み込み直す" })).not.toBeInTheDocument();
  });

  it("説明と既定値・範囲は(i)の奥へ置く（縦に長い一覧の行に敷かない）", async () => {
    const user = userEvent.setup();
    vi.mocked(listTuningParameters).mockResolvedValue([parameter({ value: 30, overridden: true })]);

    render(<TuningPanel />);
    await screen.findByLabelText("右折");

    // 開く前は行に出ていない。
    expect(screen.queryByText("右折1回の損失。")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "右折の説明を表示" }));

    expect(await screen.findByText("右折1回の損失。")).toBeInTheDocument();
    expect(screen.getByText("既定 12秒（0〜120）")).toBeInTheDocument();
  });
});
