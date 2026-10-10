"""立ち寄り先（食べる・飲む・入浴・自転車・景色・名所・泊まる・コンビニ・寺社）の群と、地点を群へ入れる判断・地点の検索で
打った語を群として読む判断。

地点の生データの列の読み替えは`infrastructure/source_models.py: OVERTURE_PLACES_SOURCE_SQL`・`BUNKA_HERITAGES_SOURCE_SQL`
が持ち、ここへは読み替えた列で届く。群へ入れ、近くの同じ店をまとめるのは派生の段（`batch/derive_stop_places.py`）で、
取込（`batch/source_adapters/overture_places.py`）はどの群にも当たりえない地点を落とすだけである。

寺社・宗教施設と、補給の点のうちコンビニ以外（自販機・トイレ・給水・駐輪場）に当たる分類は、どの群の語にも
入れない——寺社は文化財の一覧から、補給の点は OpenStreetMap から出す（1つの種類を2つの出どころから出さない）。
補給の点のコンビニは、群「コンビニ」の行から出す（`infrastructure/point_tile_layers.py`の`poi`）。
"""

import re
import unicodedata
from enum import StrEnum

from app.domain.address_area import HYPHEN_CHARACTERS


class StopPlaceGroup(StrEnum):
    """立ち寄り先の群。地図のチップで選ぶ単位で、点のタイルの属性`group`の値。"""

    EAT_DRINK = "eat_drink"
    BATH = "bath"
    BICYCLE = "bicycle"
    SCENIC = "scenic"
    LODGING = "lodging"
    CONVENIENCE = "convenience"
    #: 国の指定・登録の文化財の建造物を持つ寺社（下の`temple_shrine_owner_sql`）。
    TEMPLE_SHRINE = "temple_shrine"


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

#: 群 → 打てばその群の店を近い順に出す語。利用者はどの群があるかを知らないので、群の名前と、群そのものを指す
#: 言い換えを広く受ける。群の一部の種類だけを指す語（「公園」「ホテル」「神社」「カフェ」）は入れない——入れると、
#: 群の別の種類の店（「公園」で博物館、「カフェ」でラーメン屋）が近い順に先に出る。その語は店の名前で引く。
PLACE_GROUP_WORDS: dict[StopPlaceGroup, tuple[str, ...]] = {
    StopPlaceGroup.CONVENIENCE: ("コンビニ", "コンビニエンスストア", "convenience", "convenience store", "konbini"),
    StopPlaceGroup.BATH: (
        "銭湯", "銭湯・温泉", "温泉", "天然温泉", "日帰り温泉", "スーパー銭湯", "スパ銭", "風呂", "お風呂", "入浴",
        "日帰り入浴", "浴場", "公衆浴場", "健康ランド", "サウナ", "sento", "onsen", "sauna"),
    StopPlaceGroup.EAT_DRINK: ("飲食店", "飲食", "食事", "ご飯", "ごはん", "グルメ", "レストラン"),
    StopPlaceGroup.LODGING: ("宿", "宿泊", "宿泊施設", "泊まる", "泊まる所", "泊まれる所"),
    StopPlaceGroup.BICYCLE: ("自転車", "自転車屋", "自転車店", "サイクルショップ", "自転車修理"),
    StopPlaceGroup.SCENIC: ("景色・名所", "景色", "絶景", "名所", "観光地", "観光スポット", "景勝地", "見どころ"),
    StopPlaceGroup.TEMPLE_SHRINE: ("寺社", "社寺", "神社仏閣", "寺社仏閣"),
}

#: 群の語を当てる形で除く文字（空白・中点・ハイフンの類。長音は残す——「スーパー」が「スパ」にならない）。
_GROUP_WORD_IGNORED = re.compile(f"[\\s・{HYPHEN_CHARACTERS}]")
#: ひらがな → カタカナ。
_HIRAGANA_TO_KATAKANA = {code: code + 0x60 for code in range(ord("ぁ"), ord("ゖ") + 1)}


def _group_word_form(text: str) -> str:
    return _GROUP_WORD_IGNORED.sub("", unicodedata.normalize("NFKC", text).lower()).translate(_HIRAGANA_TO_KATAKANA)


_GROUP_BY_WORD: dict[str, StopPlaceGroup] = {
    _group_word_form(word): group for group, words in PLACE_GROUP_WORDS.items() for word in words}


def queried_group(query: str) -> StopPlaceGroup | None:
    """入力が群の語（`PLACE_GROUP_WORDS`。表記の揺れ——全角・半角・大文字・空白・中点・ひらがなとカタカナ——を除いて比べる）
    なら、その群。語を含むだけの入力（「大江戸温泉物語」）は店の名前でありうるので、群として読まない。"""
    return _GROUP_BY_WORD.get(_group_word_form(query))


#: どれかの群に入る語の全部。取込はこのどれも道筋に持たない地点を落とす。
OVERTURE_GROUPED_WORDS: frozenset[str] = frozenset().union(*(words for _, words in OVERTURE_GROUP_WORDS))

#: 同じ群・同じチェーンの地点を1つにまとめる距離（地面の m）。同じ店が出どころごとに少しずれた位置で
#: 重なって入っているのを1つにする。チェーンの分からない地点は別々の店として扱い、まとめない。
MERGE_RADIUS_M = 30.0

