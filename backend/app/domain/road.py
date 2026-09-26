# OSMの路面を表すタグ（自由記述に近い文字列）の読み方。材料の値式・MVT生成SQL・地図の表示行・
# 材料の値の呼び名（区分の名前・タグの値の呼び名）・舗装良否・走行モデルの転がり抵抗は、すべてここの
# 宣言から導く。

from collections.abc import Mapping
from typing import NamedTuple

from app.domain.tuning import TUNING_PARAMETERS_BY_ID


class SurfaceClass(NamedTuple):
    """surfaceタグの路面区分の1つ。**区分は「走りやすさの違いが出る単位」で束ねる**——OSMの値を網羅する
    体系ではなく、稀な値は区分を持たない側（その他）へ落とす。

    `paved`は材料「舗装良否」の真偽、`rolling_resistance`は走行モデルがこの区分の道で使う転がり抵抗の
    較正値のid（`domain/tuning.py`）。どちらも区分から導く（区分と別々に宣言すると、同じタグの判定が
    2か所に分かれる）。`tags`は区分に属するタグの値→その値の呼び名で、タグの値の
    呼び名もここにしか書かない（対訳を別の表に持つと、区分へ足したタグに呼び名が無いまま生の値で画面に出る）。"""

    key: str
    label: str
    paved: bool
    tags: Mapping[str, str]
    rolling_resistance: str


#: 並びが地図の凡例の並び。
SURFACE_CLASSES: tuple[SurfaceClass, ...] = (
    # 切石・レンガの敷石はロードバイクで普通に走れる平滑な舗装として扱う（舗装良否は良）。
    SurfaceClass(
        "paved",
        "舗装",
        True,
        {
            "asphalt": "アスファルト",
            "paved": "舗装（種別不明）",
            "chipseal": "チップシール舗装",
            "concrete": "コンクリート",
            "concrete:plates": "コンクリート版",
            "concrete:lanes": "コンクリート帯（轍部のみ舗装）",
            "paving_stones": "石畳（切石）",
            "bricks": "レンガ舗装",
        },
        "speed.crr",
    ),
    SurfaceClass(
        "compacted",
        "締め固め・細砂利",
        False,
        {"compacted": "締固め砂利", "fine_gravel": "細砂利"},
        "speed.crr_compacted",
    ),
    SurfaceClass(
        "gravel",
        "砂利・未舗装",
        False,
        {"gravel": "砂利", "pebblestone": "小石敷き", "rock": "岩盤", "unpaved": "未舗装（種別不明）"},
        "speed.crr_gravel",
    ),
    SurfaceClass(
        "soil",
        "土・草・泥・砂",
        False,
        {
            "dirt": "土",
            "ground": "地面（土・砂利混合）",
            "earth": "土（地表面）",
            "mud": "泥",
            "sand": "砂",
            "grass": "芝・草地",
            "woodchips": "ウッドチップ",
        },
        "speed.crr_soil",
    ),
    SurfaceClass(
        "cobblestone",
        "石畳",
        False,
        {"sett": "石畳（玉石）", "cobblestone": "玉石舗装", "unhewn_cobblestone": "玉石舗装（未加工）"},
        "speed.crr_cobblestone",
    ),
)

#: タグはあるが、どの区分にも当てはまらない値の道の区分。路面の見込みでは区分の無い道と同じに扱う
#: （良い・悪いのどちらにも倒さず、等級が無ければ不明）。
SURFACE_OTHER_KEY = "other"
SURFACE_OTHER_LABEL = "その他"


def _check_each_tag_in_one_class(classes: tuple[SurfaceClass, ...]) -> None:
    """同じタグを2つの区分へ書くと、どちらで塗られるかがSQLの評価順で決まる。読み込みの時点で落とす。"""
    seen: dict[str, str] = {}
    for surface_class in classes:
        for tag in surface_class.tags:
            if tag in seen:
                raise ValueError(f"surfaceの値'{tag}'が区分'{seen[tag]}'と'{surface_class.key}'の両方にある")
            seen[tag] = surface_class.key
    if SURFACE_OTHER_KEY in {surface_class.key for surface_class in classes}:
        raise ValueError(f"区分の鍵'{SURFACE_OTHER_KEY}'は区分に当てはまらない値の側が使う")


