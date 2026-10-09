"""住所の区画（都道府県・市区町村・区・大字/町・丁目/字）の語彙と、住所の表記を揃える形・検索の鍵の作り方・区画の祖先から
辺りの名前を組み立てる形。

区画の表（`address_areas`）と鍵の表（`address_search_keys`）は派生の段（`batch/derive_addresses.py`）が作り、
ここは段の語彙と、入力と鍵の両方にかける揃え方（`standardize_address`）・区画の名前から鍵を作る形（`search_keys`）・
施設の辺りの名前（`area_label`）を持つ。
アドレス・ベース・レジストリ（ABR）の列の読み方は`infrastructure/source_models.py`が持ち、ここへは名前で届く。
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence

from app.domain.place_search import PlaceMatchLevel

#: 区画の段（粗い→細かい）。郡は段にせず、郡に属す町村の区画が名前（`county_name`）で持つ。
ADDRESS_AREA_LEVELS: tuple[PlaceMatchLevel, ...] = ("prefecture", "city", "ward", "oaza", "aza")

#: 鍵を続き（打ちかけの語を頭に持つ区画）に使う段。大字・町までで、丁目・字は続きに出さない。
CONTINUABLE_LEVELS: frozenset[PlaceMatchLevel] = frozenset({"prefecture", "city", "ward", "oaza"})

#: ABR の町字区分（`machiaza_type`）→ 区画の段。1 が大字・町、2 が丁目、3 が小字。ここに無い区分（4 町字なし・
#: 5 道路名）は区画の行を作らない。
MACHIAZA_TYPE_LEVELS: dict[str, PlaceMatchLevel] = {"1": "oaza", "2": "aza", "3": "aza"}

#: ハイフン・ダッシュ・マイナスの類（長音を含まない）。最後を半角のハイフンにしてあり、正規表現の文字類の末尾に
#: 置けばそのまま文字として読まれる。施設の名前の揃え方（`domain/stop_place.py: normalized_sql`）も同じ集合を除く。
HYPHEN_CHARACTERS = "‐‑‒–—―−-"

#: 住所の揃え方で`-`へ寄せる文字。ハイフンの類に長音（NFKC のあとの「ー」。半角の「ｰ」もここへ寄る）を足したもの。
_HYPHENS = re.compile(f"[ー{HYPHEN_CHARACTERS}]")
_SPACES = re.compile(r"\s+")
_KANJI_NUMERALS = "〇一二三四五六七八九"
_KANJI_DIGITS = {c: n for n, c in enumerate(_KANJI_NUMERALS)}
_KANJI_NUMBER = re.compile("[〇一二三四五六七八九十]+")
_CHOME = re.compile(r"(\d+)丁目?")
_KE = re.compile("[ヶヵケがゖ]")
_NO = re.compile("[の之ノ]")


def _kanji_number(match: re.Match[str]) -> str:
    """漢数字の並びを算用数字へ。「十」は1つまで（「二十三」→23・「十」→10）。読めない並びはそのまま。"""
    text = match.group(0)
    tens, has_ten, ones = text.partition("十")
    try:
        if not has_ten:
            return str(int("".join(str(_KANJI_DIGITS[c]) for c in text)))
        return str((_KANJI_DIGITS[tens] if tens else 1) * 10 + (_KANJI_DIGITS[ones] if ones else 0))
    except KeyError:
        return text


def standardize_address(text: str) -> str:
    """住所の表記の揺れを除いた形。打った入力と区画の鍵の両方にかけ、同じ住所が同じ文字列になるようにする。

    NFKC・小文字・空白を除く → ハイフンと長音の類を`-` → 漢数字を算用数字 → 数字の後の「丁目」「丁」を`-`
    → 「大字」を除く → 「ヶ」「ヵ」「ケ」「が」を「ケ」・「の」「之」「ノ」を「ノ」。
    """
    text = _SPACES.sub("", unicodedata.normalize("NFKC", text).lower())
    text = _HYPHENS.sub("-", text)
    text = _KANJI_NUMBER.sub(_kanji_number, text)
    text = _CHOME.sub(r"\1-", text)
    text = text.replace("大字", "")
    text = _KE.sub("ケ", text)
    return _NO.sub("ノ", text)


def chome_name(number: str, written: str) -> str:
    """丁目の区画の名前（「四丁目」「四十二丁目」「六丁」）。

    ABR の丁目の表記は「４丁目」「四丁目」「６丁」が市区町村ごとに混ざるので、番号（`chome_number`）から漢数字で作り、
    見た目をそろえる。「丁」で終わる表記は「丁」のまま。
    """
    tens, ones = divmod(int(number), 10)
    digits = ("" if tens < 2 else _KANJI_NUMERALS[tens]) + ("十" if tens else "") + (_KANJI_NUMERALS[ones] if ones else "")
    return digits + ("丁" if written.endswith("丁") else "丁目")


def area_label(chain: Iterable[tuple[str, str]]) -> str:
    """施設の辺りの名前（「川口市元郷四丁目」「さいたま市岩槻区本町」）。

    `chain`は区画の祖先を都道府県から区画まで並べた (段, 名前)。市区町村から先の名前をつなぎ、都道府県は持たない
    （政令市は市と区をつなぐ。郡は区画の段でないので並びに出ない）。
    """
    return "".join(name for level, name in chain if level != "prefecture")


def search_keys(heads: Sequence[tuple[str, str]], tails: Iterable[str] = ("",)) -> frozenset[str]:
    """区画を引く鍵（`standardize_address`をかけた形）。

    `heads`は都道府県から区画（字・丁目なら大字）までの (段, 名前) の並びで、段は`prefecture`・`county`・`city`・
    `ward`・`oaza`。名前の空の段は飛ばす。書き始める段ごとの形（「東京都新宿区西新宿」「新宿区西新宿」「西新宿」）と、
    郡があれば都道府県から書いて郡を省いた形を作り、それぞれの後ろに`tails`（字・丁目の名前。区画そのものが
    `heads`の最後なら空）の1つずつを付ける。
    """
    names = [(level, name) for level, name in heads if name]
    variants = [[name for _, name in names[start:]] for start in range(len(names))]
    if names and names[0][0] == "prefecture" and any(level == "county" for level, _ in names):
        variants.append([name for level, name in names if level != "county"])
    keys = {standardize_address("".join(parts) + tail) for parts in variants for tail in tails}
    return frozenset(key for key in keys if key)
