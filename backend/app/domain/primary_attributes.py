"""一次属性の語彙の宣言（地図での束ね方・凡例の行・名前）と、宣言だけから導く式。

型は`domain/registry.py`が持つ（docs/modules/backend/axis-studio.md「一次属性の語彙」）。
"""

from collections import Counter

from app.domain.registry import (
    DisplayAxisSpec,
    DisplayCategorySpec,
    PointFactSpec,
    PointThinningSpec,
    PrimaryAttributeSpec,
)
from app.domain.material_sql import CYCLEWAY_CLASSES
from app.domain.road import SURFACE_CLASSES, TRACK_GRADES, surface_class_description
from app.domain.stop_place import StopPlaceGroup
from app.domain.traffic import TAG_KIND_RULES, kind_map_sql, kinds_shown_as, stop_kind_sql

#: 元のタグの値をこの数より多く持つ種別は、説明でタグの名前だけを言う（値を並べると説明が値の一覧になる）。
_LISTED_TAG_VALUES = 3


def _values_note(tag_key: str, values: tuple[str, ...]) -> str:
    """行の説明の末尾に添える元のタグ（OSM の値そのものを行の値に持つ行）。行の値から組むので、値を足すと説明にも出る。
    連絡路（`<値>_link`）が元の値とそろっていれば「とその連絡路」とまとめる。"""
    links = sorted(v for v in values if v.endswith("_link"))
    bases = [v for v in values if not v.endswith("_link")]
    if links and links == sorted(f"{v}_link" for v in bases):
        return f"[OSM の {tag_key}={'・'.join(bases)} とその連絡路]"
    return f"[OSM の {tag_key}={'・'.join(values)}]"


def _kinds_note(kinds: tuple[str, ...]) -> str:
    """種別を行の値に持つ行の、説明の末尾に添える元のタグ。タグ→種別の表（`domain/traffic.py: TAG_KIND_RULES`）と
    信号の読み替え（`kinds_shown_as`）から引くので、どちらを変えても説明に出る。"""
    shown = {k for kind in kinds for k in kinds_shown_as(kind)}
    tags: dict[str, list[str]] = {}
    for tag_key, value, kind, _priority in TAG_KIND_RULES:
        if kind in shown:
            tags.setdefault(tag_key, []).append(value)
    if not tags:
        raise ValueError(f"種別{kinds}にタグ→種別の表の行が無い")
    return "[OSM の " + " と ".join(
        f"{key} タグ" if len(values) > _LISTED_TAG_VALUES else f"{key}={'・'.join(values)}"
        for key, values in tags.items()
    ) + "]"


def _tag_row(
    tag_key: str, key: str, label: str, values: tuple[str, ...], meaning: str
) -> DisplayCategorySpec:
    """OSM の`tag_key`の値を行の値に持つ行。説明は意味の文`meaning`に元のタグを添える。"""
    return DisplayCategorySpec(key=key, label=label, values=values, description=f"{meaning}{_values_note(tag_key, values)}。")


def _kind_row(key: str, label: str, values: tuple[str, ...], meaning: str, glyph: str | None = None) -> DisplayCategorySpec:
    """種別を行の値に持つ行。説明は意味の文`meaning`に元のタグを添える。"""
    return DisplayCategorySpec(
        key=key, label=label, values=values, glyph=glyph, description=f"{meaning}{_kinds_note(values)}。"
    )


