<div align="center">

# 🧠 Apex Orchestrator

### **A deterministic engineering agent that reasons about your codebase — and helps you act on it.**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-1100%2B%20passing-brightgreen)]()
[![Coverage](https://img.shields.io/badge/coverage-~88%25-brightgreen)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-black)](LICENSE)
[![No LLM required](https://img.shields.io/badge/LLM-optional-blueviolet)]()

**Apex scans your project, proposes a grounded, prioritized engineering roadmap, and applies real, test‑verified fixes under strict safety gates.** Its core runs **deterministically — no LLM required, fully offline** — so it's cheap, reproducible, and safe to put in CI.

[🚀 Quick Start](#-quick-start) · [💡 The Idea Engine](#-the-idea-engine) · [🗺️ Roadmap Mode](#️-roadmap-grounded-prioritization) · [🤖 Guarded Maintenance](#-guarded-autonomous-maintenance) · [🛡️ Safety](#️-safety-model) · [🧩 Claude Code](#-claude-code-integration)

</div>

---

## 🎯 What it does

Most code tools stop at a flat list of issues. Apex goes further — think of it as a small engineering brain with **eyes** (scanners), a **brain** (a deterministic reasoning engine), and **hands** (a sandboxed, test‑verified executor):

| Stage | What Apex does | Command |
|---|---|---|
| 👁️ **Scan** | Profiles structure, finds security risks, import cycles, fragile/untested modules | built into every run |
| 💡 **Ideate** | Generates a **fractal tree of grounded development ideas** from real code facts | `apex ideate` |
| 🗺️ **Prioritize** | Sequences ideas into a **Stabilize → Secure → Evolve → Refine** roadmap with impact/effort/ROI grounded in real structure | `apex ideate --roadmap` |
| 🔎 **Review** | Reviews a PR diff like a human reviewer — issues on the *changed* lines, with auto‑fix flags; CI‑ready | `apex review` |
| 🤖 **Fix** | Applies real, **test‑verified** fixes with automatic rollback and safety gates | `apex maintain` |
| 🔁 **Evolve** | Improves the project cycle by cycle **to a fixpoint**, then proves the gain (before/after + roadmap diff) | `apex evolve` |
| 🧪 **Simulate** | Preview what autonomous improvement would do — on a throwaway copy, changing nothing | `apex simulate` |
| 🎓 **Grade** | One memorable health grade (A–F) from all signals, with the cheapest ways to climb | `apex grade` |
| 📊 **Report** | One self‑contained HTML dashboard of everything above | `apex dashboard` |

Everything is **deterministic** (same input → same output) and **traceable** (every idea cites the concrete code fact that produced it). An optional LLM layer exists but is **off by default**.

### What Apex detects & fixes

One canonical AST detector powers both `apex review` and the health grade (and it
honours inline `# noqa` / `# nosec` suppression, just like Bandit/ruff).

| Category | Detected | Auto-fixed? |
|---|---|---|
| **Security** | `eval`/`exec`, `os.system`, `subprocess(shell=True)`, `pickle.loads`, `yaml.load`, f-string SQL, `tempfile.mktemp` (B306), weak `hashlib.md5/sha1` (B324), hardcoded secrets, bare `except` | eval→`literal_eval`, `os.system`→`subprocess.run(shlex.split(...))`, bare-except→`except Exception`; pickle/sql/tempfile/weak-hash **flagged** (no safe drop-in) |
| **Correctness (logic bugs)** | frozen-dataclass mutation (`FrozenInstanceError`), `return`/`break`/`continue` in `finally`, unreachable `except`, identity-vs-literal (`x is 5`, F632), comparison-with-itself, `assert` on a tuple | `x is 5`→`x == 5` |
| **Reliability** | `open()` without `encoding=`, network call without `timeout=` | `open(...)`→`encoding="utf-8"`; timeout flagged |
| **Code debt** | `== None`→`is None`, mutable default args (value-preserving guard, `T \| None` when safe) | yes |
| **Coverage** | untested modules, **shallow-only tests** (smoke/type stubs that assert no behaviour), complexity hotspots, TODO/FIXME debt clusters | generates real characterization tests (import + return-type contracts) |

The grade rolls these into five components — **Security · Architecture · Testing · Code debt · Correctness** — each severity-weighted, with test/fixture code excluded and shallow tests given only half credit (so a clean A+ can't be faked with stub tests).

---

## 🚀 Quick Start

```bash
# Install
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .[dev]

# Verify (1100+ tests)
pytest -q
```

**One command to remember — `apex`:**

```bash
apex                       # autonomous review — and applies safe fixes when it's safe to
apex "harden security"     # focus the review with a plain-English goal
apex auto --recommend      # read-only: review and recommend, never touch the tree
apex auto --apply --commit # full autonomy: apply verified fixes and commit each one
```

That's it. `apex` assesses the project, prioritizes the highest‑ROI work, and **decides for itself whether to act**: on a clean git tree with safe, test‑verified fixes available, it applies them autonomously (in roadmap order, capped, auto‑rolled‑back, *not committed* so you review with `git diff`); on a dirty tree — or when nothing is safely auto‑applicable — it recommends instead and tells you the one command to proceed. Use `--recommend` to force read‑only or `--apply` to override the gate. The specialized commands below are there when you want them, but you never *have* to memorize them.

> No API keys, no network, no setup beyond `pip install`. The core never calls out to anything.

## 🛡️ Use Apex in CI (drop-in GitHub Action)

Gate any repo on a deterministic, test-verified health grade — no API keys, no cost:

```yaml
# .github/workflows/apex.yml
name: Apex health gate
on: [pull_request]
jobs:
  apex:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }            # full history for the diff review
      - uses: mert544/apex-orchestrator@main
        with:
          min-score: "80"                   # fail the PR if the grade drops below 80
          base: origin/${{ github.base_ref }}
          fail-on-high: "true"              # fail if a high-severity issue is in the diff
```

The action grades the project (`apex grade --min-score`) and runs a diff-scoped
review of the PR (`apex review --fail-on-high`). Both are offline and
deterministic, so the gate is fast and reproducible.

---

## 💡 The Idea Engine

Apex doesn't only *analyze* code — it proposes **how to develop it**. The **Idea Permutation Engine** splits a project into development branches derived from its real structure, then permutes each branch through development "lenses" (extend, harden, test, simplify, document, integrate, generalize, observe) — the *"abc"* of every *"a"*. Optionally it **zooms fractally**: any idea can open into self‑similar sub‑ideas.

```bash
apex ideate --target=. --depth=2 --breadth=4              # the idea tree
apex ideate --target=. --facets --facet-depth=2           # fractal zoom into specifics
apex ideate --target=. --actions --top=10                 # map ideas → a supervised plan
```

Ask the engine to **show its work** for any idea — provenance, the value formula with the weights used, roadmap impact/effort/ROI grounded in fan‑in and LOC, and its caveats:

```bash
apex explain x.a.c --target=.     # why does this idea score what it does?
apex explain --target=.           # explain the single highest‑value idea
apex ideate --target=. --pareto   # the efficient frontier (non‑dominated ideas only)
apex ideate --target=. --adaptive # value‑guided fractal: high‑value branches grow deeper
```

Each idea is **traceable to a concrete project fact**, scored by relevance × novelty × feasibility, and stress‑tested with counterfactual caveats.

### It gets wiser over time

Apex is deterministic but not amnesiac. Every time it applies fixes (`auto`, `maintain`, `evolve`), it records which kinds of ideas actually landed cleanly vs. rolled back to `.apex/idea-memory.json`, and on later runs gives a bounded feasibility nudge toward the lenses with a strong track record **on your codebase**. Combined with `--adaptive` depth, the branches it has learned to trust grow deeper — a fractal that sharpens where it pays off. With no memory file, scoring is identical to a fresh engine, so determinism is never compromised. The engine also synthesizes ideas no single lens yields — e.g. a *security‑focused test suite* for a module that needs both hardening and tests, or *break this import cycle* from the dependency graph.

---

## 🗺️ Roadmap: grounded prioritization

A list of ideas is noise without an order. `--roadmap` sequences the whole tree into the phases an experienced engineer would follow — **you build a safety net before you change risky code, secure what's exposed, then evolve, then polish** — and scores each idea with **impact, effort, and ROI grounded in measured structure**:

- **Impact** = real *blast radius* (how many modules import the subject) + structural risk.
- **Effort** = real *size* (measured LOC + branch complexity) + how deep the idea is.
- **Quick wins** = high impact, low effort — surfaced across all phases.

```bash
apex ideate --target=. --roadmap
```

```text
# Engineering Roadmap for `.`
30 ideas sequenced · mean ROI 1.44

## ⚡ Quick wins (high impact, low effort)
- x.a.c  Test: app/engine/debug_engine.py        (ROI 2.41 · impact 1.0 · effort 0.42)

## Phase 1: Stabilize — Build a safety net before changing risky code
- x.a.c  Test: app/engine/debug_engine.py    (ROI 2.41 · imported by 6 · 330 LOC)
- x.c    Reduce fragility of claim_analyzer.py (ROI 1.86 · imported by 4 · 50 LOC)
...
## Phase 2: Secure   ## Phase 3: Evolve   ## Phase 4: Refine
```

**Track progress across runs** — the engine remembers its own recommendations:

```bash
apex ideate --target=. --roadmap --save     # snapshot today's roadmap
# ...do some work...
apex ideate --target=. --roadmap --diff     # what's new / resolved / shifted ROI?
```

**Or turn a phase straight into a guarded apply plan:**

```bash
apex ideate --target=. --roadmap --actions --phase=Secure --apply --verify
```

---

## 🤖 Guarded autonomous maintenance

One command runs the whole guarded loop: **scan → generate fixes → apply → verify with your tests → roll back failures → commit → report.** Every change is gated by `ModePolicy` + `SafetyGates`, individually verified against your test suite, and **automatically rolled back if it breaks anything** — a maintenance run can never leave your project broken.

```bash
apex maintain --target=. --mode=report                      # plan only, no changes
apex maintain --target=. --mode=supervised                  # apply verified fixes, no commit
apex maintain --target=. --mode=autonomous --commit --out=MAINT.md
```

Real deterministic, AST‑based fixes it can apply and verify:

| Risk | Fix |
|---|---|
| `eval(s)` | → `ast.literal_eval(s)` |
| `os.system(cmd)` | → `subprocess.run(...)` |
| bare `except:` | → `except Exception:` |
| `yaml.load(s)` | → `yaml.safe_load(s)` |
| `x == None` | → `x is None` (PEP 8, behavior‑preserving) |
| missing docstrings | → generated docstrings |
| `pickle.loads` / SQL f‑strings | flagged (no unsafe auto‑rewrite) |

The run ends with a Markdown report of what was applied, rolled back, or blocked — with per‑step commit hashes in autonomous mode.

---

## 🔁 Self‑improvement loop (`apex evolve`)

`apex evolve` closes the loop: it applies guarded fixes **cycle after cycle until it reaches a fixpoint** (no further fix can be safely applied and verified), then **proves the project got healthier** — a before/after of security findings, open safe fixes, and mean ROI, plus a roadmap **diff** of exactly which ideas it resolved.

```bash
apex evolve --target=. --max-cycles=3          # apply to a fixpoint, prove the gain
apex evolve --target=. --dry-run               # preview the first cycle, change nothing
apex evolve --target=. --commit                # commit each verified fix as it lands
```

```text
Ran 3 cycle(s) · applied 9 fix(es) · rolled back 0 · mode supervised

## Before → After
- Security findings: 2 → 0  ✅
- Open safe fixes:   26 → 24 ✅

## ✅ Ideas resolved (no longer surface)
- Add a first test layer for app/cfg.py
- Harden: app/parse.py
...
```

Because every fix is test‑verified with automatic rollback, an evolve run converges the codebase toward fewer findings without ever leaving it broken.

---

## 📊 Dashboard

```bash
apex dashboard --target=. --out=report.html
```

A single self‑contained HTML file (no external assets): project overview, scan findings, **architecture health** (import cycles, fragile modules), the **idea tree**, **tree‑shape telemetry**, the **engineering roadmap** with ROI bars, the action plan, and reasoning telemetry.

---

## 🛡️ Safety model

Apex operates in three explicit modes, enforced by `ModePolicy`:

| Mode | What it does | Best for |
|---|---|---|
| 📋 **Report** | Scans and reports only. Zero file changes. | Audits, CI |
| 👁️ **Supervised** | Applies test‑verified patches, **never commits**. | Daily development |
| 🤖 **Autonomous** | Applies, verifies, and commits each fix individually. | Trusted environments |

**SafetyGates** additionally enforce: a max‑changed‑files scope limit, blocked sensitive paths (`.env`, `secrets/**`, `*.pem`), secret detection, mandatory test verification after every patch, and a rollback‑ready journal for every change. Patches are always staged in a sandbox first.

---

## 🧩 Claude Code integration

This repo ships first‑class [Claude Code](https://code.claude.com) customizations in `.claude/`, so you (and Claude) can drive *and extend* Apex from your editor:

- **Slash commands**: `/apex-ideate`, `/apex-roadmap`, `/apex-maintain` (safe dry‑run default), `/apex-dashboard`
- **Subagents**: `apex-auditor` (read‑only health report), `apex-test-writer` (parallel coverage specialist), `apex-engineer` (builds a deterministic engine feature end‑to‑end)
- **Skills**: `apex` (run & extend), `apex-cover` (coverage recipe), `apex-ship` (commit/verify discipline)

---

## 🏗️ Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│                        APEX ORCHESTRATOR                          │
├──────────────────────────────────────────────────────────────────┤
│  Eyes (Scanners)     │  Brain (Engine)        │  Hands (Executor) │
│  ────────────────    │  ──────────────        │  ──────────────── │
│  Project profiler    │  Idea permutation tree │  Action executor  │
│  Security / AST scan │  Roadmap (impact/effort│  Semantic patches │
│  Dependency graph    │   /ROI from real code) │  Safety gates     │
│  Code metrics        │  Tree‑shape telemetry  │  Verify+rollback  │
├──────────────────────────────────────────────────────────────────┤
│  Memory & Feedback   │  Policy                │  Reports          │
│  Cross‑run tracker   │  Mode policy           │  Markdown / HTML  │
│  Roadmap history     │  Safety gates          │  SARIF / Mermaid  │
└──────────────────────────────────────────────────────────────────┘
```

Optional surfaces: an **MCP server** (stdio + HTTP/SSE) for IDE integration, a **Prometheus** metrics endpoint, an **LSP** server, and a plugin system with hook points and runtime‑contributed idea operators.

---

## 📈 Project status

- ✅ **Idea Permutation Engine** — fractal idea tree (+ recursive facet zoom, adaptive value‑guided depth, synthesis & module‑pair ideas)
- ✅ **Roadmap mode** — phase sequencing + impact/effort/ROI grounded in fan‑in and measured LOC/complexity, the Pareto efficient frontier, and cross‑run diffing
- ✅ **Learning memory** — per‑lens apply outcomes bias future scoring (bounded, opt‑in, deterministic)
- ✅ **Self‑improvement loop** (`apex evolve`) — converge to a fixpoint with a circuit breaker, prove the gain, and track the trajectory
- ✅ **Guarded maintenance** — real AST fixes, test‑verified, auto‑rollback, optional per‑fix commits
- ✅ **Dashboard, debug, self‑audit, MCP, metrics, LSP**
- ✅ **Deterministic, offline core** — LLM is strictly opt‑in
- ✅ **1100+ tests**, ~88% coverage, ruff‑linted, CI‑gated

**Experimental (not production‑ready):** the Kubernetes operator, Helm chart, and VS Code extension are skeletal.

---

## 🤝 Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup and conventions.

```bash
pip install -e .[dev]
pytest -q          # run the suite
ruff check app/    # lint
```

---

## 📄 License

Licensed under **Apache‑2.0**. See [LICENSE](LICENSE).

<div align="center">

**Built for engineers who believe a codebase deserves real reasoning — not just a linter.**

</div>
