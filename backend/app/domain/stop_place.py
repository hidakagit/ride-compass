"""立ち寄り先（食べる・飲む・入浴・自転車・景色・名所・泊まる・コンビニ）の群と、地点を群へ入れる判断。

地点の生データの列の読み替えは`infrastructure/source_models.py: OVERTURE_PLACES_SOURCE_SQL`が持ち、
ここへは読み替えた列で届く。群へ入れ、近くの同じ店をまとめるのは派生の段（`batch/derive_stop_places.py`）で、
取込（`batch/source_adapters/overture_places.py`）はどの群にも当たりえない地点を落とすだけである。

寺社・宗教施設と、補給の点のうちコンビニ以外（自販機・トイレ・給水・駐輪場）に当たる分類は、どの群の語にも
入れない——寺社は文化財の一覧から、補給の点は OpenStreetMap から出す（1つの種類を2つの出どころから出さない）。
補給の点のコンビニは、群「コンビニ」の行から出す（`infrastructure/point_tile_layers.py`の`poi`）。
"""

from enum import StrEnum


class StopPlaceGroup(StrEnum):
    """立ち寄り先の群。地図のチップで選ぶ単位で、点のタイルの属性`group`の値。"""

    EAT_DRINK = "eat_drink"
    BATH = "bath"
    BICYCLE = "bicycle"
    SCENIC = "scenic"
    LODGING = "lodging"
    CONVENIENCE = "convenience"


#: Overture の分類（`taxonomy.hierarchy`。上の段から下の段への語の並び）の語 → 群。道筋に語が1つでも
#: あればその群で、上の行から先に当たった群に入れる。語は細かい段を名指す——上の段を名指すと、下に
#: 立ち寄り先でない分類を抱える（`lodging`だけの行は寮・住所が多く、`historic_site`はマンションの名前が
#: 多く、`spa`はエステ・マッサージ）。公式の分類の一覧: https://docs.overturemaps.org/guides/places/
OVERTURE_GROUP_WORDS: tuple[tuple[StopPlaceGroup, frozenset[str]], ...] = (
    (StopPlaceGroup.EAT_DRINK, frozenset({"food_and_drink"})),
    (StopPlaceGroup.BATH, frozenset({"public_bath_house", "sauna", "hot_springs"})),
    (StopPlaceGroup.BICYCLE, frozenset({
        "bike_store", "bike_repair_maintenance", "bike_rental", "bike_sharing_location"})),
    (StopPlaceGroup.SCENIC, frozenset({
        "park", "garden", "lake", "waterfall", "mountain", "beach", "castle", "observatory", "museum",
        "nature_reserve"})),
    (StopPlaceGroup.LODGING, frozenset({
        "hotel", "hostel", "inn", "bed_and_breakfast", "campground", "resort", "lodge", "cabin", "cottage"})),
    (StopPlaceGroup.CONVENIENCE, frozenset({"convenience_store"})),
)

#: どれかの群に入る語の全部。取込はこのどれも道筋に持たない地点を落とす。
OVERTURE_GROUPED_WORDS: frozenset[str] = frozenset().union(*(words for _, words in OVERTURE_GROUP_WORDS))

#: 同じ群・同じチェーンの地点を1つにまとめる距離（地面の m）。同じ店が出どころごとに少しずれた位置で
#: 重なって入っているのを1つにする。チェーンの分からない地点は別々の店として扱い、まとめない。
MERGE_RADIUS_M = 30.0

