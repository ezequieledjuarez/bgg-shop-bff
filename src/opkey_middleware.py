import requests
import os
from flask import request, g

def validate_op_key_with_core(raw_key, path, method):
    core_base = os.getenv("SALEOR_BASE_URL", "http://localhost:8000")
    url = f"{core_base}/internal/op-validate"
    internal_secret = os.getenv("OPKEY_INTERNAL_SECRET", "")
    if len(internal_secret.encode("utf-8")) < 32:
        return None
    try:
        r = requests.post(
            url,
            json={"op_key": raw_key, "path": path, "method": method},
            headers={"X-Internal-Secret": internal_secret},
            timeout=3,
            allow_redirects=False,
        )
        if r.status_code != 200:
            return None
        result = r.json()
        if not isinstance(result, dict) or type(result.get("valid")) is not bool:
            return None
        return result
    except Exception:
        return None


def init_app(app):
    @app.before_request
    def _opkey_before_request():
        raw_key = request.headers.get("X-Op-Key") or request.headers.get("X-Op-Key".lower())
        if not raw_key:
            return
        res = validate_op_key_with_core(raw_key, request.path, request.method)
        if res is None:
            g.op_session = {"valid": False}
            g.op_session_valid = False
            g.op_session_validation_failed = True
            return
        g.op_session = res
        g.op_session_valid = bool(res.get("valid"))