_check_each_tag_in_one_class(SURFACE_CLASSES)


class TrackGrade(NamedTuple):
    """tracktypeタグの等級。値はOSMの語彙そのもので、並びは固い路面から柔らかい路面への順。

    `surface_class`は、surfaceタグの無い道でこの等級から見込む路面の区分（`SURFACE_CLASSES`の鍵）。"""

    value: str
    label: str
    surface_class: str


#: 呼び名はOSMの定義（Key:tracktype）の路面の中身から付ける。並びが地図の凡例の並び。
#: 見込む区分は、surfaceタグも付いた道でその等級に最も多い路面から決める。
TRACK_GRADES: tuple[TrackGrade, ...] = (
    TrackGrade("grade1", "1 舗装・固く締まる", "paved"),
    TrackGrade("grade2", "2 砂利[未舗装]", "gravel"),
    TrackGrade("grade3", "3 砂利と土が半々", "gravel"),
    TrackGrade("grade4", "4 土・草が主", "soil"),
    TrackGrade("grade5", "5 土・草・砂", "soil"),
)


class SurfaceEstimate(NamedTuple):
    """材料「路面の見込み」の値の1つ。surfaceタグの区分があればそれ、無ければtracktypeの等級から写した
    区分、どちらも無ければ「不明」（surfaceタグがどの区分にも当てはまらない値の道も、等級が無ければ不明）。
    舗装質の軸と走行モデルの転がり抵抗は、どちらもこの値を読む。

    `paved`は舗装良否（Noneは不明）、`rolling_resistance`は転がり抵抗の較正値のid。"""

    key: str
    label: str
    paved: bool | None
    rolling_resistance: str


#: 区分も等級も無い道のうち、「不明（農道・林道）」にする道路種別。
TRACK_HIGHWAY = "track"
#: 区分も等級も無い農道・林道。舗装の道も未舗装の道も多いので、転がり抵抗は両者の間の値を使う。
UNKNOWN_TRACK_SURFACE = SurfaceEstimate("unknown_track", "不明（農道・林道）", None, "speed.crr_unknown")
#: 区分も等級も無い、農道・林道以外の道。タグの付いたこの種の道はほぼ舗装なので、舗装の転がり抵抗を使う。
UNKNOWN_ROAD_SURFACE = SurfaceEstimate("unknown_road", "不明（一般の道）", None, "speed.crr")

def surface_estimates(classes: tuple[SurfaceClass, ...]) -> tuple[SurfaceEstimate, ...]:
    """路面の見込みがとりうる値: surfaceの区分と、2つの不明。"""
    return (
        *(SurfaceEstimate(c.key, c.label, c.paved, c.rolling_resistance) for c in classes),
        UNKNOWN_TRACK_SURFACE,
        UNKNOWN_ROAD_SURFACE,
    )


SURFACE_ESTIMATES = surface_estimates(SURFACE_CLASSES)


def _check_estimates_are_consistent(
    classes: tuple[SurfaceClass, ...], grades: tuple[TrackGrade, ...], estimates: tuple[SurfaceEstimate, ...]
) -> None:
    """等級が写す先の区分が無いと、その等級の道の見込みがSQLで区分の外の値になる。鍵が重なると、
    見込みの値から舗装良否・転がり抵抗を引いたときにどちらの宣言か決まらない。転がり抵抗の較正値が
    宣言に無いと、最初のルート生成で落ちる。どれも読み込みの時点で落とす。"""
    class_keys = {c.key for c in classes}
    missing = sorted({g.surface_class for g in grades} - class_keys)
    if missing:
        raise ValueError(f"等級が写す区分{missing}がsurfaceの区分に無い")
    keys = [e.key for e in estimates]
    duplicated = sorted({k for k in keys if keys.count(k) > 1})
    if duplicated:
        raise ValueError(f"路面の見込みの鍵{duplicated}が重なっている")
    undeclared = sorted({e.rolling_resistance for e in estimates} - TUNING_PARAMETERS_BY_ID.keys())
    if undeclared:
        raise ValueError(f"転がり抵抗の較正値{undeclared}が`domain/tuning.py`に無い")


_check_estimates_are_consistent(SURFACE_CLASSES, TRACK_GRADES, SURFACE_ESTIMATES)
