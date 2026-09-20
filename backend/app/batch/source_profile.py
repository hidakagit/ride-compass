"""外部ソースの取込プロファイル（YAML）の読み込み。

**取り込む母集団の宣言はプロファイルだけが持つ**。実装には範囲を書かない——範囲を
広げるときに直す場所が1つになり、適用した内容をそのまま`source_runs.profile`へ
記録できる。

対象範囲（`target`）はソース共通で、`from_target`と書いたソースがそれを引き継ぐ。
都道府県はJIS X 0401（国の標準）で書き、ソースごとの採番への変換はアダプタが持つ。
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_VERSION = 1

#: 対象範囲を`target`から引き継ぐことを表す値。
FROM_TARGET = "from_target"

PROFILE_PATH = Path(__file__).resolve().parent / "source_profile.yaml"


class SourceProfileError(ValueError):
    """プロファイルの形式不正（未対応のversion・必須キー欠如・型違い）。"""


@dataclass(frozen=True)
class Target:
    """全ソース共通の対象範囲。"""

    #: JIS X 0401の都道府県コード。全国は`None`（`all`と書いたとき）。
    prefectures: tuple[str, ...] | None
    #: (min_lat, min_lon, max_lat, max_lon)。
    bbox: tuple[float, float, float, float]

    def is_nationwide(self) -> bool:
        return self.prefectures is None


@dataclass(frozen=True)
class SourceSpec:
    """1ソースぶんの宣言。

    `adapter`が外部の形を読む実装を指す。それ以外（絞り込みの適用・run記録・
    パーティションの選択）は取込の共通経路が持つ。
    """

    name: str
    adapter: str
    #: 行の絞り込み。中身はアダプタが解釈する。
    rows: dict[str, Any]
    #: ラスタ・タイル系の格子の指定。ベクタのソースは空。
    grid: dict[str, Any]
    #: 列の絞り込み。`"all"`以外は今のところ使わない。
    columns: str
    #: タグの絞り込み。`"all"`以外は今のところ使わない。
    tags: str


@dataclass(frozen=True)
class SourceProfile:
    version: int
    target: Target
    sources: tuple[SourceSpec, ...]
    #: ファイル全体のSHA-256。`source_runs`へ記録し、どの宣言で取り込んだ行かを追える。
    profile_hash: str
    #: 記録用の生データ（`source_runs.profile`へそのまま入れる）。
    raw: dict[str, Any]

    def source(self, name: str) -> SourceSpec:
        for spec in self.sources:
            if spec.name == name:
                return spec
        raise SourceProfileError(f"プロファイルに '{name}' がありません")


def _parse_target(raw: object) -> Target:
    if not isinstance(raw, dict):
        raise SourceProfileError("target はマッピングが必要です")
    prefectures_raw = raw.get("prefectures")
    if prefectures_raw == "all":
        prefectures: tuple[str, ...] | None = None
    elif isinstance(prefectures_raw, list) and prefectures_raw:
        prefectures = tuple(str(p) for p in prefectures_raw)
    else:
        raise SourceProfileError('target.prefectures は "all" か空でないリストが必要です')

    bbox_raw = raw.get("bbox")
    if not (isinstance(bbox_raw, list) and len(bbox_raw) == 4):
        raise SourceProfileError("target.bbox は4つの数（min_lat, min_lon, max_lat, max_lon）が必要です")
    bbox = tuple(float(v) for v in bbox_raw)
    if not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        raise SourceProfileError("target.bbox は min < max である必要があります")
    return Target(prefectures=prefectures, bbox=bbox)  # type: ignore[arg-type]


def _parse_source(raw: object) -> SourceSpec:
    if not isinstance(raw, dict):
        raise SourceProfileError("sources の各要素はマッピングが必要です")
    name = raw.get("name")
    adapter = raw.get("adapter")
    if not isinstance(name, str) or not name:
        raise SourceProfileError("sources[].name が必要です")
    if not isinstance(adapter, str) or not adapter:
        raise SourceProfileError(f"sources[{name}].adapter が必要です")

    rows = raw.get("rows", {})
    if isinstance(rows, str):
        rows = {"mode": rows}
    if not isinstance(rows, dict):
        raise SourceProfileError(f"sources[{name}].rows はマッピングか文字列が必要です")

    grid = raw.get("grid", {})
    if not isinstance(grid, dict):
        raise SourceProfileError(f"sources[{name}].grid はマッピングが必要です")

    return SourceSpec(
        name=name,
        adapter=adapter,
        rows=rows,
        grid=grid,
        columns=str(raw.get("columns", "all")),
        tags=str(raw.get("tags", "all")),
    )


def load_source_profile(path: Path | None = None) -> SourceProfile:
    """プロファイルを読む。形式不正は`SourceProfileError`で即座に落とす。"""
    target_path = path or PROFILE_PATH
    text = target_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise SourceProfileError("プロファイルはマッピングが必要です")

    version = raw.get("version")
    if version != SUPPORTED_VERSION:
        raise SourceProfileError(f"未対応のversionです: {version}（対応は{SUPPORTED_VERSION}）")

    sources_raw = raw.get("sources")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise SourceProfileError("sources は空でないリストが必要です")
    sources = tuple(_parse_source(s) for s in sources_raw)

    names = [s.name for s in sources]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise SourceProfileError(f"sources[].name が重複しています: {duplicated}")

    return SourceProfile(
        version=version,
        target=_parse_target(raw.get("target")),
        sources=sources,
        profile_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        raw=raw,
    )
