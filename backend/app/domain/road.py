# OSMの路面を表すタグ（自由記述に近い文字列）の読み方。材料の値式・MVT生成SQL・地図の表示行・
# 材料の値の呼び名（区分の名前・タグの値の呼び名）は、すべてここの宣言から導く。

from collections.abc import Mapping
from typing import NamedTuple


class SurfaceClass(NamedTuple):
    """surfaceタグの路面区分の1つ。**区分は「走りやすさの違いが出る単位」で束ねる**——OSMの値を網羅する
    体系ではなく、稀な値は区分を持たない側（その他）へ落とす。

    `paved`は材料「舗装良否」の真偽で、舗装良否はこの区分から導く（区分と良否を別々に宣言すると、
    同じタグの判定が2か所に分かれる）。`tags`は区分に属するタグの値→その値の呼び名で、タグの値の
    呼び名もここにしか書かない（対訳を別の表に持つと、区分へ足したタグに呼び名が無いまま生の値で画面に出る）。"""

    key: str
    label: str
    paved: bool
    tags: Mapping[str, str]


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
    ),
    SurfaceClass(
        "compacted",
        "締め固め・細砂利",
        False,
        {"compacted": "締固め砂利", "fine_gravel": "細砂利"},
    ),
    SurfaceClass(
        "gravel",
        "砂利・未舗装",
        False,
        {"gravel": "砂利", "pebblestone": "小石敷き", "rock": "岩盤", "unpaved": "未舗装（種別不明）"},
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
    ),
    SurfaceClass(
        "cobblestone",
        "石畳",
        False,
        {"sett": "石畳（玉石）", "cobblestone": "玉石舗装", "unhewn_cobblestone": "玉石舗装（未加工）"},
    ),
)

#: タグはあるが、どの区分にも当てはまらない値の道の区分。舗装良否は不明（良い・悪いのどちらにも倒さない）。
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
    """tracktypeタグの等級。値はOSMの語彙そのもので、並びは固い路面から柔らかい路面への順。"""

    value: str
    label: str


#: 呼び名はOSMの定義（Key:tracktype）の路面の中身から付ける。並びが地図の凡例の並び。
TRACK_GRADES: tuple[TrackGrade, ...] = (
    TrackGrade("grade1", "1 舗装・固く締まる"),
    TrackGrade("grade2", "2 砂利[未舗装]"),
    TrackGrade("grade3", "3 砂利と土が半々"),
    TrackGrade("grade4", "4 土・草が主"),
    TrackGrade("grade5", "5 土・草・砂"),
)
