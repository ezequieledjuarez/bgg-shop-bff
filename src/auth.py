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
		if not auth_header or not auth_header.strip():
			# If X-Op-Key was validated earlier by middleware, allow
			if getattr(g, "op_session_valid", False):
				return f(*args, **kwargs)
			if getattr(g, "op_session_validation_failed", False):
				return jsonify({"error": "upstream GraphQL request failed"}), 502
			return jsonify({"error": "Authentication required"}), 401
		token = auth_header.strip()
		try:
			is_admin = proxy.check_admin(token)
		except UpstreamError:
			return jsonify({"error": "upstream GraphQL request failed"}), 502
		if is_admin is None:
			return jsonify({"error": "Authentication required"}), 401
		if not is_admin:
			return jsonify({"error": "forbidden"}), 403
		return f(*args, **kwargs)

	return wrapper


def review_moderator_required(f):
	@wraps(f)
	def wrapper(*args, **kwargs):
		auth_header = request.headers.get("Authorization")
		if not auth_header or not auth_header.strip():
			response = jsonify({"error": "Authentication is required."})
			response.status_code = 401
		else:
			try:
				is_moderator = proxy.check_admin(auth_header.strip(), require_active=True)
			except Exception:
				response = jsonify({"error": "upstream GraphQL request failed"})
				response.status_code = 502
			else:
				if is_moderator is None:
					response = jsonify({"error": "Authentication is required."})
					response.status_code = 401
				elif not is_moderator:
					response = jsonify({"error": "Administrative permission is required."})
					response.status_code = 403
				else:
					return f(*args, **kwargs)
		response.headers["Cache-Control"] = "no-store"
		return response

	return wrapper
