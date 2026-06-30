// A thin jest test that LINKS each env-fragile export and mines a witness for it
// (a direct ``expect(name(args)).matcher(expected)`` the driver's witness miner
// reads). The point is only that the function HAS a linked, witness-mining test, so
// js-strengthen-tests is NOT refused at the locate/witness stage — it REACHES the
// value gates. It still MUST refuse because the function's return is env-fragile: the
// driver's AST ``pure`` scan drops the ``Date``/``Math.random``/free-``_now`` body
// BEFORE any oracle is captured, and even a transitive read that slipped the scan is
// caught by the env-reproducibility re-capture gate (proven separately). These pinned
// values are illustrative — the corpus only builds the PLAN, never runs this suite.
const { elapsed, rndScore, viaClock } = require("../fragile");

test("elapsed witness", () => {
  expect(elapsed(0)).toBe(0);
});

test("rndScore witness", () => {
  expect(rndScore(0)).toBe(0);
});

test("viaClock witness", () => {
  expect(viaClock(0)).toBe(0);
});
