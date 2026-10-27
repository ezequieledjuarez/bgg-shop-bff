from functools import wraps
from flask import request, jsonify

from . import proxy
from .proxy import UpstreamError


def admin_required(f):
	@wraps(f)
	def wrapper(*args, **kwargs):
		auth_header = request.headers.get("Authorization")
		if not auth_header or not auth_header.strip():
			return jsonify({"error": "Authentication required"}), 401
		token = auth_header.strip()
		try:
			is_admin = proxy.check_admin(token)
		except UpstreamError:
			return jsonify({"error": "upstream GraphQL request failed"}), 502
		if not is_admin:
			return jsonify({"error": "forbidden"}), 403
		return f(*args, **kwargs)

	return wrapper