#: 一次属性の宣言。材料が指す要素には、表の中で`:=`により名前を付ける（材料が表の要素そのものを指すことは
#: `domain/material_catalog.py: MaterialSpec`の検証が守る）。
#: 材料を1つも持たない属性（どの軸からも参照されず評価に効かない）も同じ表に並ぶ——
#: 材料を持つかどうかは材料カタログを引けば分かるため、表を分けない。
PRIMARY_ATTRIBUTES: tuple[PrimaryAttributeSpec, ...] = (
    ATTR_HIGHWAY := PrimaryAttributeSpec(
        attr_id="highway",
        tile_kind="road_surface",
        label="道路の種類",
        geometry="line",
        # 順序のある分類なので、色相ではなく濃淡で幹線→細街路を表す。
        display_axes=(
            DisplayAxisSpec(
                key="highway",
                property="highway",
                palette="ordered",
                categories=(
                    _tag_row(
                        "highway",
                        "arterial",
                        "幹線道路",
                        ("motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"),
                        "高速道路・国道・主要な県道など、車が遠くへ行くための太い通り",
                    ),
                    _tag_row(
                        "highway",
                        "secondary",
                        "主要道",
                        ("secondary", "secondary_link", "tertiary", "tertiary_link"),
                        "県道・市町村の主な道など、地域の中を結ぶ通り",
                    ),
                    _tag_row(
                        "highway",
                        "local",
                        "生活道路",
                        ("residential", "unclassified", "living_street", "service", "road"),
                        "住宅街の道・名前の付かない細い道・施設の中の通路など、主に近くへ行くための道",
                    ),
                    _tag_row(
                        "highway",
                        "cycleway",
                        "自転車・歩行者道",
                        ("cycleway", "path", "footway", "pedestrian", "bridleway", "steps"),
                        "自転車道・歩道・遊歩道・歩行者専用の道・階段など、車が通らない道",
                    ),
                    _tag_row("highway", "track", "農道・林道", ("track",), "田畑や山林へ入るための道。舗装も未舗装もある"),
                ),
            ),
        ),
    ),
    ATTR_LANES := PrimaryAttributeSpec(attr_id="lanes", label="車線数", geometry="line"),
    ATTR_MAXSPEED := PrimaryAttributeSpec(attr_id="maxspeed", label="制限速度", geometry="line"),
    ATTR_CYCLEWAY := PrimaryAttributeSpec(
        attr_id="cycleway",
        tile_kind="road_surface",
        label="自転車インフラ",
        geometry="line",
        # 行は材料「自転車の走る場所」の値そのもの。当てはまらない道は値を持たない（該当なし）。
        display_axes=(
            DisplayAxisSpec(
                key="cycleway",
                property="cycleway_class",
                palette="nominal",
                hue_slot=7,
                categories=tuple(
                    DisplayCategorySpec(key=c.key, label=c.label, values=(c.key,), description=c.description)
                    for c in CYCLEWAY_CLASSES
                ),
            ),
        ),
    ),
    ATTR_SURFACE := PrimaryAttributeSpec(
        attr_id="surface",
        tile_kind="road_surface",
        label="路面の種類",
        geometry="line",
        # 行は材料「路面の区分」の値そのもの（区分の宣言は`domain/road.py: SURFACE_CLASSES`）。
        # 区分に無い値は材料の値が「その他」になり、地図も行の外（その他）として出す。
        display_axes=(
            DisplayAxisSpec(
                key="surface",
                property="surface_class",
                palette="nominal",
                hue_slot=9,
                categories=tuple(
                    DisplayCategorySpec(
                        key=c.key, label=c.label, values=(c.key,), description=surface_class_description(c)
                    )
                    for c in SURFACE_CLASSES
                ),
            ),
        ),
    ),
    ATTR_TRACKTYPE := PrimaryAttributeSpec(
        attr_id="tracktype",
        tile_kind="road_surface",
        label="農道・林道の等級",
        geometry="line",
        # 等級は固い路面から柔らかい路面への順序を持つ。
        display_axes=(
            DisplayAxisSpec(
                key="tracktype",
                property="tracktype",
                palette="ordered",
                categories=tuple(
                    _tag_row("tracktype", g.value, g.label, (g.value,), g.description) for g in TRACK_GRADES
                ),
            ),
        ),
    ),
    ATTR_MOTOR_VEHICLE_ACCESS := PrimaryAttributeSpec(attr_id="motor_vehicle_access", label="自動車通行可否", geometry="line"),
    ATTR_LIT := PrimaryAttributeSpec(attr_id="lit", label="街灯", geometry="line"),
    ATTR_TUNNEL := PrimaryAttributeSpec(
        attr_id="tunnel",
        tile_kind="road_surface",
        label="トンネル",
        geometry="line",
        display_axes=(
            DisplayAxisSpec(
                key="tunnel",
                property="tunnel",
                palette="nominal",
                hue_slot=2,
                categories=(
                    DisplayCategorySpec(
                        key="tunnel",
                        label="トンネル",
                        values=(True,),
                        description="トンネルの中を通る区間[OSM の tunnel タグ]。",
                    ),
                ),
            ),
        ),
    ),
    ATTR_ONEWAY := PrimaryAttributeSpec(
        attr_id="oneway",
        tile_kind="road_surface",
        label="一方通行",
        geometry="line",
        display_axes=(
            DisplayAxisSpec(
                key="oneway",
                property="oneway",
                palette="nominal",
                hue_slot=5,
                categories=(
                    DisplayCategorySpec(
                        key="oneway",
                        label="一方通行",
                        values=(True,),
                        description=(
                            "一方向にしか進めない道。環状交差点も含み、自転車だけ両方向に通れる道は含まない"
                            "[OSM の oneway・oneway:bicycle・junction タグ]。"
                        ),
                    ),
                ),
            ),
        ),
    ),
    ATTR_ELEVATION := PrimaryAttributeSpec(attr_id="elevation", label="標高図", geometry="area"),
    ATTR_STOP_POI := PrimaryAttributeSpec(
        attr_id="stop_poi",
        tile_kind="poi",
        label="停止要因",
        geometry="point",
        # 種別は評価へ効く（停止密度の材料になる）が、種別ごとの重みは軸定義が持ち運用で
        # 入れ替わるため、順序を表す評価配色は使わず色相で分ける。
        display_axes=(
            DisplayAxisSpec(
                key="kind",
                property="kind",
                palette="nominal",
                hue_slot=3,
                tone="dark",
                categories=(
                    _kind_row("traffic_signals", "信号", ("traffic_signals",), "信号機。信号付きの横断歩道もここに入る"),
                    _kind_row("crossing", "横断歩道", ("crossing",), "信号の無い横断歩道"),
                    _kind_row("stop", "一時停止", ("stop",), "一時停止の標識がある所"),
                    _kind_row("give_way", "徐行", ("give_way",), "相手に道を譲る（徐行する）標識がある所"),
                    # 車道用と歩道・自転車道用の踏切は、利用者から見れば同じ「線路を渡る点」。
                    _kind_row(
                        "level_crossing",
                        "踏切",
                        ("level_crossing", "railway_crossing"),
                        "線路（路面電車を含む）を渡る所。車道の踏切も歩道・自転車道の踏切も入る",
                    ),
                    _kind_row(
                        "barrier",
                        "車止め・ゲート",
                        ("barrier",),
                        "車止めの柱・ゲート・柵など、道をふさいで止まるか押して通る所",
                    ),
                    _kind_row(
                        "traffic_calming",
                        "ハンプ・狭さく",
                        ("traffic_calming",),
                        "車の速度を落とさせる段差（ハンプ）や道幅の絞り込み",
                    ),
                ),
            ),
        ),
    ),
    ATTR_ACCIDENT_POINT := PrimaryAttributeSpec(
        attr_id="accident_point",
        tile_kind="accident",
        label="事故[警察庁統計]",
        geometry="point",
        # 1つの点に2つの見方がある。色は先頭の軸（当事者）が決め、重大度は大きさで示す
        # ——重大度を色でも表すと当事者の色と取り合う。
        display_axes=(
            DisplayAxisSpec(
                key="party",
                label="当事者",
                property="involves_bicycle",
                palette="nominal",
                hue_slot=0,
                tone="light",
                categories=(
                    # 自転車関連だけが事故密度の材料になる。
                    DisplayCategorySpec(
                        key="bicycle",
                        label="自転車関連",
                        values=(True,),
                        description="当事者に自転車が含まれる事故[警察庁の交通事故統計の当事者種別]。",
                    ),
                    DisplayCategorySpec(
                        key="other",
                        label="その他",
                        values=(False,),
                        description="当事者に自転車が含まれない事故（車どうし・車と歩行者など）。",
                    ),
                ),
            ),
            DisplayAxisSpec(
                key="severity",
                label="重大度",
                property="fatal",
                categories=(
                    DisplayCategorySpec(
                        key="fatal",
                        label="死亡事故",
                        values=(True,),
                        description="死者が1人以上記録された事故[事故後24時間以内の死者。警察庁の交通事故統計の死者数]。",
                        radius_px=6,
                    ),
                    DisplayCategorySpec(
                        key="non_fatal",
                        label="死亡以外",
                        values=(False,),
                        description="死者の記録が無い事故（負傷事故）。",
                        radius_px=3,
                    ),
                ),
            ),
        ),
        point_facts=(PointFactSpec(property="occurred_year", label="発生年"),),
        # 事故は面的に多く、同じ濃さだと停止要因の点が埋もれる。
        point_opacity=0.75,
    ),
    ATTR_INTERSECTION := PrimaryAttributeSpec(attr_id="intersection", label="交差点", geometry="point"),
    ATTR_LANDCOVER := PrimaryAttributeSpec(attr_id="landcover", label="緑と水", geometry="area"),
    PrimaryAttributeSpec(
        attr_id="supply_poi",
        tile_kind="poi",
        label="補給・休憩ポイント",
        geometry="point",
        display_axes=(
            DisplayAxisSpec(
                key="kind",
                property="kind",
                palette="nominal",
                hue_slot=1,
                tone="light",
                categories=(
                    # コンビニだけは OpenStreetMap でなく Overture の地点（立ち寄り先の群「コンビニ」）から出す。
                    DisplayCategorySpec(
                        key="convenience",
                        label="コンビニ",
                        values=(StopPlaceGroup.CONVENIENCE.value,),
                        glyph="bag",
                        description="コンビニのチェーンの店[Overture Maps の地点のコンビニの分類のうち、チェーンの名前に当たるもの]。",
                    ),
                    # 自販機は「ここで飲み物が買える」という約束として読まれる。中身が
                    # 分からないものを同じ確からしさに見せない。
                    DisplayCategorySpec(
                        key="vending_drinks",
                        label="飲料自販機",
                        values=("vending_drinks",),
                        glyph="bottle",
                        description="飲み物か食べ物を売ると書かれた自動販売機[OSM の amenity=vending_machine と vending タグ]。",
                    ),
                    DisplayCategorySpec(
                        key="vending_unknown",
                        label="自販機(中身不明)",
                        values=("vending_unknown",),
                        glyph="question",
                        description="何を売るかが書かれていない自動販売機。飲み物が買えるとは限らない。",
                    ),
                    _kind_row(
                        "toilets",
                        "トイレ",
                        ("toilets",),
                        "公衆トイレなど、地図のデータにトイレとして載っている所",
                        glyph="toilet",
                    ),
                    _kind_row("drinking_water", "給水", ("drinking_water",), "水飲み場など、飲み水をくめる所", glyph="drop"),
                    _kind_row("bicycle_parking", "駐輪場", ("bicycle_parking",), "自転車を止められる所", glyph="parking"),
                ),
            ),
        ),
        # 名前を持つのはコンビニの点だけ（OpenStreetMap の点の名前は焼かない）。
        point_name_property="name",
    ),
    # 群「コンビニ」は補給の点に出すので、ここの行に入れない。
    PrimaryAttributeSpec(
        attr_id="stop_place",
        tile_kind="stop_place",
        label="立ち寄り先",
        geometry="point",
        display_axes=(
            DisplayAxisSpec(
                key="group",
                property="group",
                palette="nominal",
                hue_slot=6,
                tone="vivid",
                categories=(
                    DisplayCategorySpec(
                        key=StopPlaceGroup.EAT_DRINK.value,
                        label="飲食店",
                        values=(StopPlaceGroup.EAT_DRINK.value,),
                        glyph="cup",
                        description="飲食店・カフェ・酒場[Overture Maps の地点の飲食の分類]。",
                    ),
                    DisplayCategorySpec(
                        key=StopPlaceGroup.BATH.value,
                        label="銭湯・温泉",
                        values=(StopPlaceGroup.BATH.value,),
                        glyph="steam",
                        description="銭湯・温泉・サウナ[Overture Maps の地点の分類]。",
                    ),
                    DisplayCategorySpec(
                        key=StopPlaceGroup.BICYCLE.value,
                        label="自転車",
                        values=(StopPlaceGroup.BICYCLE.value,),
                        glyph="wrench",
                        description="自転車の店・修理・貸し自転車[Overture Maps の地点の分類]。",
                    ),
                    DisplayCategorySpec(
                        key=StopPlaceGroup.SCENIC.value,
                        label="景色・名所",
                        values=(StopPlaceGroup.SCENIC.value,),
                        glyph="mountain",
                        description="公園・庭園・湖・滝・山・浜・城・展望台・博物館の類[Overture Maps の地点の分類]。",
                    ),
                    DisplayCategorySpec(
                        key=StopPlaceGroup.LODGING.value,
                        label="宿",
                        values=(StopPlaceGroup.LODGING.value,),
                        glyph="bed",
                        description="ホテル・旅館・民宿・キャンプ場の類[Overture Maps の地点の分類]。",
                    ),
                    DisplayCategorySpec(
                        key=StopPlaceGroup.TEMPLE_SHRINE.value,
                        label="寺社",
                        values=(StopPlaceGroup.TEMPLE_SHRINE.value,),
                        glyph="gate",
                        description="国の指定・登録の文化財の建造物を持つ寺社[文化遺産オンライン]。",
                    ),
                ),
            ),
        ),
        # 街中は飲食店で埋まるので、地点の少ない群から残す（並びは都内の件数の少ない順）。
        point_thinning=PointThinningSpec(
            rows=(
                StopPlaceGroup.TEMPLE_SHRINE.value,
                StopPlaceGroup.BATH.value,
                StopPlaceGroup.BICYCLE.value,
                StopPlaceGroup.LODGING.value,
                StopPlaceGroup.SCENIC.value,
                StopPlaceGroup.EAT_DRINK.value,
            ),
            ratio_property="confidence",
        ),
        point_name_property="name",
    ),
)
# 読む側はidで1件を引く（`next(...)`）ため、同じidを2度宣言すると後の宣言が黙って消える。
_REPEATED_ATTR_IDS = sorted(attr_id for attr_id, n in Counter(a.attr_id for a in PRIMARY_ATTRIBUTES).items() if n > 1)
if _REPEATED_ATTR_IDS:
    raise ValueError(f"primary attribute declared more than once: {_REPEATED_ATTR_IDS}")


def stop_poi_map_group_sql(alias: str) -> str:
    """地図の停止要因の点を近いものどうしまとめる単位を返すSQL式（`node_materials`の別名`alias`）。

    単位は凡例の行で、数える種別（`COUNT_KIND_OF`）ではない。地図の点は「そこに何があるか」を
    示すため、凡例で分けて見せている種別（例: 車止めとハンプ・狭さく）は近くても別の点のまま
    出し、評価では1回と数える。凡例で同じ行に入る種別は地図で見分けられないので1点にまとめる。
    凡例の行に無い種別（補給休憩）は種別そのままを返す。
    """
    kind = stop_kind_sql(alias)
    row_of = {
        value: category.key
        for category in ATTR_STOP_POI.display_axes[0].categories
        for value in category.values
        if isinstance(value, str)
    }
    return kind_map_sql(kind, row_of, otherwise=kind)