#: 名前に日本語の文字（かな・漢字）が無い地点を、同じ連絡先を持つ日本語の名前の地点へ寄せる群と、寄せる距離（地面の m）。
#: 同じ場所が出どころの中で言語違いの別の行（Facebook のページ等）として重なって入っているのを1つにする。Overture の地点には
#: 重なりを結ぶ ID も言語ごとの名前も無い。飲食は入れない——同じ連絡先を持つ近くの店は、同じビル・同じ会社の別の店が多い。
#: 景色・名所は場所が広く、同じ公園の行が100m以上離れて入る。値の根拠は docs/modules/backend/static-road-attributes.md「立ち寄り先」。
CONTACT_MERGE_RADIUS_M: dict[StopPlaceGroup, float] = {
    StopPlaceGroup.SCENIC: 200.0,
    StopPlaceGroup.LODGING: MERGE_RADIUS_M,
    StopPlaceGroup.BATH: MERGE_RADIUS_M,
    StopPlaceGroup.BICYCLE: MERGE_RADIUS_M,
}

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
    """名前の表記の揺れ（全角・半角・大文字・空白・ハイフンの類・中点）を除いた形を出す式。ハイフンの類は住所の揃え方と
    同じ集合（`domain/address_area.py: HYPHEN_CHARACTERS`。末尾が半角のハイフンで、文字類の末尾に置く）。"""
    return f"lower(regexp_replace(normalize({text_expr}, NFKC), '[[:space:]・･{HYPHEN_CHARACTERS}]', '', 'g'))"


def japanese_name_sql(name_expr: str) -> str:
    """名前に日本語の文字（ひらがな・カタカナ・半角カナ・漢字）があるかの式。"""
    return f"({name_expr} ~ '[ぁ-ゟ゠-ヿｦ-ﾟ㐀-䶿一-鿿々〆]')"


def contacts_sql(websites_expr: str, phones_expr: str) -> str:
    """地点の連絡先（ウェブサイト・電話。jsonb の文字列の配列か null）を、1つずつ比べられる形の行に出す副問い合わせ
    （列`contact`）。ウェブサイトは小文字にして`http(s)://`・`www.`・末尾の`/`を除き、電話は数字だけにして頭の国番号を0にする
    （配布には`+81339412222`と`03-3941-2222`の両方の書き方がある）。"""

    def elements(expr: str) -> str:
        return f"jsonb_array_elements_text(CASE WHEN jsonb_typeof({expr}) = 'array' THEN {expr} ELSE '[]' END)"

    website = "regexp_replace(lower(trim(w)), '^https?://(www\\.)?|^www\\.|/+$', '', 'g')"
    phone = "regexp_replace(regexp_replace(t, '[^0-9]', '', 'g'), '^81', '0')"
    return (f"SELECT 'w:' || {website} AS contact FROM {elements(websites_expr)} w WHERE {website} <> ''"
            f" UNION SELECT 't:' || {phone} FROM {elements(phones_expr)} t WHERE {phone} <> ''")


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


#: 同じ所有者の文化財の建物を1つの寺社にまとめる距離（地面の m）。境内に散らばる建物（本堂・山門・別院）は1つにし、
#: 同じ名前の別の寺社・離れた奥之院は分ける。値の根拠は docs/modules/backend/static-road-attributes.md「立ち寄り先」。
HERITAGE_MERGE_RADIUS_M = 1000.0

#: 所有者の名前がこの語で終われば寺社。所有者の欄が寺社を名指すのは、法人の名前が寺社そのものの名前だから。
#: キリスト教の教会・教団・教区と、新しい宗教団体（「〜教」「〜殿」等）はどれでも終わらない。
TEMPLE_SHRINE_SUFFIXES: tuple[str, ...] = (
    "寺", "院", "神社", "大社", "神宮", "宮", "社", "稲荷", "八幡", "権現", "坊", "庵", "斎", "廟")

#: 寺社の語で終わっても寺社でない名前の終わり。
NOT_TEMPLE_SHRINE_SUFFIXES: tuple[str, ...] = ("病院", "医院", "学院", "修道院", "美術院", "研究院")

#: 寺社の語で終わっても、これを含めば寺社でない（学校法人○○学院・株式会社○○社・特定非営利活動法人○○寺 等）。
#: 宗教法人の印は名前から先に外す（`owner_name_sql`）。
NOT_TEMPLE_SHRINE_WORDS: tuple[str, ...] = ("法人", "会社")


def owner_lines_sql(owners_expr: str) -> str:
    """文化財の所有者の欄を、1人ずつの行に分ける式（集合を返す）。複数の所有者は改行か読点で並ぶ。"""
    return f"regexp_split_to_table({owners_expr}, '[\\n、,，]')"


def owner_name_sql(owner_expr: str) -> str:
    """所有者の欄の1人ぶんから、頭の宗教法人の印（「宗教法人」「（宗教法人）」）と末尾の括弧書き（「（豊川）」）を除いた名前の式。"""
    # 空白には全角の空白も入る（「宗教法人　日本基督教団」）。
    trimmed = f"regexp_replace({owner_expr}, '^[[:space:]　]+|[[:space:]　]+$', '', 'g')"
    stripped = f"regexp_replace({trimmed}, '^[（(]?宗教法人[）)]?[[:space:]　]*', '')"
    return f"regexp_replace({stripped}, '[[:space:]　]*[（(][^）)]*[）)]$', '')"


def temple_shrine_owner_sql(name_expr: str) -> str:
    """`owner_name_sql`の名前が寺社の名前かの式。"""
    suffixes = "|".join(TEMPLE_SHRINE_SUFFIXES)
    not_suffixes = "|".join(NOT_TEMPLE_SHRINE_SUFFIXES)
    not_words = "|".join(NOT_TEMPLE_SHRINE_WORDS)
    return (f"({name_expr} ~ '({suffixes})$' AND {name_expr} !~ '({not_suffixes})$'"
            f" AND {name_expr} !~ '{not_words}')")
