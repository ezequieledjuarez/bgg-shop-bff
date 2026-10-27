import time
import threading
import requests
import os
from flask import request, g

# Simple in-memory cache for op_key validation results.
# cache: raw_key -> (expiry_epoch, result_dict)
_CACHE = {}
_LOCK = threading.Lock()
_DEFAULT_TTL = int(os.getenv("OPKEY_CACHE_TTL", "120"))  # seconds


def _now_epoch():
    return int(time.time())


def validate_op_key_with_core(raw_key, path, method):
    core_base = os.getenv("SALEOR_BASE_URL", "http://localhost:8000")
    url = f"{core_base}/internal/op-validate"
    internal_secret = os.getenv("OPKEY_INTERNAL_SECRET", "changeme-internal-secret")
    try:
        # Diagnostic: log outgoing validate call
        try:
            _log_entry = {
                "ts": int(time.time()),
                "event": "validate_call_out",
                "url": url,
                "path": path,
                "method": method,
                "masked_key": (raw_key[:6] + "..." + raw_key[-4:]) if raw_key else None,
            }
            _write_log(_log_entry)
        except Exception:
            pass

        r = requests.post(
            url,
            json={"op_key": raw_key, "path": path, "method": method},
            headers={"X-Internal-Secret": internal_secret},
            timeout=3,
        )
        # Diagnostic: log response
        try:
            _write_log({
                "ts": int(time.time()),
                "event": "validate_call_in",
                "status_code": r.status_code,
                "response_snippet": (r.text[:200] if r.text else None),
            })
        except Exception:
            pass
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _write_log(entry: dict):
    # Best-effort: append to /tmp and repository test-results for host visibility
    try:
        import json
        s = json.dumps(entry, ensure_ascii=False)
        try:
            with open('/tmp/bff-opkey.log', 'a', encoding='utf-8') as fh:
                fh.write(s + "\n")
        except Exception:
            pass
        try:
            host_path = os.path.join(os.path.dirname(__file__), '..', '..', 'test-results', 'bff-opkey.log')
            host_path = os.path.normpath(host_path)
            os.makedirs(os.path.dirname(host_path), exist_ok=True)
            with open(host_path, 'a', encoding='utf-8') as fh:
                fh.write(s + "\n")
        except Exception:
            pass
    except Exception:
        pass


def init_app(app):
    @app.before_request
    def _opkey_before_request():
        raw_key = request.headers.get("X-Op-Key") or request.headers.get("X-Op-Key".lower())
        if not raw_key:
            return
        # Check cache
        with _LOCK:
            entry = _CACHE.get(raw_key)
            if entry and entry[0] > _now_epoch():
                g.op_session = entry[1]
                g.op_session_valid = bool(entry[1].get("valid"))
                return
        # Not cached or expired -> validate with core
        res = validate_op_key_with_core(raw_key, request.path, request.method)
        if res is None:
            # treat as invalid
            with _LOCK:
                _CACHE[raw_key] = (_now_epoch() + _DEFAULT_TTL, {"valid": False})
            g.op_session = {"valid": False}
            g.op_session_valid = False
            return
        # Cache positive or negative result
        with _LOCK:
            _CACHE[raw_key] = (_now_epoch() + _DEFAULT_TTL, res)
        g.op_session = res
        g.op_session_valid = bool(res.get("valid"))
