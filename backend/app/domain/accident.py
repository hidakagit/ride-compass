"""警察庁交通事故統計オープンデータの事故を道路へ帰属させ、数えるときの判断。

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


# --- 生データの列から判定する式 -----------------------------------------------
#
# 本票の列名（日本語）と判定の規則をここだけが持つ。生データは列を捨てずに`attrs`へ
# 入れてあるため、読む側は都度これを使う——同じ判定をタイルと集計で別々に書くとずれる。
# 別名`a`は事故の生データの行（`infrastructure/source_models.py: ACCIDENTS_SOURCE_SQL`）を指す。

#: 死者数の列。ゼロ埋めの数字列で入っている。
FATAL_SQL = "coalesce((a.attrs->>'死者数')::int, 0) > 0"

def bicycle_sql(party_types: str) -> str:
    """当事者種別のいずれかが自転車系コードなら自転車関連事故とみなす式。

    `party_types`は`BICYCLE_PARTY_TYPE_CODES`を渡すtext[]のパラメータの書き方で、
    実行する側のドライバが決める（SQLAlchemyなら`:name`、asyncpgなら`$n`）。
    """
    return (f"(a.attrs->>'当事者種別（当事者A）' = ANY({party_types})"
            f" OR a.attrs->>'当事者種別（当事者B）' = ANY({party_types}))")

#: 発生年（全角空白を含む列名）。
OCCURRED_YEAR_SQL = "(a.attrs->>'発生日時　　年')::int"
