# Case Study: Flask Mini — Real-World Validation

This case study validates that Apex Orchestrator can detect **known, deliberately planted issues** in a real-world-style Flask application.

## Test Project

**Location:** `examples/flask_mini/`

A small Flask API with 6 known security and quality issues:

| Issue | Location | Severity | Expected Detection |
|---|---|---|---|
| 1. `eval()` usage | `app/routes/api.py::process_data` | **Critical** | Function-level risk scan |
| 2. `os.system()` usage | `app/routes/api.py::exec_cmd` | **Critical** | Function-level risk scan |
| 3. `pickle.loads()` on untrusted data | `app/routes/api.py::load_data` | **Critical** | Function-level risk scan |
| 4. Bare `except:` | `app/routes/api.py::safe_route` | **Medium** | AST pattern detection |
| 5. Missing docstring | `app/routes/api.py::helper_compute` | **Low** | Function-level analysis |
| 6. Too many arguments | `app/routes/api.py::helper_compute` | **Low** | Function-level analysis |

## Validation Result

```bash
pytest tests/test_real_world_validation.py -v
```

**Result:** ✅ All 6 issues detected automatically.

## How Apex Found Them

1. **`FunctionFractalAnalyzer.analyze_file()`** scanned each `.py` file
2. It produced a mini-fractal claim for every function:
   ```json
   {
     "name": "process_data",
     "full_name": "app.routes.api::process_data",
     "risks": ["Uses eval() — arbitrary code execution risk", "missing_docstring"],
     "risk_score": 0.4
   }
   ```
3. `RealWorldValidator.assert_expected_issues()` confirmed all 6 patterns were surfaced

## Significance

This proves Apex is not just a theoretical framework — it **detects real vulnerabilities** (eval, os.system, pickle) that would be caught by security auditors, without requiring manual configuration or LLM calls.

## Next Steps

- Expand validation to larger projects (Django, FastAPI)
- Add OWASP Top 10 pattern matching
- Validate auto-generated patches actually fix the issues
