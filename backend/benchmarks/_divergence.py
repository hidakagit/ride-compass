"""候補ルートのEdge id列から「分岐点」を求める計測用ロジック（DB接続に依存しない）。

分岐点は、表示中の候補を走っている利用者が別の候補へ乗り換えられる地点
（両方の候補が通る同じEdgeを走り終えた直後に、次へ進むEdgeが分かれる地点）。

**これは計測のための実装であり、製品の実装ではない。** 乗り換えUIそのものは
frontendが同じ集合演算をTypeScriptで行う（docs/tasks/T621.md 論点2）。ここは
「実データで分岐点がいくつ出るか」を数えるためだけに存在する。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class DivergencePoint:
    """表示中の候補の1地点と、そこから乗り換えられる候補。

    `after_edge_id`はこのEdgeを走り終えた地点を指す。`None`は起点そのもの
    （最初のEdgeから既に分かれている）。
    """

    index: int
    after_edge_id: str | None
    targets: tuple[str, ...]


def _successors(path: Sequence[str]) -> dict[str, str]:
    """Edge id→そのEdgeの次に進むEdge id。最後のEdgeは終点に着くため含まれない。

    同じEdgeを2回以上通る経路では最初の通過を採る（後の通過へ乗り換えると、
    乗り換え先の経路を余分に走ることになる）。
    """
    successors: dict[str, str] = {}
    for current, following in zip(path, path[1:]):
        successors.setdefault(current, following)
    return successors


def divergence_points(
    displayed: Sequence[str], others: Mapping[str, Sequence[str]]
) -> list[DivergencePoint]:
    """`displayed`を走っているときに他候補へ乗り換えられる地点を、起点に近い順に返す。

    同じ地点で複数の候補へ乗り換えられる場合は1つの`DivergencePoint`へまとめる
    （地図のマーカー1つに対応する）。
    """
    grouped: dict[int, tuple[str | None, list[str]]] = {}

    for label, other in others.items():
        if not other or not displayed:
            continue
        if other[0] != displayed[0]:
            grouped.setdefault(0, (None, []))[1].append(label)
        successors = _successors(other)
        for index, (edge, following) in enumerate(zip(displayed, displayed[1:]), start=1):
            successor = successors.get(edge)
            if successor is not None and successor != following:
                grouped.setdefault(index, (edge, []))[1].append(label)

    return [
        DivergencePoint(index=index, after_edge_id=after_edge_id, targets=tuple(targets))
        for index, (after_edge_id, targets) in sorted(grouped.items())
    ]


def spliced_path(
    displayed: Sequence[str], target: Sequence[str], point: DivergencePoint
) -> list[str]:
    """`point`で`displayed`から`target`へ乗り換えた経路のEdge id列。

    `evaluate_loops`へ渡す`TracedLoop.data`と同じ形で、合成が経路として成立することを
    計測時に確かめるために使う。
    """
    if point.after_edge_id is None:
        return list(target)
    position = list(target).index(point.after_edge_id)
    return list(displayed[: point.index]) + list(target[position + 1 :])
