from app.domain.scoring import normalize_min_max


def test_higher_is_better_maps_max_to_100_and_min_to_0():
    scores = normalize_min_max([10.0, 20.0, 30.0], higher_is_better=True)

    assert scores == [0.0, 50.0, 100.0]


def test_lower_is_better_inverts_the_mapping():
    scores = normalize_min_max([10.0, 20.0, 30.0], higher_is_better=False)

    assert scores == [100.0, 50.0, 0.0]


# 改善計画T463: テスト名どおり「中立」の値(50.0)を期待するよう訂正。以前は100.0
# （最良点）を期待しており、テスト名の主張と実装の挙動が矛盾していた。
def test_all_equal_values_get_neutral_score():
    scores = normalize_min_max([5.0, 5.0, 5.0], higher_is_better=True)

    assert scores == [50.0, 50.0, 50.0]


def test_none_values_pass_through_unchanged():
    scores = normalize_min_max([10.0, None, 30.0], higher_is_better=True)

    assert scores == [0.0, None, 100.0]


def test_all_none_returns_all_none():
    scores = normalize_min_max([None, None], higher_is_better=True)

    assert scores == [None, None]


# ユーザー指摘（2026-09-03、「おすすめ度の数字が極端。ルート生成ロジックの距離誤差で
# ほぼ決まっていて参考にならない」）: min_meaningful_range未満の実差は0/100へ誇張しない。
def test_min_meaningful_range_compresses_small_real_differences():
    # 実差は1.0（20.0〜21.0）しか無いが、min_meaningful_rangeが無いと従来どおり0/100へ
    # 引き伸ばされる。
    without_compression = normalize_min_max([20.0, 20.5, 21.0], higher_is_better=False)
    assert without_compression == [100.0, 50.0, 0.0]

    # min_meaningful_range=10.0を渡すと、同じ実差1.0は10.0幅の一部としてのみ評価され、
    # 0/100への誇張が弱まる（順序自体は変わらない: 最小値が最高得点のまま）。
    compressed = normalize_min_max([20.0, 20.5, 21.0], higher_is_better=False, min_meaningful_range=10.0)
    assert compressed[0] is not None and compressed[2] is not None
    assert compressed[0] > compressed[1] > compressed[2]
    assert 50.0 < compressed[0] < 100.0
    assert 0.0 < compressed[2] < 50.0
    assert compressed[1] == 50.0  # 中央値はmid=(lo+hi)/2と一致するため中立のまま


def test_min_meaningful_range_no_effect_when_actual_range_is_already_larger():
    # 実差（80.0）がmin_meaningful_range（10.0）を上回るときは、従来どおりhi-loそのもので
    # 正規化する（min_meaningful_rangeを渡さない場合と完全に同じ結果になる）。
    with_range = normalize_min_max([10.0, 90.0], higher_is_better=False, min_meaningful_range=10.0)
    without_range = normalize_min_max([10.0, 90.0], higher_is_better=False)
    assert with_range == without_range == [100.0, 0.0]


def test_min_meaningful_range_does_not_affect_tied_values():
    # lo==hiの中立50点フォールバックは、min_meaningful_rangeの有無に関わらず変わらない。
    scores = normalize_min_max([5.0, 5.0], higher_is_better=True, min_meaningful_range=10.0)
    assert scores == [50.0, 50.0]
