# Case study: Apex catches an "almost-right" AI pull request

> A real, reproducible example — every number below is `apex review`'s actual
> output, not a mockup. Run it yourself; the verdict is deterministic.

## The scene

An AI coding assistant is asked to add a "rule expression" feature. It returns a
PR that **looks right** and probably passes a quick human skim:

```python
def parse_rule(expr, opts=[]):
    """Evaluate a user-supplied rule expression."""
    try:
        return eval(expr)
    except:
        opts.append("error")
        return None
```

Three real defects are hiding in nine lines — the kind that slip through review
when a team is drowning in AI-generated PRs:

- a **code-injection** hole (`eval` on user input),
- a **shared-state bug** (mutable default `opts=[]`),
- a swallowed-everything **bare `except`**.

## What `apex review` says (verbatim)

```
$ apex review --base HEAD --fail-on-high

# Apex review — changes since `HEAD`

Reviewed 1 changed file(s) · 3 issue(s) (3 auto-fixable by `apex maintain`).

- 🔴 app/config.py:9  [bug]      mutable default argument — shared-state bug   · Apex can auto-fix
- 🔴 app/config.py:12 [security] eval() — code injection risk                 · Apex can auto-fix
- 🟠 app/config.py:13 [security] bare except — use except Exception:           · suggested fix below

      - except:
      + except Exception:

$ echo $?
1
```

`apex review` looked at **only the changed lines**, named each defect with its
file:line and a grounded reason, showed the fix, and **exited non-zero** — so in
CI the pull request is blocked before it can merge.

## Why this matters commercially

- **Deterministic.** The same diff always produces this exact verdict. You don't
  have to trust the reviewer — you can replay it. (An LLM reviewer can't promise
  that.)
- **Zero-token, offline, air-gappable.** No API key, no code leaves the machine.
  It runs on every commit in a bank, a defense contractor, or any shop that
  *cannot* send source to a cloud model — where LLM reviewers simply aren't
  allowed.
- **It gates CI.** Drop the workflow in `.github/workflows/apex-ci.yml`: Apex
  posts this verdict as a PR comment, uploads the findings to your **Security
  tab** (SARIF), and fails the build on a high-severity issue. See
  [`docs/ci.md`](ci.md).
- **It can fix what it proves safe.** `apex review --fix` applies the
  auto-fixable findings on the changed files, **test-verified with auto-rollback**
  — it never leaves the PR broken.

## The positioning, in one line

> LLMs write code fast and unpredictably. **Apex is the deterministic reviewer
> that catches the "almost right" — with evidence, offline, on every PR** — the
> trust layer the generation tools created demand for.

_Reproduce: `git init` a repo, commit the clean version, paste the AI PR, and run
`apex review --base HEAD --fail-on-high`. Same verdict, every time._
