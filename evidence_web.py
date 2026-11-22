"""Flask views for the operator's registered evidence-study workspace."""

from flask import Blueprint, jsonify, render_template, request
import evidence_workspace as workspace

views = Blueprint("evidence_workspace", __name__)


@views.route("/evidence-studies")
def panel():
    return render_template("evidence_studies.html")


@views.route("/api/evidence-studies")
def listing():
    return jsonify(workspace.list_items())


@views.route("/api/evidence-studies/items/<ident>")
def show(ident):
    return jsonify(workspace.describe(ident))


@views.route("/api/evidence-studies/actions/<action>", methods=["POST"])
def action(action):
    payload = request.get_json()
    if action == "resume":
        if not isinstance(payload, dict) or payload.keys() != {"id"}:
            raise ValueError("Provide the workspace job ID")
        return jsonify(workspace.resume(payload["id"])), 202
    if action == "plan":
        return jsonify(workspace.preview(payload))
    if action == "compare":
        if not isinstance(payload, dict) or payload.keys() != {"ids"}:
            raise ValueError("Provide run IDs to compare")
        return jsonify(workspace.compare(payload["ids"]))
    result = workspace.submit(action, payload)
    return jsonify(result), 202 if result["status"] == "running" else 201


@views.errorhandler(ValueError)
def bad_input(error):
    return jsonify(error=str(error)), 400


@views.errorhandler(OSError)
@views.errorhandler(KeyError)
def unavailable(_error):
    return jsonify(
        error="The registered study could not be read. Check the host profile or job diagnostics."
    ), 409
