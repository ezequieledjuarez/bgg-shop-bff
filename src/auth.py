from functools import wraps
from flask import request, jsonify
from flask import g

from . import proxy
from .proxy import UpstreamError
import logging

logger = logging.getLogger(__name__)


def admin_required(f):
	@wraps(f)
	def wrapper(*args, **kwargs):
		auth_header = request.headers.get("Authorization")
		# Temporary debug: capture raw representation and length to triage truncation
		try:
			print(f"[auth-debug] Authorization raw_repr={repr(auth_header)} length={len(auth_header) if auth_header else 0}")
		except Exception:
			pass
		# Log presence of Authorization header (masked for safety)
		if auth_header and isinstance(auth_header, str):
			masked = auth_header[:10] + '...' if len(auth_header) > 13 else auth_header
			# Ensure visibility during tests
			print(f"[auth] Incoming Authorization header: {masked}")
		# Also log the Origin header for CORS/origin-related debugging
		origin = request.headers.get('Origin')
		print(f"[auth] Incoming Origin header: {origin}")
		# If Authorization missing, dump header keys for quick inspection
		if not auth_header:
			# Log middleware-provided op session state for triage
			try:
				op_valid = getattr(g, 'op_session_valid', False)
				op_sess = getattr(g, 'op_session', None)
				print(f"[auth] g.op_session_valid={op_valid} g.op_session={repr(op_sess)[:200]}")
				# also persist a compact debug entry to disk for offline inspection
				try:
					import json, os
					dbg = {'ts': __import__('datetime').datetime.utcnow().isoformat() + 'Z', 'path': request.path, 'method': request.method, 'op_session_valid': bool(op_valid), 'op_session': None if op_sess is None else {'session_id': getattr(op_sess, 'id', None), 'user_id': getattr(op_sess, 'user_id', None), 'ops': getattr(op_sess, 'ops', None)}}
					out = '/tmp/bff-auth-debug.log'
					with open(out, 'a', encoding='utf-8') as fh:
						fh.write(json.dumps(dbg, ensure_ascii=False) + "\n")
				except Exception:
					pass
			except Exception:
				pass
			try:
				print(f"[auth] Request header keys: {list(request.headers.keys())}")
			except Exception:
				pass

		# Persist auth-related debug info to disk so we can correlate offline
		try:
			import json, os
			out_path = '/tmp/bff-debug-headers.log'
			entry = {
				'ts': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
				'path': request.path,
				'method': request.method,
				'auth_raw': repr(auth_header),
				'request_headers': dict(request.headers),
			}
			try:
				with open(out_path, 'a', encoding='utf-8') as fh:
					fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
			except Exception as e:
				print(f"[auth-debug] write failed to {out_path}: {e}")
				# best-effort fallback
				try:
					fallback = '/home/eze/develop/boardgame-app/test-results/bff-auth-debug.log'
					os.makedirs(os.path.dirname(fallback), exist_ok=True)
					with open(fallback, 'a', encoding='utf-8') as fh:
						fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
					print(f"[auth-debug] wrote fallback log to {fallback}")
				except Exception:
					pass
		except Exception:
			pass
		if not auth_header or not auth_header.strip():
			# If X-Op-Key was validated earlier by middleware, allow
			if getattr(g, "op_session_valid", False):
				print("[auth] request validated via X-Op-Key")
				return f(*args, **kwargs)
			return jsonify({"error": "Authentication required"}), 401
		token = auth_header.strip()
		try:
			# Conditional dump before performing WhoAmI/admin check
			try:
				import os, json, datetime
				if os.getenv("BFF_DUMP_BEFORE_ADMIN", "").lower() in ("1", "true", "yes") or os.path.exists('/tmp/BFF_DUMP_BEFORE_ADMIN'):
					try:
						dump = {
							'ts': datetime.datetime.utcnow().isoformat() + 'Z',
							'note': 'auth_pre_whoami',
							'path': request.path,
							'method': request.method,
							'headers': {'Authorization': auth_header},
						}
						with open('/tmp/bff-graphql-outgoing.log', 'a', encoding='utf-8') as fh:
							fh.write(json.dumps(dump, ensure_ascii=False) + "\n")
					except Exception:
						pass
			except Exception:
				pass
			is_admin = proxy.check_admin(token)
		except UpstreamError as exc:
			# Best-effort: persist a verification entry so we can confirm
			# the controller's UpstreamError path is exercised in the
			# running container during troubleshooting.
			try:
				import json, datetime
				entry = {
					'ts': datetime.datetime.utcnow().isoformat() + 'Z',
					'note': 'auth_upstream_error_test',
					'error': str(exc),
				}
				with open('/tmp/bff-graphql-error.log', 'a', encoding='utf-8') as fh:
					fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
			except Exception:
				pass
			return jsonify({"error": "upstream GraphQL request failed"}), 502
		if not is_admin:
			return jsonify({"error": "forbidden"}), 403
		return f(*args, **kwargs)

	return wrapper

