import pathlib
import re

import pytest
import yaml

from src.proxy import has_required_registration_password_composition


PASSWORD_VECTORS = [
    ("Abcdef1!", True),
    ("abcdef1!", False),
    ("ABCDEF1!", False),
    ("Abcdefg!", False),
    ("Abcdefg1", False),
    ("Abcdefg1 ", False),
    ("Abcdefg1\t", False),
    ("Abcdefg1\n", False),
    ("Ábcdef1!", False),
    ("ABCDEF1!ñ", False),
    ("Abcdefg!١", False),
    ("Abcdef1😀", False),
    (" Abcdef1! ", True),
    ("Abcdef1!\né", True),
]


@pytest.mark.parametrize(("password", "expected"), PASSWORD_VECTORS)
def test_registration_password_categories_use_ascii_and_preserve_other_characters(password, expected):
    assert has_required_registration_password_composition(password) is expected


def test_openapi_registration_password_pattern_matches_bff_validation():
    spec_path = pathlib.Path(__file__).resolve().parents[1] / "specs" / "openapi.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    register_password = schemas["RegisterRequest"]["properties"]["password"]
    register_pattern = register_password["pattern"]
    assert "pattern" not in schemas["LoginRequest"]["properties"]["password"]
    assert "ASCII uppercase" in register_password["description"]
    assert "not whitespace" in register_password["description"]
    pattern = re.compile(register_pattern)

    for password, expected in PASSWORD_VECTORS:
        assert bool(pattern.search(password)) is expected
        assert has_required_registration_password_composition(password) is expected
