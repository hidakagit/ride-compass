"""派生データの系譜版数（`domain/derived_data_versions.py`）の契約。"""

from app.domain.derived_data_versions import (
    EDGE_ATTRIBUTE_COUNTS_ALGORITHM_VERSION,
    WAY_ATTRIBUTE_COUNTS_ALGORITHM_VERSION,
)


def test_edge_and_way_attribute_counts_share_one_algorithm_version():
    """Edge単位とWay単位の集計は同じロジックのため、版数も揃っていなければならない。

    定数は「それぞれ単独で読める」ことを優先して別々に持つ。揃っているかを目視で確かめる
    運用にすると、片方だけ上げたときに鮮度台帳が「片方は最新・片方は古い」と出し、どちらが
    正しいのか読み手に判断できなくなる。
    """
    assert EDGE_ATTRIBUTE_COUNTS_ALGORITHM_VERSION == WAY_ATTRIBUTE_COUNTS_ALGORITHM_VERSION
