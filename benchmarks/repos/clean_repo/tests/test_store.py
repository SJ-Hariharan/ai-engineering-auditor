import pytest

from inventory_pkg import Item, Store
from inventory_pkg.pricing import apply_discount


def test_add_and_get():
    s = Store()
    s.add(Item("a", "Apple", 2, 100))
    assert s.get("a").name == "Apple"


def test_negative_quantity_rejected():
    with pytest.raises(ValueError):
        Store().add(Item("a", "Apple", -1, 100))


def test_total_with_discount():
    s = Store()
    s.add(Item("a", "Apple", 2, 100))
    assert s.total_value(50) == 100


def test_discount_bounds():
    with pytest.raises(ValueError):
        apply_discount(100, 101)


def test_save_load(tmp_path):
    s = Store()
    s.add(Item("a", "Apple", 2, 100))
    p = tmp_path / "x.json"
    s.save(p)
    t = Store()
    t.load(p)
    assert t.get("a") == s.get("a")