#: チェーン → 名前かブランドに含まれていればそのチェーンとみなす語（`normalized_sql`で正規化した形）。上の行から
#: 先に当たったチェーンに入れる（`ローソンストア100`を`ローソン`より先に置く）。ブランドの列は出どころによって
#: 空か表記がばらばら（「FamilyMart」「ローソン Lawson Japan」）で、同じ店が「セブン-イレブン」と
#: 「セブンイレブン 南浦和駅西口店」のように入るので、表記の揺れをここで寄せる。ほかのチェーンはブランドの一致で見る。
#: 旧名（サンクス・サークルK・セーブオン等）は、看板を替えた店の古い地点が今の店の隣に残っているので、今のチェーンへ寄せる。
#:
#: **ここに並ぶのはコンビニのチェーンだけで、群「コンビニ」はここに当たる地点だけを入れる**（`kept_sql`）。Overture の
#: `convenience_store`には、100円ショップ・ドラッグストア・小さなスーパー・個人の商店・駐車場等も入っている。
#: 語は関東の地点（2026-09-23.1）で当たらなかった名前から足した。1件ずつの打ち間違い（「ロ−ソン」等）は足さない。
CHAIN_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("seven_eleven", ("セブンイレブン", "7eleven", "seveneleven")),
    ("familymart", (
        "ファミリーマート", "familymart", "ファミマ", "サンクス", "サークルk", "circlek", "サークルケイ", "サークルケー",
        "ココストア", "エーエムピーエム")),
    ("lawson_store100", ("ローソンストア100", "lawsonstore100", "ストア100", "store100", "ショップ99")),
    ("natural_lawson", ("ナチュラルローソン", "naturallawson")),
    ("lawson", ("ローソン", "lawson", "セーブオン")),
    ("ministop", ("ミニストップ", "ministop")),
    # ヤマザキデイリーストア・ニューヤマザキデイリーストアは同じ会社の旧い看板。
    ("daily_yamazaki", ("デイリーヤマザキ", "dailyyamazaki", "デイリーストア")),
    ("yamazaki_shop", ("ヤマザキショップ", "yショップ")),
    ("newdays", ("ニューデイズ", "newdays")),
    ("seicomart", ("セイコーマート", "seicomart")),
    ("three_f", ("スリーエフ",)),
    ("poplar", ("ポプラ",)),
    ("seikatsu_saika", ("生活彩家",)),
    ("community_store", ("コミュニティストア",)),
    ("mon_mart", ("モンマート",)),
    ("hot_spar", ("ホットスパー",)),
    ("rieven_house", ("リーベンハウス", "rievenhouse")),
    # 駅の売店。
    ("kiosk", ("キヨスク", "kiosk")),
    ("bellmart", ("ベルマート", "bellmart")),
    ("plusta", ("plusta",)),
    ("tomony", ("トモニー",)),
    ("toks", ("toks",)),
    ("odakyu_shop", ("odakyushop", "odakyumart")),
)

#: 濁点・半濁点の付いたかな → 外した形。チェーンの語は外した形どうしで当てる——濁点が空白に化けた名前
#: （「セフ ンイレフ ン」。元の文字で濁点の場所が空白になっていて、正規化では戻らない）があるため。
_VOICED_KANA = "ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポヴ"
_UNVOICED_KANA = "カキクケコサシスセソタチツテトハヒフヘホハヒフヘホウ"
_DEVOICE = str.maketrans(_VOICED_KANA, _UNVOICED_KANA)


def normalized_sql(text_expr: str) -> str:
    """名前の表記の揺れ（全角・半角・大文字・空白・ハイフン・中点）を除いた形を出す式。"""
    return f"lower(regexp_replace(normalize({text_expr}, NFKC), '[[:space:]\\-‐‑–—−・･]', '', 'g'))"


def store_name_sql(name_expr: str) -> str:
    """店の中の ATM の地点の名前（「セブン銀行ATM セブン-イレブン ○○店 共同出張所」「銀行ATM | イーネット
    ファミリーマート○○ 共同出張所」）を、中にある店の名前へ直す式。ほかの名前はそのまま。"""
    return (f"regexp_replace({name_expr},"
            " '^(?:(?:セブン)?銀行|イーネット)(?:ATM)?\\s*(?:\\|\\s*イーネット)?\\s*(.*?)\\s*共同出張所$', '\\1')")


def chain_text_sql(normalized_expr: str) -> str:
    """チェーンの語を当てる形（`normalized_sql`で正規化した式から、濁点・半濁点を外した形）を出す式。"""
    return f"translate({normalized_expr}, '{_VOICED_KANA}', '{_UNVOICED_KANA}')"


def chain_sql(name: str, brand: str) -> str:
    """地点のチェーンを出す式。`name`・`brand`は`chain_text_sql`の形の式（ブランドはNULLがある）。
    `CHAIN_WORDS`に当たらなければブランド、ブランドも無ければNULL。"""
    whens = " ".join(
        f"WHEN {' OR '.join(f'strpos({text}, {word.translate(_DEVOICE)!r}) > 0' for text in (name, brand) for word in words)} THEN {chain!r}"
        for chain, words in CHAIN_WORDS)
    return f"CASE {whens} ELSE nullif({brand}, '') END"


def kept_sql(group: str, chain: str) -> str:
    """群に入った地点を表へ入れるかの式。群「コンビニ」は`CHAIN_WORDS`のチェーンだけ、ほかの群は全部。"""
    chains = ", ".join(repr(chain_key) for chain_key, _ in CHAIN_WORDS)
    return f"({group} <> '{StopPlaceGroup.CONVENIENCE}' OR {chain} IN ({chains}))"


def overture_group_sql(hierarchy: str) -> str:
    """分類の道筋（jsonbの文字列の配列を出す式）から群を出す式。どの群にも当たらなければNULL。"""
    whens = " ".join(
        f"WHEN {hierarchy} ?| ARRAY[{', '.join(repr(word) for word in sorted(words))}] THEN '{group}'"
        for group, words in OVERTURE_GROUP_WORDS)
    return f"CASE {whens} END"
