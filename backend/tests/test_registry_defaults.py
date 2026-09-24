"""`domain/registry_defaults.py`——ビルド時生成物のために一次属性の語彙を1回だけ埋める。

ここで見るのは**何を登録し、何を拒むか**。
"""

from contextlib import contextmanager

import pytest

from app.domain import registry_defaults
from app.domain.registry import (
    PrimaryAttributeSpec,
    reset_registry_for_testing,
)
from app.domain.registry_defaults import register_defaults


@contextmanager
def _empty_registry():
    reset_registry_for_testing()
    try:
        yield
    finally:
        reset_registry_for_testing()


@contextmanager
def _vocabulary(labels: dict[str, str]):
    """一次属性の語彙を差し替える。"""
    saved = registry_defaults.PRIMARY_ATTRIBUTES
    registry_defaults.PRIMARY_ATTRIBUTES = tuple(
        PrimaryAttributeSpec(attr_id=attr_id, label=label, geometry="line") for attr_id, label in labels.items()
    )
    try:
        yield
    finally:
        registry_defaults.PRIMARY_ATTRIBUTES = saved


class TestWhatGetsRegistered:
    def test_calling_it_twice_is_rejected(self):
        """レジストリは大域の状態。二重に埋めると、どちらの内容か分からなくなる。"""
        with _empty_registry():
            with _vocabulary({"known": "既知"}):
                register_defaults()

                with pytest.raises(ValueError):
                    register_defaults()


class TestAgainstTheRealDeclarations:
    def test_the_real_declarations_register_without_conflict(self):
        """差し替えずに実際の宣言で通す。`register_defaults`が弾くもの——同じ一次属性の
        二重の宣言——は、**この呼び出しが成功すること**で確かめられる。
        個別の性質を並べ直しても、同じことの言い換えにしかならない。
        """
        reset_registry_for_testing()
        try:
            register_defaults()
        finally:
            reset_registry_for_testing()
