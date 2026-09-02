def normalize_min_max(
    values: list[float | None], higher_is_better: bool, min_meaningful_range: float = 0.0
) -> list[float | None]:
    """候補集合内でmin-max正規化し0-100点に変換する。

    絶対的なしきい値を決め打ちできる実データが無いため、同じ`generate_loops`呼び出し内の
    候補同士を相対比較するためのスコアとして設計している（異なるリクエスト間では比較不可）。
    `None`はそのまま`None`を返す（そのメトリクスが取得できなかった候補は合成時に除外するため）。
    全候補が同値の場合は差をつけられないため中立の50点を返す（改善計画T463で100点から
    訂正——候補間の相対順位には影響しない[全員へ同じ定数が加わるだけ]が、「全候補とも
    劣悪な値で差が無い」場合まで一律100点になると、ユーザー向けスコア内訳がその指標を
    「完璧だった」と見せてしまっていた）。

    `min_meaningful_range`: ユーザー指摘（2026-09-03、「おすすめ度の数字が極端。ルート生成
    ロジックの距離誤差でほぼ決まっていて参考にならない」）: min-max正規化は候補集合内の
    実際の値幅（hi-lo）がどれだけ小さくても強制的に0/100へ引き伸ばすため、実差が測定誤差・
    ノイズ相当の指標（例: 風が弱い日のoverall_difficulty差）でも、あたかも意味のある大差が
    あるかのように誇張されてしまう。この引数を渡すと、値幅がmin_meaningful_range未満の場合に
    限り、実際の値幅の代わりにmin_meaningful_range幅（(lo+hi)/2を中心に据える）で正規化する
    ——候補間の相対順序（誰が良い/悪いか）は変えず、0/100への誇張だけを弱める。値幅が
    min_meaningful_range以上のときは従来と完全に同じ結果になる（effective_range=hi-lo）。
    既定0.0は従来どおり常にhi-loそのものを使う（無効化）。
    """
    present = [v for v in values if v is not None]
    if not present:
        return [None] * len(values)

    lo, hi = min(present), max(present)

    def scale(value: float | None) -> float | None:
        if value is None:
            return None
        if lo == hi:
            return 50.0
        span = hi - lo
        effective_span = max(span, min_meaningful_range)
        mid = (lo + hi) / 2
        ratio = (value - (mid - effective_span / 2)) / effective_span
        ratio = min(1.0, max(0.0, ratio))
        if not higher_is_better:
            ratio = 1 - ratio
        return round(ratio * 100, 1)

    return [scale(v) for v in values]
