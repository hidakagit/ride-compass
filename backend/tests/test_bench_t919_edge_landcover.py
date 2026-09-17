"""T919の計測（benchmarks/bench_t919_edge_landcover.py）のうち、DB・ラスタを要さない部分。

**計測が実装の判断根拠になる**ため、ここが間違っていると「ばらつきが小さいので不要」と
いう誤った結論を出しうる。way内レンジの定義そのものを固定する。
"""

from dataclasses import dataclass

from benchmarks.bench_t919_edge_landcover import way_class_ranges
from app.domain.attributes import WIRED_LANDCOVER_KEYS


@dataclass
class _Percentages:
    """`LandcoverPercentages`のうち、配線済みクラスの割合だけを持つ差し替え。"""

    values: dict

    def __getattr__(self, name):
        return self.values[name]


def _percentages(**overrides):
    values = dict.fromkeys(WIRED_LANDCOVER_KEYS, 0.0)
    values.update(overrides)
    return _Percentages(values)


def test_way内レンジは区間の最大と最小の差になる():
    segments = [
        _percentages(trees_percent=10.0, built_percent=80.0),
        _percentages(trees_percent=70.0, built_percent=20.0),
        _percentages(trees_percent=40.0, built_percent=50.0),
    ]

    ranges = way_class_ranges(segments)

    assert ranges["trees_percent"] == 60.0
    assert ranges["built_percent"] == 60.0


def test_全区間が同じ値ならレンジは0():
    """way平均で塗っても失われるものが無い場合。この形が多数なら T919 は不要になる。"""
    segments = [_percentages(trees_percent=33.0)] * 3

    assert way_class_ranges(segments)["trees_percent"] == 0.0


def test_配線済みクラスが増えてもレンジを出す対象に入る():
    """クラスを1つ配線したときに、計測だけがそのクラスを見落とさないようにする
    （WIRED_LANDCOVER_KEYSから組み立てており、クラス名を並べていない）。"""
    segments = [_percentages(), _percentages()]

    assert set(way_class_ranges(segments)) == set(WIRED_LANDCOVER_KEYS)
