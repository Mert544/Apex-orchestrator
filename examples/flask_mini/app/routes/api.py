"""Intentionally vulnerable demo fixture for the Apex static analyzer.

This Flask route module deliberately contains known security and quality
defects (marked with ``# KNOWN ISSUE``) so Apex's detectors and fix
transforms have a realistic target to find and repair. It is defensive
test data that exercises a code-analysis tool — not production code, and
not an exploit.
"""
from flask import Blueprint, request, jsonify
import os
import pickle

bp = Blueprint("api", __name__)

# KNOWN ISSUE 1: No input validation (missing guard clause)
@bp.route("/process", methods=["POST"])
def process_data():
    data = request.json
    # No validation of 'data' before eval-like usage below
    result = eval(data["expression"])  # KNOWN ISSUE 2: eval() usage
    return jsonify({"result": result})

# KNOWN ISSUE 3: Missing docstring, missing type annotations
def helper_compute(x, y, z, a, b, c):
    return x + y + z + a + b + c

# KNOWN ISSUE 4: Bare except
@bp.route("/safe")
def safe_route():
    try:
        return "ok"
    except:  # bare except
        return "error"

# KNOWN ISSUE 5: os.system usage
@bp.route("/exec/<cmd>")
def exec_cmd(cmd):
    os.system(cmd)
    return "done"

# KNOWN ISSUE 6: pickle.loads on untrusted data
@bp.route("/load", methods=["POST"])
def load_data():
    raw = request.data
    obj = pickle.loads(raw)
    return jsonify({"obj": str(obj)})
