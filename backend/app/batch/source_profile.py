"""外部ソースの取込プロファイル（YAML）の読み込み。

**取り込む母集団の宣言はプロファイルだけが持つ**。実装には範囲を書かない——範囲を
広げるときに直す場所が1つになり、適用した内容をそのまま`source_runs.profile`へ
記録できる。

対象範囲（`target`）はソース共通で、全ソースがそれを使う。範囲は緯度経度の枠
（`target.bbox`）だけで決まる。

**書いた欄は必ず効く**。どの段（ファイル全体・`target`・各ソース・その`rows`/`grid`）でも、
読む側が知らない欄があれば取込を始める前に止め、その場所と名前を名指しする。知っている欄は
読む側の宣言（dataclassのフィールド）そのもので、ソースごとの`rows`/`grid`はアダプタが
`register_adapter`で型を宣言する。欄を足すときは、読む側のフィールドを1つ足す。
"""

import hashlib
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

_SUPPORTED_VERSION = 1

_PROFILE_PATH = Path(__file__).resolve().parent / "source_profile.yaml"

#: フィールドのmetadataのキー。Falseなら、そのフィールドはファイルに書く欄ではなく読み込みが作る値。
_IN_FILE = "in_file"


class SourceProfileError(ValueError):
    """プロファイルの形式不正（未対応のversion・必須キー欠如・知らない欄・型違い）。"""


@dataclass(frozen=True)
class NoFields:
    """欄を1つも持たない`rows`/`grid`。アダプタが型を宣言しなかった側に当たる。"""


@dataclass(frozen=True)
class Target:
    """全ソース共通の対象範囲。"""

    #: (min_lat, min_lon, max_lat, max_lon)。
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class SourceSpec:
    """1ソースぶんの宣言。

    `adapter`が外部の形を読む実装を指す。run記録とパーティションの選択は取込の
    共通経路が持つ。
    """

    name: str
    adapter: str
    #: 行の絞り込み。型はアダプタが宣言する（`register_adapter`の`rows`）。
    rows: Any
    #: ラスタ・タイル系の格子の指定。型はアダプタが宣言する（`register_adapter`の`grid`）。
    grid: Any


@dataclass(frozen=True)
class SourceProfile:
    version: int
    target: Target
    sources: tuple[SourceSpec, ...]
    #: ファイル全体のSHA-256。`source_runs`へ記録し、どの宣言で取り込んだ行かを追える。
    profile_hash: str = field(metadata={_IN_FILE: False})

    def source(self, name: str) -> SourceSpec:
        for spec in self.sources:
            if spec.name == name:
                return spec
        raise SourceProfileError(f"プロファイルに '{name}' がありません")


def _file_fields(cls: type) -> dict[str, Any]:
    return {f.name: f for f in fields(cls) if f.metadata.get(_IN_FILE, True)}


def _reject_unknown(raw: dict[str, Any], cls: type, where: str) -> None:
    known = _file_fields(cls)
    unknown = sorted(str(key) for key in raw if key not in known)
    if unknown:
        raise SourceProfileError(
            f"{where} に知らない欄があります: {unknown}（読む欄: {sorted(known)}）")


def _parse_section(cls: type, raw: object, where: str) -> Any:
    """アダプタが宣言した型へ、`rows`/`grid`の中身を当てはめる。"""
    if not isinstance(raw, dict):
        raise SourceProfileError(f"{where} はマッピングが必要です")
    _reject_unknown(raw, cls, where)
    missing = sorted(
        name for name, f in _file_fields(cls).items()
        if f.default is MISSING and f.default_factory is MISSING and name not in raw
    )
    if missing:
        raise SourceProfileError(f"{where} に欄が足りません: {missing}")
    return cls(**raw)


def _parse_target(raw: object) -> Target:
    if not isinstance(raw, dict):
        raise SourceProfileError("target はマッピングが必要です")
    _reject_unknown(raw, Target, "target")
    bbox_raw = raw.get("bbox")
    if not (isinstance(bbox_raw, list) and len(bbox_raw) == 4):
        raise SourceProfileError("target.bbox は4つの数（min_lat, min_lon, max_lat, max_lon）が必要です")
    bbox = tuple(float(v) for v in bbox_raw)
    if not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        raise SourceProfileError("target.bbox は min < max である必要があります")
    return Target(bbox=bbox)  # type: ignore[arg-type]


def _parse_source(raw: object, adapters: dict[str, Any]) -> SourceSpec:
    if not isinstance(raw, dict):
        raise SourceProfileError("sources の各要素はマッピングが必要です")
    name = raw.get("name")
    adapter = raw.get("adapter")
    if not isinstance(name, str) or not name:
        raise SourceProfileError("sources[].name が必要です")
    _reject_unknown(raw, SourceSpec, f"sources[{name}]")
    if not isinstance(adapter, str) or not adapter:
        raise SourceProfileError(f"sources[{name}].adapter が必要です")
    entry = adapters.get(adapter)
    if entry is None:
        raise SourceProfileError(
            f"sources[{name}].adapter が未登録です: {adapter}（登録済み: {sorted(adapters)}）")

    return SourceSpec(
        name=name,
        adapter=adapter,
        rows=_parse_section(entry.rows, raw.get("rows", {}), f"sources[{name}].rows"),
        grid=_parse_section(entry.grid, raw.get("grid", {}), f"sources[{name}].grid"),
    )


def _registered_adapters() -> dict[str, Any]:
    """登録済みのアダプタ。アダプタはimportされたときに自分を登録する。

    取込の共通経路（`ingest.py`）とアダプタがこのモジュールをimportするため、関数の中でimportする。
    """
    from app.batch import source_adapters  # noqa: F401
    from app.batch.ingest import ADAPTERS

    return ADAPTERS


def load_source_profile(path: Path | None = None) -> SourceProfile:
    """プロファイルを読む。形式不正は`SourceProfileError`で即座に落とす。"""
    target_path = path or _PROFILE_PATH
    text = target_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise SourceProfileError("プロファイルはマッピングが必要です")
    _reject_unknown(raw, SourceProfile, "プロファイルの最上位")

    version = raw.get("version")
    if version != _SUPPORTED_VERSION:
        raise SourceProfileError(f"未対応のversionです: {version}（対応は{_SUPPORTED_VERSION}）")

    sources_raw = raw.get("sources")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise SourceProfileError("sources は空でないリストが必要です")
    adapters = _registered_adapters()
    sources = tuple(_parse_source(s, adapters) for s in sources_raw)

    names = [s.name for s in sources]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise SourceProfileError(f"sources[].name が重複しています: {duplicated}")

    return SourceProfile(
        version=version,
        target=_parse_target(raw.get("target")),
        sources=sources,
        profile_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
