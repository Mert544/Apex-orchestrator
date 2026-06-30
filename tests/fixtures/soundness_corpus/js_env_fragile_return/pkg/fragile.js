// A JS env-fragile-return shape for the soundness corpus: EXPORTED zero-arg
// functions whose return value VARIES with the clock / a random source — the JS
// image of the Python ``env_fragile_return`` fixture. js-cover-gaps MUST refuse
// every one (an empty plan, never a landed test):
//
//   * ``stamp`` / ``rndInt`` read the clock / randomness DIRECTLY, so the driver's
//     AST ``pure`` scan already refuses them (a ``Date``/``Math.random`` reference).
//   * ``viaHelper`` reads no clock DIRECTLY — it calls a module-level ``_clock()``
//     — but ``_clock`` is a FREE identifier in its body (not a param/local/own
//     name), so the AST scan's free-identifier rule refuses it too (refuse-on-
//     uncertainty: a free reference could be a closure over external mutable state).
//     The dedicated env-gate regression test (test_js_cover_gaps_objective_eyml)
//     proves the SEPARATE case the AST scan cannot see — a value that captures
//     cleanly yet re-renders differently under varied env/clock — is caught by the
//     env-reproducibility re-capture gate.
//
// A test pinning any of these would pass the jest gate ONCE then go RED on a later
// run — the moat's cardinal fake-green sin — so the only sound verdict is REFUSE.
function stamp() {
  return Date.now();
}

function rndInt() {
  return Math.floor(Math.random() * 1000);
}

function _clock() {
  return Date.now();
}

function viaHelper() {
  return _clock();
}

module.exports = { stamp, rndInt, viaHelper };
