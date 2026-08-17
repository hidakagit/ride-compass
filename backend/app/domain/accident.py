"""警察庁交通事故統計オープンデータの取込で使う純関数群（外部静的データソース T50）。

`domain/traffic.py`と同じ「純関数・unknown安全」の方針。本票CSVの列定義・コード値は
2026-08-16に実データ（honhyo_2023.csv）とコード表CSV
（https://www.npa.go.jp/publications/statistics/koutsuu/opendata/koudohyou/）を
直接取得して確認したもの（2_koudohyou_todouhukenkoudo.csv・31_koudohyou_toujisyasyuetu.csv）。
"""

# サンプル点/Edgeから事故地点へ空間マッチする際のスナップ半径（外部静的データソース T50残作業）。
# 事故地点の緯度経度は本票の度分秒表記からの変換値で、信号等のOSM node（STOP_POI_MATCH_MAX_
# DISTANCE_M=15m、domain/traffic.py）よりジオコーディング精度が粗い可能性があるため、
# domain/road.py: SURFACE_MATCH_MAX_DISTANCE_M（30m）と同じ側に揃える。
# openrouteservice_engine.py（明示引数）とAttributeRepository各メソッド（デフォルト引数）の
# 両方がこの定数をimportして参照する（改善計画T44と同じ「片側import」原則）。
ACCIDENT_MATCH_MAX_DISTANCE_M = 30.0

# 死亡事故の重み（改善計画: 事故密度の精度改善）。件数を単純にCOUNTすると軽傷の物損に近い
# 事故と死亡事故が同じ1件として扱われ、最も避けたい重大事故のリスクが薄まる。死亡事故は
# `ACCIDENT_FATAL_WEIGHT`件分として積算する（road_graph_repository.py: _ACCIDENT_COUNTS_SQL/
# _NEAREST_ACCIDENT_COUNTS_SQLがSUM(CASE WHEN fatal THEN :fatal_weight ELSE 1 END)で適用）。
# 3.0は「死亡事故は軽傷事故の3件分のリスクとみなす」という暫定値（本格チューニングはP2据え置き、
# 他の閾値・補正値と同じ方針）。
ACCIDENT_FATAL_WEIGHT = 3.0

# 関東7都県の都道府県コード（NPA独自の採番。JIS X 0401とは異なる）。
# import_profile.yamlのPBF取込bboxと同じ関東スコープに揃える。
KANTO_PREFECTURE_CODES: dict[str, str] = {
    "30": "東京",
    "40": "茨城",
    "41": "栃木",
    "42": "群馬",
    "43": "埼玉",
    "44": "千葉",
    "45": "神奈川",
}

# 当事者種別（31_koudohyou_toujisyasyuetu.csv）のうち自転車に該当するコード。
# 51=軽車両－自転車、52=軽車両－駆動補助機付自転車（電動アシスト自転車）。
# 59（軽車両－その他）は自転車ではない軽車両（手押し車等）のため含めない。
BICYCLE_PARTY_TYPE_CODES: frozenset[str] = frozenset({"51", "52"})


def is_kanto_prefecture(prefecture_code: str) -> bool:
    return prefecture_code.strip() in KANTO_PREFECTURE_CODES


def involves_bicycle(party_type_a: str, party_type_b: str) -> bool:
    """当事者種別（当事者A・当事者B）のいずれかが自転車系コードなら自転車関連事故とみなす。"""
    return party_type_a.strip() in BICYCLE_PARTY_TYPE_CODES or party_type_b.strip() in BICYCLE_PARTY_TYPE_CODES


def is_fatal(death_count_raw: str) -> bool:
    """「死者数」列（"000"等のゼロ埋め数値文字列）から死亡事故かどうかを判定する。"""
    try:
        return int(death_count_raw.strip()) > 0
    except ValueError:
        return False


def build_accident_id(prefecture_code: str, police_station_code: str, honhyo_number: str, occurred_year: int) -> str:
    """本票の複合キー（都道府県コード＋警察署等コード＋本票番号は年内でのみ一意）に
    発生年を足して、年次再取込みでも冪等なグローバル一意キーにする。"""
    return f"{occurred_year}-{prefecture_code.strip()}-{police_station_code.strip()}-{honhyo_number.strip()}"


def _dms_to_decimal(raw: str) -> float | None:
    """本票の緯度・経度列（度分秒を1つの数値へ連結した表記。右5桁=秒×1000、
    次の2桁=分、残り=度）を10進の度へ変換する。欠損（空・非数値・全て0）や
    分/秒が60以上になる不正値はNone（根拠のない推測はしない）。"""
    value = raw.strip()
    if not value.isdigit() or len(value) < 8:
        return None
    seconds = int(value[-5:]) / 1000.0
    minutes = int(value[-7:-5])
    degrees = int(value[:-7])
    if minutes >= 60 or seconds >= 60:
        return None
    return degrees + minutes / 60.0 + seconds / 3600.0


# 日本の緯度・経度のおおよその範囲（南鳥島・沖ノ鳥島等の離島を含む広めの値）。
# 変換結果の妥当性チェック用であり、関東7都県への絞り込みはis_kanto_prefectureで別途行う。
_JAPAN_LATITUDE_RANGE = (20.0, 46.0)
_JAPAN_LONGITUDE_RANGE = (122.0, 154.0)


def latitude_from_raw(raw: str) -> float | None:
    value = _dms_to_decimal(raw)
    if value is None or not (_JAPAN_LATITUDE_RANGE[0] <= value <= _JAPAN_LATITUDE_RANGE[1]):
        return None
    return value


def longitude_from_raw(raw: str) -> float | None:
    value = _dms_to_decimal(raw)
    if value is None or not (_JAPAN_LONGITUDE_RANGE[0] <= value <= _JAPAN_LONGITUDE_RANGE[1]):
        return None
    return value


def distance_weighted_accident_density(
    segments: list[tuple[float, float | None]], years_covered: int
) -> float | None:
    """(区間distance_km, 区間内の事故count)のリストと収録年数から、ルート全体の事故密度
    （件/(km・年)）を求める（外部静的データソース T50残作業）。

    stop_density/intersection_density（domain/traffic.py: _density_per_km）と同じ
    「合計count÷合計distance_km」の集約に、収録年数での正規化を加える点が異なる
    （事故は複数年分を積み上げて集計するため、年数で割らないと収録年数を増やすほど
    見かけ上密度が上がってしまう）。traffic.pyの_density_per_kmはモジュール非公開のため、
    ここに薄く複製する（accident.py→traffic.pyへの依存は意味的に不要なため作らない）。
    countがNoneの区間は「データ未取得」を表し、0（実測で対象無し）とは区別して集計から
    除外する。除外後に1区間も残らない、距離の合計が0以下、またはyears_coveredが0以下なら
    None。

    countはint（単純件数）ではなくfloat（改善計画: 事故密度の精度改善で死亡事故を
    `ACCIDENT_FATAL_WEIGHT`倍として積算したSUM、road_graph_repository.py:
    _ACCIDENT_COUNTS_SQL参照）。
    """
    if years_covered <= 0:
        return None
    available = [(distance, count) for distance, count in segments if count is not None]
    if not available:
        return None
    distance_sum = sum(distance for distance, _ in available)
    if distance_sum <= 0:
        return None
    count_sum = sum(count for _, count in available)
    return round(count_sum / distance_sum / years_covered, 2)
