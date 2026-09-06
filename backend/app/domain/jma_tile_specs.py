"""気象庁タイル配信のズーム仕様レジストリ。

配信元（気象庁の各`*.properties__<hash>.xml`）は要素ごとに`zoomUse`（使用するズームの
偶奇）と`maxNativeZoom`（XML中のコメントで「画像が実在する最大ズームレベル」と説明されて
いる値）を持つ。アプリがタイルを要求してよい最大ズームはこの2つの組み合わせで決まり、
どちらか一方だけを見ると実データの無いズームを指してしまう。

MapLibreの`maxzoom`（frontend: `MapView.tsx: DYNAMIC_WEATHER_RENDERERS`）と
プリウォームバッチの対象ズーム（`services/jma_tile_prewarm_service.py`）は、いずれも
`effective_max_zoom()`でこの1箇所から導く。値を手で書き写すと配信元との突き合わせを
誤る（実際に7要素中6要素で誤っていた、[T633](../../../docs/tasks/T633.md)）。

frontendへは`scripts/export_openapi.py`が`jma-tile-config.json`として書き出す。
"""

from dataclasses import dataclass
from typing import Literal

#: 配信元がタイルを生成するズームの偶奇。`"all"`は偶奇の制約が無いことを表す。
ZoomUse = Literal["even", "odd", "all"]


@dataclass(frozen=True)
class JmaTileSpec:
    """1要素分の配信元ズーム仕様。"""

    #: タイルパス中の要素id（`.../surf/<element_id>/{z}/{x}/{y}.png`）。
    element_id: str
    zoom_use: ZoomUse
    max_native_zoom: int
    min_zoom: int = 4
    #: 配信元の`properties.xml`で`zoom_use`・`max_native_zoom`の両方を直接確認できたか。
    #: Falseの要素は実測と近縁要素からの推定を含むため、扱いを変える場合はここを見る。
    verified: bool = True


def effective_max_zoom(spec: JmaTileSpec) -> int:
    """実データが存在する最大ズーム。

    `zoom_use`が偶数/奇数のみの場合、`max_native_zoom`がその偶奇に合わないと、その
    ズームのタイルは存在せず空タイルが返る。合う側へ1段下げた値が実際の上限になる。
    """
    z = spec.max_native_zoom
    if spec.zoom_use == "even":
        return z if z % 2 == 0 else z - 1
    if spec.zoom_use == "odd":
        return z if z % 2 == 1 else z - 1
    return z


# 出典は各要素を表示する公式ページが読み込む設定ファイル:
#   キキクル4種 … `bosai/risk/table/risk.properties__<hash>.xml`
#   降水/雷/竜巻 … `bosai/nowc/table/nowc.properties__<hash>.xml`
JMA_TILE_SPECS: dict[str, JmaTileSpec] = {
    # キキクル（危険度分布）。土砂・大雨・浸水はラスタ、洪水はベクタ（.pbf）。
    "land": JmaTileSpec("land", "even", 11),
    "rain_mesh": JmaTileSpec("rain_mesh", "even", 11),
    "inund": JmaTileSpec("inund", "even", 11),
    # floodは`zoomUse="even"`を持つが`maxNativeZoom`の記載が無い。同じrisk系の他3要素と
    # 同じ11として扱う——z10に実データがありz11・z12が空という実測とも一致する。
    "flood": JmaTileSpec("flood", "even", 11),
    # 降水ナウキャスト。
    "hrpns": JmaTileSpec("hrpns", "even", 10),
    # 雷・竜巻ナウキャストはmaxNativeZoomが9で、他のJMAタイルより1段粗い。
    "thns": JmaTileSpec("thns", "even", 9),
    "trns": JmaTileSpec("trns", "even", 9),
    # 線状降水帯予測マップ。公式ページ（軽量版）が設定ファイルを外部化しておらず、
    # `zoomUse`・`maxNativeZoom`を一次情報で確認できていない。同じrasrf/nowc系の
    # `hrpns`と同じ値を暫定的に置く。
    "sjfcstmap": JmaTileSpec("sjfcstmap", "even", 10, verified=False),
}


def max_zoom_for(element_id: str) -> int | None:
    """要素idに対する実データ上限ズーム。未登録の要素はNone。"""
    spec = JMA_TILE_SPECS.get(element_id)
    return effective_max_zoom(spec) if spec is not None else None


def has_native_tile(spec: JmaTileSpec, zoom: int) -> bool:
    """そのズームに配信元の実データが存在するか。

    `zoom_use`の偶奇に合わないズームは、配信元が200を返しても中身は空タイルになる。
    """
    if zoom < spec.min_zoom or zoom > effective_max_zoom(spec):
        return False
    if spec.zoom_use == "even":
        return zoom % 2 == 0
    if spec.zoom_use == "odd":
        return zoom % 2 == 1
    return True


def source_zoom_for_interpolation(element_id: str, zoom: int) -> int | None:
    """`zoom`のタイルを補間するために取得すべき親ズーム。補間が不要／不可能ならNone。

    `zoom_use`が偶奇を限る要素では、実データを持つズームが1つおきに並ぶため、親は常に
    `zoom - 1`（そこは必ず反対の偶奇になる）。親が`min_zoom`を下回る場合は補間できない
    （拡大の元が無い）。上限を超えるズームはMapLibre側のoverzoomが担うため対象外。
    """
    spec = JMA_TILE_SPECS.get(element_id)
    if spec is None or spec.zoom_use == "all":
        return None
    if zoom > effective_max_zoom(spec) or zoom < spec.min_zoom:
        return None
    if has_native_tile(spec, zoom):
        return None
    parent = zoom - 1
    return parent if parent >= spec.min_zoom else None
