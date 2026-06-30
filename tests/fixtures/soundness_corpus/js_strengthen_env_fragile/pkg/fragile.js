// A JS env-fragile-return shape for the js-strengthen-tests soundness corpus: an
// ALREADY-tested EXPORTED function whose return value VARIES with the clock / a
// random source — the strengthen-tests image of the Python ``env_fragile_return``
// fixture and the sibling of ``js_env_fragile_return`` (which targets js-cover-gaps).
// js-strengthen-tests MUST refuse it (an empty plan, never a landed assertion):
//
//   * ``elapsed`` / ``rndScore`` read the clock / randomness DIRECTLY, so the driver's
//     AST ``pure`` scan already refuses them (a ``Date``/``Math.random`` reference) —
//     the target is dropped BEFORE any mutant is seeded or any oracle captured.
//   * ``viaClock`` reads no clock DIRECTLY — it calls a module-level ``_now()`` — but
//     ``_now`` is a FREE identifier in its body (not a param/local/own name), so the
//     AST scan's free-identifier rule refuses it too (refuse-on-uncertainty).
//
// Each is exercised by the linked jest test below (so it is NOT refused at the
// locate/witness stage — it REACHES the value gates), proving the refusal comes from
// the AST + env-reproducibility gates, not a missing test. A mutant-killing assertion
// pinning any of these real outputs would pass the jest gate ONCE then go RED on a
// later run — the moat's cardinal fake-green sin — so the only sound verdict is
// REFUSE. (The dedicated env-gate regression test proves the SEPARATE case the AST
// scan cannot see — a value that captures cleanly yet re-renders differently under
// varied env/clock — is caught by the env-reproducibility re-capture gate.)
function elapsed(since) {
  return Date.now() - since;
}

function rndScore(seed) {
  return seed + Math.floor(Math.random() * 100);
}

function _now() {
  return Date.now();
}

function viaClock(offset) {
  return _now() + offset;
}

module.exports = { elapsed, rndScore, viaClock };
