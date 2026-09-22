"""`domain/traffic.py`——OSMタグから派生する分類と、所要時間モデルのパラメータ。

引き当てそのものはDB側で行うため、**表が実際にどう当たるか**は
`test_tag_classification.py`（種別）と`test_resolve_direction.py`（通行方向）が
DBへ通して確かめる。ここで見るのは、交差点の優先関係に使う階級順だけ。
"""


from app.domain.traffic import (
    MAJOR_CROSSING_MIN_RANK,
    highway_rank,
)


class TestHighwayRank:
    def test_a_bigger_road_ranks_above_a_smaller_one(self):
        assert highway_rank("trunk") > highway_rank("primary") > highway_rank("residential")

    def test_a_link_shares_the_rank_of_the_road_it_joins(self):
        """ランプは本線と同じ扱い。分けると合流待ちの判定が本線とずれる。"""
        assert highway_rank("primary_link") == highway_rank("primary")

    def test_a_missing_or_unknown_tag_ranks_lowest(self):
        assert highway_rank(None) == 0
        assert highway_rank("") == 0
        assert highway_rank("no_such_highway") == 0

    def test_waiting_is_required_only_above_the_quiet_streets(self):
        assert highway_rank("residential") < MAJOR_CROSSING_MIN_RANK
        assert highway_rank("service") < MAJOR_CROSSING_MIN_RANK
        assert highway_rank("tertiary") >= MAJOR_CROSSING_MIN_RANK


