// A JS/TS contradiction shape for the soundness corpus: a `throw`-stub whose ONLY
// contract is its JSDoc `@example`, with NO jest test linking it (so it is a
// js-implement-from-jsdoc candidate, the JS analogue of the Python provenance_trap)
// — but whose two examples are MUTUALLY UNSATISFIABLE by every fixed template, so
// js-implement-from-jsdoc MUST refuse (no fixed body reproduces both). The JS image
// of an adversarial shape Apex's own (Python) tree lacks.
/**
 * @example
 * combine(1, 2) === 100
 * combine(3, 4) === 5
 */
function combine(a, b) {
  throw new Error("Not implemented");
}
module.exports = { combine };
