# Apex — Value Proposition & ROI

*For engineering leaders and buyers evaluating Apex.*

> **What Apex is, in one line:** a deterministic, LLM-free, stdlib-only
> engineering agent that profiles your codebase, proposes a grounded roadmap of
> what to build next, and applies real **test-verified** fixes under strict
> safety gates — running offline, at **zero marginal cost**, with every
> recommendation carrying its own proof.

Apex is not a Copilot/Cursor competitor and does not try to be one. LLM
assistants generate code fast; Apex is the **deterministic trust layer** you run
*alongside* them — the one your CI and your auditor can actually depend on. This
document makes the business case without hype, grounded in capabilities that
exist in the product today (see `docs/market-positioning.md`, `CHECKPOINT.md`,
`ROADMAP.md`).

A note on numbers: **every dollar figure below is illustrative**, used to show
the *shape* of the cost comparison. They are not vendor quotes, and not a claim
about any specific competitor's pricing. Substitute your own contract numbers to
model your situation.

---

## 1. The cost story — zero marginal cost

Apex's core is **stdlib-only**: no API keys, no model-inference tokens, no
per-seat or per-line-of-code SaaS metering. Once it's installed, running it on
one commit or ten thousand commits costs the same: nothing beyond the compute you
already own. There is no usage meter to watch and no budget to ration, so teams
can run it on **every commit and every PR** without "should we afford this run?"
friction.

This contrasts with the two prevailing cost models in the modern tooling stack:

1. **Token-metered AI tools** (AI code review, AI autofix, chat-in-CI): you pay
   per request, scaling with PR volume and repo size. Cost grows exactly when
   you use the tool most.
2. **Per-seat / per-LOC SaaS** (hosted code-quality and security platforms):
   you pay a recurring subscription that scales with headcount or codebase size,
   used or not.

Apex's marginal cost per run, per seat, and per line is **$0**.

### Worked illustration (illustrative figures only)

Assume a team of **20 engineers** opening **400 PRs/month**.

| Cost line | Typical metered/SaaS model *(illustrative)* | Apex |
|---|---|---|
| Per-seat tooling subscription | $30/seat/mo × 20 = **$600/mo** | **$0** |
| AI review tokens per PR | ~$0.50/PR × 400 = **$200/mo** | **$0** |
| AI autofix / agent tokens | variable, grows with usage | **$0** |
| **Illustrative monthly total** | **~$800/mo (~$9,600/yr)** | **$0 marginal** |

The point is the *structure*, not the exact figures: metered and per-seat models
turn "run quality checks more often" into "spend more," while Apex makes
frequency free. Plug your own seat price, PR volume, and token rate into the same
table to size the difference for your org. Apex's only real costs are the compute
it runs on (which you already have) and the engineering time to adopt it.

---

## 2. The risk story — deterministic, proof-carrying, never fakes green

The bottleneck of AI-assisted engineering has shifted from *generation* to
*verification*: code that is "almost right, but wrong in a way that bites later."
Apex is built to remove that class of risk from its own output.

- **Deterministic — same input, same output.** No sampling, no temperature, no
  hallucinated findings. A result can be **replayed and audited**, so you don't
  have to *trust* it — you can *reproduce* it. This is also what lets CI depend
  on it: `apex gate` fails a build on a regression (grade drop, new security
  finding, coverage loss) the same way every time, and `apex gate --baseline`
  answers "did this PR make it worse?" reproducibly.
- **Proof-carrying recommendations.** A runnable recommendation shows the **exact
  draft diff** (computed, not blindly applied), a deterministic **re-parse
  verdict**, the **before→after metric delta** (max nesting / complexity /
  cognitive load), and whether **your tests actually exercise the change**
  (verification strength). Every applied fix writes a machine-readable
  `proof-of-fix.json` artifact — finding cited, diff, test-run evidence,
  rollbacks, commits — that a reviewer or compliance officer can open. "Trust me"
  becomes "here is the evidence."
- **Never fakes a green.** Apex refuses to claim "verified" on code its host
  suite doesn't actually cover. `apex develop --top` will not auto-apply to a
  module the tests don't exercise (it blocks unless forced, or first writes a
  characterization-test stub to shield the change). `apex scope` states the exact
  fraction of the repo it analyzes rather than silently grading a subset.
- **Safe autonomy with auto-rollback.** Fixes apply **only if the full suite
  passes**, with automatic rollback on failure, under a `ModePolicy`
  (report / supervised / autonomous) and `SafetyGates` (patch-scope limits,
  blocked sensitive paths, secret detection). `apex maintain` can run
  unsupervised without ever leaving the project in a broken state.

