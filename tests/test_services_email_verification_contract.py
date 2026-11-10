import pathlib
import re

import yaml
from graphql import build_schema, parse, validate

from src import proxy

ROOT = pathlib.Path(__file__).resolve().parents[2]
SDL = ROOT / "bgg-shop-core" / "specs" / "schema.graphql"
SPEC = pathlib.Path(__file__).resolve().parents[1] / "specs" / "openapi.yaml"
PREFIX = "/api/v1/auth/email-verification/"


def _documents():
    import inspect
    source = inspect.getsource(proxy)
    return re.findall(r'"""\n(\s*(?:mutation|query)\s+(?:Register|ConfirmEmailVerification|ResendEmailVerification|Login)\b.*?)"""', source, re.S)


def test_bff_documents_validate_against_canonical_core_sdl():
    schema = build_schema(SDL.read_text(encoding="utf-8"))
    documents = _documents()
    assert len(documents) == 4
    for document in documents:
        assert validate(schema, parse(document)) == []


def test_openapi_documents_canonical_verification_contract():
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    paths = spec["paths"]
    assert list(paths[PREFIX + "confirm"]) == ["post"]
    assert list(paths[PREFIX + "resend"]) == ["post"]
    assert set(paths[PREFIX + "confirm"]["post"]["responses"]) == {"200", "400", "405", "429", "502", "503"}
    assert set(paths[PREFIX + "resend"]["post"]["responses"]) == {"202", "400", "405", "429", "502", "503"}
    assert "403" in paths["/api/v1/auth/login"]["post"]["responses"]
    token = spec["components"]["schemas"]["ConfirmEmailVerificationRequest"]["properties"]["token"]
    assert re.fullmatch(token["pattern"], "A" * 43)
    assert proxy.VERIFICATION_TOKEN_PATTERN.pattern.replace("\\A", "^").replace("\\Z", "$") == token["pattern"]


def test_feature_local_contract_drafts_are_removed():
    contracts = ROOT / "specs" / "016-email-verification" / "contracts"
    assert sorted(p.name for p in contracts.iterdir()) == ["README.md"]
