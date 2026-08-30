from app.domain.jma_area import municipality_code_to_class20_code, resolve_area


def _area_data(*, two_level: bool = True) -> dict:
    """area.jsonの最小フィクスチャ。2段（class20→class15→class10）と1段
    （class20の親が直接class10、Ogasawaraのような区域）の両方を模す。"""
    if two_level:
        return {
            "class20s": {"1310100": {"name": "千代田区", "parent": "130011"}},
            "class15s": {"130011": {"name": "２３区西部", "parent": "130010"}},
            "class10s": {"130010": {"name": "東京地方", "parent": "130000"}},
        }
    return {
        "class20s": {"1342100": {"name": "小笠原村", "parent": "130040"}},
        "class15s": {"130040": {"name": "小笠原諸島", "parent": "130040"}},
        "class10s": {"130040": {"name": "小笠原諸島", "parent": "130000"}},
    }


def test_municipality_code_to_class20_code_appends_00():
    assert municipality_code_to_class20_code("13101") == "1310100"


def test_resolve_area_walks_class15_to_class10():
    resolved = resolve_area("13101", _area_data(two_level=True))
    assert resolved is not None
    assert resolved.class20_code == "1310100"
    assert resolved.class10_code == "130010"
    assert resolved.office_code == "130000"
    assert resolved.class10_name == "東京地方"


def test_resolve_area_handles_class20_parent_already_being_class10():
    # 小笠原諸島のようにclass15とclass10が同一コードで自己参照するケース。
    resolved = resolve_area("13421", _area_data(two_level=False))
    assert resolved is not None
    assert resolved.class10_code == "130040"
    assert resolved.class10_name == "小笠原諸島"
    assert resolved.office_code == "130000"


def test_resolve_area_returns_none_for_unknown_municipality_code():
    assert resolve_area("99999", _area_data()) is None


def test_resolve_area_returns_none_on_broken_parent_chain():
    broken = {
        "class20s": {"1310100": {"name": "千代田区", "parent": "999999"}},
        "class15s": {},
        "class10s": {},
    }
    assert resolve_area("13101", broken) is None


# 改善計画T463: 想定外の形式の外部データ（"parent"/"name"キー欠如）に対し、
# KeyErrorを伝播させずNoneへ倒すことの回帰テスト（他の外部データ処理関数と同じ流儀）。
def test_resolve_area_returns_none_when_class20_missing_parent_key():
    malformed = {
        "class20s": {"1310100": {"name": "千代田区"}},  # "parent"キーが無い
        "class15s": {},
        "class10s": {},
    }
    assert resolve_area("13101", malformed) is None


def test_resolve_area_returns_none_when_class15_missing_parent_key():
    malformed = {
        "class20s": {"1310100": {"name": "千代田区", "parent": "130011"}},
        "class15s": {"130011": {"name": "２３区西部"}},  # "parent"キーが無い
        "class10s": {},
    }
    assert resolve_area("13101", malformed) is None


def test_resolve_area_returns_none_when_class10_missing_name_or_parent_key():
    malformed = {
        "class20s": {"1310100": {"name": "千代田区", "parent": "130010"}},
        "class15s": {},
        "class10s": {"130010": {"name": "東京地方"}},  # "parent"キーが無い
    }
    assert resolve_area("13101", malformed) is None
