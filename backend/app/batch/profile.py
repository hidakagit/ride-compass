"""PBF取込プロファイル（YAML）の読み込みとタグマッチング（docs/osm-pbf-import.md 5.2節）。

取込対象の要素を宣言的に指定する。「wayをosm_raw_waysへ取り込む」に加え、静的道路属性P1
（docs/static-road-attributes-plan.md）で「nodeをosm_raw_poisへ取り込む」を追加した。
将来の拡張も同じく「エントリ追加＋対応するelement_type/targetのwriter実装」で行う
（取込コアはこのプロファイル語彙のまま変えない）。matchはANDマッチのみのため、
複数タグキーのOR条件（例: highway=*またはrailway=level_crossing）は複数ルールに分けて
表現する（同じtargetへ複数ルールが書き込むのは想定内、matching_ruleは最初に一致した
ルールを返す）。
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

SUPPORTED_VERSION = 1
SUPPORTED_ELEMENT_TYPES = {"way", "node"}
SUPPORTED_TARGETS = {"osm_raw_ways", "osm_raw_pois"}


class ProfileError(ValueError):
    """プロファイルの形式不正（未対応のelement_type/target・必須キー欠如等）。"""


@dataclass(frozen=True)
class ElementRule:
    name: str
    element_type: str
    # タグ名 -> "*"（存在のみ要求）または許容値のリスト。複数キーはANDマッチ。
    match: dict[str, list[str] | str]
    target: str


@dataclass(frozen=True)
class ImportProfile:
    version: int
    rules: tuple[ElementRule, ...]
    # プロファイルファイル全体のSHA-256。osm_import_runsに記録し「どの設定で
    # 取り込んだデータか」を後から追跡できるようにする。
    profile_hash: str


def _normalize_match(name: str, raw_match: object) -> dict[str, list[str] | str]:
    if not isinstance(raw_match, dict) or not raw_match:
        raise ProfileError(f"elements[{name}]: matchはタグ名→値の空でない辞書が必要です")
    normalized: dict[str, list[str] | str] = {}
    for tag, value in raw_match.items():
        if value == "*":
            normalized[str(tag)] = "*"
        elif isinstance(value, str):
            normalized[str(tag)] = [value]
        elif isinstance(value, list) and value and all(isinstance(v, str) for v in value):
            normalized[str(tag)] = list(value)
        else:
            raise ProfileError(
                f"elements[{name}]: match.{tag}は\"*\"・文字列・文字列リストのいずれかが必要です"
            )
    return normalized


def load_profile(path: str | Path) -> ImportProfile:
    raw_bytes = Path(path).read_bytes()
    data = yaml.safe_load(raw_bytes)
    if not isinstance(data, dict):
        raise ProfileError("プロファイルのトップレベルは辞書が必要です")
    if data.get("version") != SUPPORTED_VERSION:
        raise ProfileError(f"未対応のプロファイルversionです: {data.get('version')!r}")

    raw_elements = data.get("elements")
    if not isinstance(raw_elements, list) or not raw_elements:
        raise ProfileError("elementsは空でないリストが必要です")

    rules = []
    for raw in raw_elements:
        name = str(raw.get("name", f"#{len(rules)}"))
        element_type = raw.get("element_type")
        if element_type not in SUPPORTED_ELEMENT_TYPES:
            raise ProfileError(f"elements[{name}]: 未対応のelement_typeです: {element_type!r}")
        target = raw.get("target")
        if target not in SUPPORTED_TARGETS:
            raise ProfileError(f"elements[{name}]: 未対応のtargetです: {target!r}")
        rules.append(
            ElementRule(
                name=name,
                element_type=element_type,
                match=_normalize_match(name, raw.get("match")),
                target=target,
            )
        )

    return ImportProfile(
        version=SUPPORTED_VERSION,
        rules=tuple(rules),
        profile_hash=hashlib.sha256(raw_bytes).hexdigest(),
    )


def rule_matches(rule: ElementRule, tags: dict[str, str]) -> bool:
    """要素のタグ辞書がルールのmatch条件（ANDマッチ）を満たすか。"""
    for tag, allowed in rule.match.items():
        value = tags.get(tag)
        if value is None:
            return False
        if allowed != "*" and value not in allowed:
            return False
    return True


def matching_rule(profile: ImportProfile, element_type: str, tags: dict[str, str]) -> ElementRule | None:
    """element_typeとタグにマッチする最初のルールを返す（無ければNone＝取込対象外）。"""
    for rule in profile.rules:
        if rule.element_type == element_type and rule_matches(rule, tags):
            return rule
    return None