Net effect: Apex's findings and fixes carry **no flaky or hallucinated results**,
produce **reproducible audits**, and **cannot silently break your build**.

---

## 3. The compliance & privacy story — code never leaves the machine

Apex's core runs **fully offline**. There are no outbound API calls, no model
endpoints, and no telemetry required for it to do its job.

- **Your source code never leaves your machine.** Nothing is sent to a
  third-party model or service for analysis.
- **Air-gappable by construction.** Because the core is stdlib-only with no
  mandatory network dependency, Apex runs in fully air-gapped environments —
  finance, defense, healthcare, and any IP-sensitive shop where cloud assistants
  are *banned*, not merely discouraged. This is an **access** advantage, not just
  a price one: Apex works where LLM tools cannot run at all.
- **No third-party data-processing agreement needed for the core.** With no code
  egress, the procurement, DPA, and data-residency review that gate cloud-based
  AI tooling are largely moot for Apex's offline operation. (An optional local-LLM
  layer exists but is **off by default**; the deterministic core never requires
  it.)

For organizations that have blocked cloud assistants over IP and compliance
concerns, "offline and self-hosted" is not a limitation — it is the headline
feature.

---

## 4. The speed story — offline, no rate limits

- **No network round-trips, no rate limits, no queueing** behind a shared API.
  Analysis runs at local-compute speed; throughput is bounded by your hardware,
  not someone else's quota. This is what makes "run it on every commit" practical
  rather than aspirational.
- **Actively optimized hot paths.** The engine's performance has been a sustained
  focus, with measured, output-preserving speedups landed across the core — for
  example, the duplicate-finder was sped up **~2.6x with no change to output**
  (commit `0a1ae26`), the health-grade path cut from ~132s to ~18s via a lighter
  profile that produces the same grade, the rank pass from ~158s to ~36s, and the
  near-duplicate detector from >320s to ~103s. These are concrete, committed
  optimizations, not projections.
- **Parallel-safe development tooling.** `apex partition` computes
  provably-disjoint parallel work groups so larger codebases can be worked across
  multiple agents/worktrees, integrated safely under a single green gate.

The combination of "offline" and "no per-run cost" is what unlocks the real speed
benefit: there is never a reason *not* to run Apex, so feedback arrives on every
change instead of being rationed.

---

## 5. What you give up (the honest trade-offs)

A trust-positioned product has to be harder on itself than any competitor would
be. Buying Apex means accepting real, deliberate limits:

- **Smaller language coverage.** Deep AST-level analysis and the safe
  transform/refactor catalog are **Python-only** today. Apex is *aware* of the
  rest of a polyglot repo — `apex scope` reports the fraction outside analysis,
  `polyglot_facts` names the biggest/most-churned non-Python files, and
  cross-language coupling is surfaced — but those non-Python parts are
  **recommend-only**, with no transforms. Mature SaaS platforms cover many more
  languages with active fixing. If your stack is mostly non-Python, Apex's
  deepest value does not yet reach it.
- **No creative or genuinely ambiguous work — by design.** Because there is no
  LLM in the core, Apex will not name things well, write meaningful prose docs,
  design APIs, or resolve ambiguous intent. Determinism buys trust but caps
  capability. This is intentional: Apex is the deterministic layer you run
  *with* an LLM, not a replacement for one. If you want a single tool that both
  drafts creative code and verifies it, Apex is only the second half.
- **Less UI polish.** Apex is CLI-first, with HTML/dashboard exports and a thin
  VS Code wrapper. It does not match the editor integration, web consoles, and
  onboarding polish of established commercial platforms. Some infrastructure
  pieces (Kubernetes operator, Helm chart, VS Code extension) are explicitly
  labeled experimental, not production-ready.
- **A younger ecosystem.** No plugin marketplace, no large third-party
  integration catalog, and a shorter track record than incumbent tools. External
  accuracy calibration exists (`apex bench` on pinned OSS repos) and is honest
  about misses, but the breadth of independent validation that comes with a
  mature product simply isn't there yet.

Apex is the right buy when **verifiable, offline, zero-cost determinism on a
Python core** is what you need. It is the wrong buy if you need broad polyglot
autofix, turnkey creative generation, or a fully polished enterprise console
today.

---

## Positioning statement

LLMs write code fast — and unpredictably. **Apex is the deterministic,
zero-token engineer that proves which changes are safe, gates your CI
reproducibly, and develops the project it sits in — offline, air-gappable, and
replayable.** It costs nothing per run, keeps your source on your own machines,
never fakes a passing build, and carries its own evidence for every
recommendation. Run it alongside your AI tools as the verification layer they
created the need for: the one your auditor, your compliance officer, and your
build pipeline can actually trust.
