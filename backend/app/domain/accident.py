"""警察庁交通事故統計オープンデータの取込で使う純関数群。

本票CSV（honhyo_YYYY.csv）の列定義・コード値の典拠は警察庁が公開するコード表CSV
（https://www.npa.go.jp/publications/statistics/koutsuu/opendata/koudohyou/）。
"""

# 事故地点を道路へスナップする際の探索半径。事故点はOSMの要素ではないため、信号・交差点の
# ように「wayの構成ノードか」で帰属を決められず、距離で最も近い道路を選ぶしかない。
# 緯度経度は本票の度分秒表記からの変換値でOSM nodeよりジオコーディング精度が粗いため、
# 半径は大きめに採る。
ACCIDENT_MATCH_MAX_DISTANCE_M = 30.0

# 死亡事故の重み。件数を単純にCOUNTすると軽傷の物損に近い事故と死亡事故が同じ1件として
# 扱われ、最も避けたい重大事故のリスクが薄まるため、死亡事故はこの件数分として積算する
# （「死亡事故は軽傷事故の3件分のリスク」という意味づけの値で、実測から導いたものではない）。
ACCIDENT_FATAL_WEIGHT = 3.0

# 当事者種別（31_koudohyou_toujisyasyuetu.csv）のうち自転車に該当するコード。
# 51=軽車両－自転車、52=軽車両－駆動補助機付自転車（電動アシスト自転車）。
# 59（軽車両－その他）は自転車ではない軽車両（手押し車等）のため含めない。
BICYCLE_PARTY_TYPE_CODES: frozenset[str] = frozenset({"51", "52"})


def _dms_to_decimal(raw: str) -> float | None:
    """本票の緯度・経度列（度分秒を1つの数値へ連結した表記。右5桁=秒×1000、
    次の2桁=分、残り=度）を10進の度へ変換する。欠損（空・非数値）や
    分/秒が60以上になる不正値はNone（根拠のない推測はしない）。

    全て0の列は0度として通す。日本の範囲外として落とすのは`latitude_from_raw`／
    `longitude_from_raw`の側で、ここは表記の解釈だけを負う。"""
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
# 度分秒からの変換結果が壊れていないかを見るためだけのもので、対象地域の絞り込みではない。
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

# --- 生データの列から判定する式 -----------------------------------------------
#
# 本票の列名（日本語）と判定の規則をここだけが持つ。生データは列を捨てずに`attrs`へ
# 入れてあるため、読む側は都度これを使う——同じ判定をタイルと集計で別々に書くとずれる。
# 別名`a`は`source_features`の事故の行を指す。

#: 死者数の列。ゼロ埋めの数字列で入っている。
FATAL_SQL = "coalesce((a.attrs->>'死者数')::int, 0) > 0"

#: 当事者種別のいずれかが自転車系コードなら自転車関連事故とみなす。
BICYCLE_SQL = (
    "(a.attrs->>'当事者種別（当事者A）' = ANY(:bicycle_party_types)"
    " OR a.attrs->>'当事者種別（当事者B）' = ANY(:bicycle_party_types))"
)

#: 発生年（全角空白を含む列名）。
OCCURRED_YEAR_SQL = "(a.attrs->>'発生日時　　年')::int"
