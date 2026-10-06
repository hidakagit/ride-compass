"""キャッシュ鍵の組み立て（方針は docs/conventions/caching.md）。

署名はSHA-1の先頭12桁。鍵はタイルURLとディスクのディレクトリ名へ入るため、衝突耐性より
パス長を優先している（形の変化を見分けるのが目的で、暗号的な強度は要らない）。
"""

import dataclasses
import hashlib
from pathlib import Path

from app.domain.landcover import LANDCOVER_CLASSES
from app.infrastructure.derived_data_meta import DataRevisions

# 土地被覆ラスタタイル。同じ配色のまま、元のGeoTIFFを別の年次・別の版へ差し替えたときと、
# ラスタの読み方・描き方（`landcover_raster.py`）を変えたときに上げる（画素が変わるのに
# URLもディスクキャッシュの鍵も変わらないため）。
LANDCOVER_REVISION = "2"

def bound_values(source: object) -> list[tuple[str, str]]:
    """SQLのバインドパラメータのうち、定義時点で値が決まっているもの（名前と値）。

    実行時に値を渡すパラメータ（タイル座標等）はこの時点で値を持たない。
    """
    bindparams = getattr(source, "_bindparams", None)
    if not bindparams:
        return []
    return sorted(
        (name, repr(param.value)) for name, param in bindparams.items() if param.value is not None
    )


def shape_digest(*sources: object) -> str:
    """形の署名。dataclassは列名の並び、それ以外は文字列化した内容とバインド済みの値で決まる。

    dataclassを列名で署名するのは、道路網の置き場（`road_network_store.py`）が列ごとの
    ファイルを列名で読み書きするため。列を足す・消す・改名したコードが古い置き場を選ぶと、
    足した列のファイルが無いまま読みに行く。
    """
    parts = []
    for source in sources:
        if dataclasses.is_dataclass(source):
            parts.append(",".join(f.name for f in dataclasses.fields(source)))
            continue
        parts.append(str(source))
        parts.append(repr(bound_values(source)))
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:12]


def cache_identity(revision: str, *shape_sources: object) -> str:
    """`<リビジョン>-<形の署名>`。タイルURL・ディスクパスへそのまま入れる。"""
    return f"{revision}-{shape_digest(*shape_sources)}"


#: DBの世代を読めないときに使う印。**この値のタイルをディスクへ残さない**——世代が
#: 分からないまま焼いたタイルは、後で世代が判明しても古いと判定できない。
UNKNOWN_REVISION = "x"


def tile_version(revisions: DataRevisions | None, shape: str) -> str:
    """配信するタイルの世代。`<派生の世代>.<生データの世代>-<形の署名>`。

    `revisions`は`derived_data_meta.get_revisions()`の値。Noneはまだ読めていない状態で、
    派生の世代の行が無いDBと同じく`UNKNOWN_REVISION`を使う。
    """
    if revisions is None or revisions.derived is None:
        return f"{UNKNOWN_REVISION}-{shape}"
    return f"{revisions.derived}.{revisions.imported}-{shape}"


def is_known_tile_version(version: str) -> bool:
    """`tile_version`が世代を読めて組んだものか。違えばディスクへ残さない。"""
    return not version.startswith(f"{UNKNOWN_REVISION}-")


#: 土地被覆ラスタタイルのURLへ入る世代（配色・クラス構成と手書きリビジョンから決まる）。
#:
#: **どのラスタを開いているかはここへ入れられない**。この値は生成物
#: （`region-tile-config.json`）を通してフロントのURLへ焼き込まれ、生成はビルド機で行う
#: ——ラスタの置き場所は環境変数（`LULC_RASTER_PATHS`）で環境ごとに違うため、入れると
#: 生成物がビルド機の設定で決まり、本番の実際の構成とずれる。**実際に開けている**ラスタ
#: 構成への追随はサーバー側のディスクの鍵（`region_tile_cache.py: landcover_generation`）で行い、
#: ブラウザ側は`cache_policy.py`が`immutable`を付けないことで再検証できるようにしてある。
LANDCOVER_TILE_VERSION = cache_identity(LANDCOVER_REVISION, LANDCOVER_CLASSES)


def raster_set_fingerprint(raster_paths: list[str]) -> str:
    """ラスタ構成の指紋（ファイル名の集合から決まる短い文字列）。

    土地被覆の派生物は、どのラスタを開いていたかに従属する。「値なし」はその構成で
    そう確定したという意味しか持たず、ラスタを1枚足せば境界またぎ・範囲外だった場所は
    値を持ちうる。指紋を派生物の鍵へ入れておけば、構成が変わった時点で古い結果が
    使われなくなる。順序には依存させない（同じ集合をどの順で渡しても同じ指紋になる）。
    """
    joined = "\n".join(sorted(Path(path).name for path in raster_paths))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


#: 地域タイルのディスクの鍵の頭。同じ置き場に同居する基礎地図・地理院のタイル（配信元のパスが鍵）と分ける。
_REGION_TILE_KEY_ROOT = "region/"


def region_tile_generation_prefix(kind: str, generation: str) -> str:
    """地域タイルの1つの系統・1つの世代のディスクの鍵が共通に持つ頭。旧世代の掃除はこれで見分ける。"""
    return f"{_REGION_TILE_KEY_ROOT}{kind}/v{generation}/"


def region_tile_kind(key: str) -> str | None:
    """ディスクの鍵が地域タイルなら、その系統。地域タイルでない鍵はNone。"""
    if not key.startswith(_REGION_TILE_KEY_ROOT):
        return None
    return key[len(_REGION_TILE_KEY_ROOT):].split("/", 1)[0]


def region_tile_key(kind: str, generation: str, z: int, x: int, y: int, extension: str) -> str:
    """地域タイル1枚のディスクの鍵。世代はURLへ入る世代と同じ文字列から組む。"""
    return f"{region_tile_generation_prefix(kind, generation)}{z}/{x}/{y}.{extension}"
