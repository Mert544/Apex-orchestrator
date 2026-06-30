// ts_driver.js — Apex's bundled, deterministic JS/TS parse/transform driver.
//
// The LLM-free transform engine behind the js-tdd-implement objective. Apex
// (Python) spawns this script through the existing CommandRunner; it speaks
// canonical JSON on stdout and exits 2 on REFUSE. It depends ONLY on the global
// TypeScript Compiler API (`require("typescript")`, resolved via NODE_PATH) — no
// third-party npm dependency is ever installed, so parsing/transforming JS/TS is
// fully offline and zero-install. `ts.createSourceFile` is a pure function of the
// bytes and every emission is sorted/stable, so the same input yields the same
// output (the determinism invariant the Python spine keeps).
//
// Subcommands (argv[2]):
//   scan  <file>            -> JSON: the single-`throw`-stub top-level functions
//                             in <file> with their exact body byte span.
//                             Exit 2 (REFUSE) when the file does not parse.
//   mine  <testfile> <name> -> JSON: the witness tuples a jest test pins on
//                             <name>: [{args:[...], expected:"..."}] from
//                             expect(<name>(...)).<matcher>(<expected>) shapes
//                             (matchers: toBe / toEqual / toStrictEqual).
//   mine-jsdoc <file> <name> -> JSON: the SAME [{args, expected}] witness shape,
//                             but mined from the stub <name>'s OWN leading JSDoc
//                             `@example` lines (`<name>(...) === <expected>` or
//                             `expect(<name>(...)).toBe(<expected>)`) — the
//                             contract of a stub NO jest test references. Pure
//                             leading-comment trivia read (no type info), exactly
//                             one JSDoc-block definition or refuse (empty list).
//                             Exit 2 (REFUSE) when the file does not parse.
//   fill  <file> <name> <body>
//                          -> replace the body BLOCK of the single top-level
//                             function <name> with `{ <body> }` (exact byte-span
//                             splice — formatting/comments around it survive),
//                             write <file> in place, print the touched span.
//                             Exit 2 (REFUSE) when <name> is not defined exactly
//                             once as a fillable stub.
//   doc-targets <file>     -> JSON: every EXPORTED function/const-arrow in <file>
//                             with NO leading JSDoc, as [{name, params,
//                             paramTypes, returnType|null, returnsInferred|null,
//                             throwsTypes|null, insertOffset}] — the facts the
//                             document-export-jsdoc (names + returnType),
//                             js-document-param-types (the verbatim per-param
//                             `paramTypes`), document-raises-jsdoc (the `throwsTypes`
//                             set) and js-document-returns-inferred (the
//                             `returnsInferred` type) objectives splice a minimal
//                             JSDoc from (pure AST). `paramTypes` is parallel to
//                             `params` (one verbatim type or null per param).
//                             `throwsTypes` is the DISTINCT thrown constructor names
//                             in source order — but ONLY when EVERY `throw` in the
//                             body is a literal `new <Identifier>(...)`; any other
//                             throw shape makes it null (the document-raises-jsdoc
//                             refusal). `returnsInferred` is the type PROVEN from the
//                             body's own literal `return` statements (boolean/string/
//                             number/Array/Object/ctor-name), or null when ANY return
//                             is non-literal / void / null / heterogeneous, the body
//                             can implicitly fall through to `undefined` (no tail
//                             return/throw), or the function is a GENERATOR (the
//                             js-document-returns-inferred refusals). An ASYNC function's
//                             type is wrapped as `Promise<T>` (its literal return is a
//                             resolved promise at runtime). It is DISJOINT from
//                             `returnType` (the DECLARED TS annotation) — the Python
//                             side fires only when `returnType` is null. Exit 2 on
//                             parse error.
//   doc-verify <file>      -> JSON: {names:[...]} the sorted EXPORTED-name set of
//                             <file>. The behaviour-identical oracle for a JSDoc
//                             splice: a leading comment changes ZERO runtime bytes,
//                             so the spliced file must re-parse (exit 2 if not) AND
//                             carry the same exported names — Python compares the
//                             pre/post sets and refuses on any drift.
//   wire-targets <file>    -> JSON: every top-level PUBLIC function/const-arrow in
//                             <file> that is DEFINED but never exported (and not
//                             otherwise named in `export {`/`export default`/
//                             `module.exports`), as [{name, kind, insertOffset}] —
//                             the missing-export targets the js-wire-exports
//                             objective splices a leading `export ` keyword before.
//                             REFUSES the WHOLE file (empty list) when ANY
//                             `module.exports`/`exports.`/`export default`/`export =`
//                             is present (CJS + default-export are the deferred
//                             surface; v0 is clean-ESM-named only). Exit 2 on parse.
//   wire-verify <file>     -> JSON: {names:[...]} the sorted ALL-EXPORTED-name set of
//                             <file> (ESM `export`, `export {`, plus CJS
//                             `module.exports.NAME`/`exports.NAME`). The oracle for a
//                             wire splice: the spliced file must re-parse (exit 2 if
//                             not) AND carry exactly the prior set UNION {name} —
//                             Python proves the splice added precisely the one
//                             intended named export and corrupted nothing.
//   cover-targets <file>   -> JSON: every EXPORTED, public (non-`_`), undecorated,
//                             NON-async, NON-generator function/const-arrow (ESM
//                             `export` or CJS `module.exports.NAME = fn`) in <file>
//                             as [{name, params:[{name, type|null, defaultText|null}],
//                             pure, exportKind}] — the CHARACTERIZATION targets the
//                             js-cover-gaps objective synthesises a jest test for. The
//                             `pure` flag is the AST forbidden-call/free-identifier
//                             scan (the cheap FIRST flaky-test guard, before the
//                             Python env-reproducibility re-capture gate): false the
//                             moment the body reads the clock/random/env/IO/network
//                             (`Date`/`Math.random`/`process`/`performance`/`fs`/
//                             `fetch`/`require`/dynamic `import`/`globalThis`/...) or
//                             references any FREE identifier outside its
//                             params/locals/own-name and a small pure-globals
//                             allow-list. `params` reuses the identifier-or-defaulted
//                             gate (a destructuring/rest param makes it null and the
//                             target is skipped); `defaultText` is the verbatim
//                             literal default (or null). The Python side decides the
//                             SOUND input slice (zero-arg / all-primitive-typed /
//                             all-literal-default) and REFUSES the rest. Exit 2 on
//                             parse error.
//   mutate <file> <name>   -> JSON: the single-token MUTANT catalog for the
//                             EXPORTED cover target <name> in <file>, as
//                             [{operator, original, mutated, start, end}] — each a
//                             UTF-16 code-unit span splice for the js-strengthen-tests
//                             (LITE) gap-FINDER. Mirrors the Python mutation_tester
//                             operator set: comparison flips (`===`->`!==`, `<`->`>=`),
//                             off-by-one boundary (`<`->`<=`), arithmetic (`+`->`-`),
//                             boolean (`&&`->`||`), bool-const (true<->false), numeric
//                             `n`->`n+1`, `return X`->`return undefined`. Sites in
//                             document order, a FIXED cap, no clock/random. Read-only:
//                             the Python side applies each splice to an IN-MEMORY copy
//                             (NEVER persisted) and decides survival against the
//                             function's MINED witnesses. Empty list when <name> is not
//                             an exported cover target. Exit 2 on parse error.
//
// Determinism: no clock, no randomness; functions are reported in source order;
// JSON keys are emitted in a fixed order. A UTF-16-code-unit-span splice
// (getStart/getEnd — the SourceFile text is indexed in UTF-16 code units, so the
// Python side re-indexes these to code points before its own splice), never an AST
// unparse, so the surrounding source is untouched.

"use strict";

const fs = require("fs");
const ts = require("typescript");

const REFUSE = 2;

// Pick the parser dialect from the extension. `.ts`/`.tsx` parse as TS, anything
// else (`.js`/`.jsx`/`.mjs`/`.cjs`) parses as JS — no TypeScript types required.
function scriptKindFor(file) {
  const lower = file.toLowerCase();
  if (lower.endsWith(".tsx")) return ts.ScriptKind.TSX;
  if (lower.endsWith(".ts")) return ts.ScriptKind.TS;
  if (lower.endsWith(".jsx")) return ts.ScriptKind.JSX;
  return ts.ScriptKind.JS;
}

function parse(file, source) {
  return ts.createSourceFile(
    file, source, ts.ScriptTarget.Latest, /*setParentNodes*/ true,
    scriptKindFor(file));
}

// The parameter NAMES of a function-like node, in order — only plain identifier
// params (no destructuring / rest / defaults) so the witness templates line up
// with concrete arguments. Returns null when any param is not a bare identifier.
function paramNames(node) {
  const names = [];
  for (const p of node.parameters) {
    if (!ts.isIdentifier(p.name) || p.dotDotDotToken || p.initializer) return null;
    names.push(p.name.text);
  }
  return names;
}

// The per-parameter facts a CHARACTERIZATION target needs for input synthesis,
// in order, or null when a param is not a plain identifier-or-defaulted-identifier
// (a destructuring / rest param has no single sample to synthesize, so the WHOLE
// target is refused). Unlike `paramNames` this ACCEPTS an `initializer` (a default)
// — but reads it ONLY when it is a LITERAL the Python side can re-emit verbatim
// (`number`/`string`/`boolean`/`null`/array-literal/object-literal/a unary minus on
// a numeric literal), else `defaultText` is null. Each entry is
// `{name, type|null, defaultText|null}`: `type` is the verbatim TS annotation (or
// null), `defaultText` the verbatim literal default source (or null). The
// js-cover-gaps input synthesiser uses these to decide the SOUND slice (zero-arg /
// all-primitive-typed / all-literal-default) and refuses anything else.
function coverParamInfos(node, sf) {
  const infos = [];
  for (const p of node.parameters) {
    if (!ts.isIdentifier(p.name) || p.dotDotDotToken) return null;
    infos.push({
      name: p.name.text,
      type: p.type ? p.type.getText(sf).trim() : null,
      defaultText: p.initializer ? literalDefaultText(p.initializer, sf) : null,
    });
  }
  return infos;
}

// The verbatim source text of a parameter DEFAULT when it is a literal the Python
// side can re-emit as a sample argument, else null. Accepted literal shapes (the
// JSON-serialisable, deterministic subset — mirrors the Python `_arg_literal`
// default discipline): a numeric/string/no-substitution-template/boolean/null
// literal, an array or object literal, or a unary `-`/`+` on a numeric literal
// (`-1`). A `BigIntLiteral`, an interpolated template, a call, an identifier
// reference, or any non-literal initializer yields null (the param then has no
// usable default — the synthesiser refuses unless another rule covers it). Pure
// AST + verbatim getText, so the emitted sample is exactly the author's bytes.
function literalDefaultText(expr, sf) {
  if (expr.kind === ts.SyntaxKind.TrueKeyword
      || expr.kind === ts.SyntaxKind.FalseKeyword
      || expr.kind === ts.SyntaxKind.NullKeyword) return expr.getText(sf).trim();
  if (ts.isNumericLiteral(expr) || ts.isStringLiteral(expr)
      || ts.isNoSubstitutionTemplateLiteral(expr)) return expr.getText(sf).trim();
  if (ts.isArrayLiteralExpression(expr) || ts.isObjectLiteralExpression(expr)) {
    return expr.getText(sf).trim();
  }
  if (ts.isPrefixUnaryExpression(expr)
      && (expr.operator === ts.SyntaxKind.MinusToken
          || expr.operator === ts.SyntaxKind.PlusToken)
      && ts.isNumericLiteral(expr.operand)) {
    return expr.getText(sf).trim();
  }
  return null;  // non-literal / bigint / interpolated / call / identifier -> refuse
}

// The DECLARED parameter TYPES of a function-like node, in order — parallel to
// `paramNames` (the SAME identifier gate, so a destructuring / rest / default
// param makes it return null too). Each entry is the param's TS type-annotation
// text read VERBATIM off the AST (`p.type.getText(sf).trim()`), or null when that
// param carries no annotation. The js-document-param-types objective reads these
// to mint `@param {T} name` lines; a type is never inferred, only copied from the
// author's own annotation (so the JSDoc cannot misstate it).
function paramTypes(node, sf) {
  const types = [];
  for (const p of node.parameters) {
    if (!ts.isIdentifier(p.name) || p.dotDotDotToken || p.initializer) return null;
    types.push(p.type ? p.type.getText(sf).trim() : null);
  }
  return types;
}

// The DISTINCT thrown-constructor names of a function-like node's body, in source
// order, or null when the throw set is not PROVABLE. The document-raises-jsdoc
// fact: walk the body for every `ts.isThrowStatement` and require its expression be
// a literal `new <Identifier>(...)` (a `ts.isNewExpression` whose `expression` is a
// bare `ts.isIdentifier` — e.g. `throw new TypeError("bad")`). Collect each ctor's
// `.text` in source order, de-duplicated (one `@throws {Ctor}` per distinct ctor).
// Returns null the moment ANY throw is a shape we cannot read verbatim — a
// `throw <variable>` / `throw fn()` / a member-expression ctor `new ns.Err()` / a
// bare re-throw — so the objective REFUSES rather than claim an unprovable @throws
// (the same null-on-unmodelled-shape discipline as `paramTypes`). A body with zero
// throws yields [] (vacuously provable, empty) — the Python honesty gate then
// refuses it (nothing to document), never an empty @throws block.
//
// ESCAPE-only attribution (the refuse-on-uncertainty fix). A `@throws` is the
// DOCUMENTED function's OWN failure contract, so only a throw that actually
// escapes THIS function counts:
//   (1) NESTED-FUNCTION boundary — a `throw` inside a nested function/method/arrow/
//       constructor (e.g. an `items.forEach((x) => { throw ... })` callback or an
//       inner helper) is THAT function's contract, not the documented one. The walk
//       therefore does NOT descend into any function-like child other than the root
//       node; its throws are invisible here.
//   (2) try/catch — statically deciding which throws a `catch` swallows vs.
//       re-throws is fragile, so the SOUND rule is to REFUSE the whole target
//       (return null) the moment the body contains ANY `try` with a `catch` clause.
//       A `try`/`finally` with NO `catch` does NOT swallow — those throws still
//       escape — so a catch-less try alone never triggers the refusal.
function throwsTypes(node) {
  const body = node.body;
  if (!body || !ts.isBlock(body)) return [];
  const seen = new Set();
  const names = [];
  let provable = true;
  function visit(n) {
    // A `try`/`catch` may swallow a throw — refuse the whole target (only a
    // PRESENT catch clause swallows; a catch-less `try`/`finally` does not).
    if (ts.isTryStatement(n) && n.catchClause) provable = false;
    if (ts.isThrowStatement(n)) {
      const expr = n.expression;
      if (expr && ts.isNewExpression(expr) && ts.isIdentifier(expr.expression)) {
        const name = expr.expression.text;
        if (!seen.has(name)) {
          seen.add(name);
          names.push(name);
        }
      } else {
        provable = false;  // a throw whose ctor we cannot read verbatim -> refuse
      }
    }
    ts.forEachChild(n, (child) => {
      // Do NOT descend into a nested function-like node — its throws are its OWN
      // contract, never the documented function's. Only the root body is walked.
      if (child !== node && ts.isFunctionLike(child)) return;
      visit(child);
    });
  }
  visit(body);
  return provable ? names : null;
}

// True when `node` carries an `async` modifier — an `async function`, an
// `async () => ...`, an `async method(){}`, or an async function expression.
// Read like `isExported`, with the `ts.getModifiers`/`node.modifiers` fallback so
// the same walk works across compiler versions. An async function's literal
// `return T` is actually wrapped in a `Promise<T>` at runtime, so we MUST emit
// `@returns {Promise<T>}`, never a bare `{T}` (that would be a false fact).
function isAsync(node) {
  const mods = ts.getModifiers ? ts.getModifiers(node) : node.modifiers;
  if (!mods) return false;
  return mods.some((m) => m.kind === ts.SyntaxKind.AsyncKeyword);
}

// The bare PROVABLE return type of a function-like node, read VERBATIM off its
// OWN-SCOPE `return` expressions, or null when it is not provable — BEFORE any
// async/generator wrapping (the `returnsType` wrapper applies those). The
// js-document-returns-inferred fact — the SIBLING of `throwsTypes` for plain JS:
// `document-export-jsdoc` can only emit `@returns {T}` from a DECLARED TS return
// type, so a plain-JS export gets no `@returns`; this infers one from LITERAL
// returns. Each return's expression is mapped to a type by its AST kind ONLY:
//   `true`/`false`              -> "boolean"
//   string / no-subst template  -> "string"
//   numeric literal             -> "number"
//   array literal               -> "Array"
//   object literal              -> "Object"
//   `new <Identifier>(...)`     -> that ctor's name (e.g. `new Date()` -> "Date")
// A type is NEVER inferred from a value flow / call result — only copied off a
// literal node — so the JSDoc cannot misstate it. Returns null the moment a
// return is a shape we cannot read verbatim: a non-literal expression
// (`return foo()`, `return a + b`, `return -1`), a bare `return;` / implicit void,
// `return null` / `return undefined`, a member-expression ctor (`new ns.Err()`),
// a `BigIntLiteral` / interpolated template (not in the table), OR the literal
// kinds DISAGREE across returns (heterogeneous — `return true` + `return "x"`).
// A node with NO return at all also yields null (nothing to document). This is
// the same null-on-unprovable discipline `throwsTypes` ships — strict, REFUSE on
// any ambiguity, never guess. (ASYNC wrapping to `Promise<T>` and GENERATOR
// refusal are applied by the `returnsType` wrapper around this bare inference.)
//
// OWN-SCOPE only (like `throwsTypes`): a `return` inside a nested function/arrow/
// method is THAT function's contract, not the documented one, so the walk does
// NOT descend into any function-like child other than the root node. A concise
// (expression-bodied) arrow — `const f = (x) => true` — has ONE implicit return
// of its body expression, which is mapped exactly like an explicit `return`.
//
// DEFINITE-RETURN guard (the never-fake-green fix). Agreeing literal returns are
// NOT enough: a body that returns a literal on SOME paths but can fall through to
// the end returns `undefined` on the tail path — so `f(x){ if(x) return true; }`
// is `boolean|undefined`, NOT `boolean`, and emitting `@returns {boolean}` would
// be a FALSE fact. We require the body to provably return/throw on the TAIL path
// via a SOUND, decidable, conservative rule: the block's LAST statement must be an
// unconditional `return <literal>` or a `throw`. That alone guarantees no implicit-
// undefined fall-through (`if(x) return true;` -> last stmt is the `if` -> REFUSE;
// `if(x) return true; return false;` -> last is `return false` -> accept; a
// trailing `for`/`while`/`switch` -> REFUSE). It is DELIBERATELY conservative —
// it also refuses an exhaustive `if/else`-both-return with no trailing return, and
// a switch-with-default — refuse-on-ambiguity is the correct posture (refusing some
// valid exhaustive cases is fine; accepting ANY fall-through is not). A concise
// arrow body always returns, so it bypasses this guard.

// True when block `body`'s LAST statement provably hands off control off the tail
// path — an unconditional `return <literal>` (a literalReturnType-readable value)
// or a `throw` — so execution cannot fall off the end into an implicit `undefined`.
function tailReturnsOrThrows(body) {
  const stmts = body.statements;
  if (!stmts || stmts.length === 0) return false;
  const last = stmts[stmts.length - 1];
  if (ts.isThrowStatement(last)) return true;
  if (ts.isReturnStatement(last)) return literalReturnType(last.expression) !== null;
  return false;
}

function literalReturnType(expr) {
  if (!expr) return null;  // a bare `return;` / implicit void -> refuse
  if (expr.kind === ts.SyntaxKind.TrueKeyword
      || expr.kind === ts.SyntaxKind.FalseKeyword) return "boolean";
  if (ts.isStringLiteral(expr) || ts.isNoSubstitutionTemplateLiteral(expr)) return "string";
  if (ts.isNumericLiteral(expr)) return "number";
  if (ts.isArrayLiteralExpression(expr)) return "Array";
  if (ts.isObjectLiteralExpression(expr)) return "Object";
  if (ts.isNewExpression(expr) && ts.isIdentifier(expr.expression)) {
    return expr.expression.text;  // `new Date()` -> "Date", verbatim ctor name
  }
  return null;  // null/undefined/call/binary/member-ctor/bigint/... -> refuse
}

function inferBareReturnType(node) {
  const body = node.body;
  if (!body) return null;
  // A concise arrow body (`(x) => true`) is ONE implicit return of the body
  // expression — map it directly (it is not a block, so the walk below is moot).
  if (!ts.isBlock(body)) return literalReturnType(body);
  let inferred = null;     // the single agreed type so far (null = none yet)
  let provable = true;     // a return we cannot read verbatim flips this false
  let sawReturn = false;   // at least one return statement seen in own scope
  function visit(n) {
    if (ts.isReturnStatement(n)) {
      sawReturn = true;
      const t = literalReturnType(n.expression);
      if (t === null) {
        provable = false;          // a non-literal / void / null return -> refuse
      } else if (inferred === null) {
        inferred = t;              // first proven type sets the contract
      } else if (inferred !== t) {
        provable = false;          // a DIFFERENT literal kind -> heterogeneous -> refuse
      }
    }
    ts.forEachChild(n, (child) => {
      // Do NOT descend into a nested function-like node — its returns are its OWN
      // contract, never the documented function's. Only the root body is walked.
      if (child !== node && ts.isFunctionLike(child)) return;
      visit(child);
    });
  }
  visit(body);
  // Provable iff every return was a literal AND they agreed AND there was one AND
  // the body provably returns/throws on the TAIL path (no implicit-undefined
  // fall-through — the definite-return guard).
  return provable && sawReturn && tailReturnsOrThrows(body) ? inferred : null;
}

// The js-document-returns-inferred fact, with async/generator wrapping applied to
// the bare inferred type. THREE soundness layers gate the emission:
//   (1) GENERATOR (`node.asteriskToken` — `function*`, `async function*`, a
//       generator method): a `return` inside a generator is the iterator's return
//       value, NOT a simple `@returns` type (the produced value is a Generator /
//       AsyncGenerator object). Documenting it properly needs `@yields` (out of
//       scope), so REFUSE entirely (null) — the sound choice.
//   (2) the bare inference + the definite-return guard (see `inferBareReturnType`).
//   (3) ASYNC (`isAsync(node)`): an `async function`'s `return T` is wrapped in a
//       `Promise<T>` at runtime, so emit `@returns {Promise<T>}`, NEVER a bare
//       `{T}`. The fall-through guard runs on the bare inference FIRST, so an async
//       fn that can fall through is `Promise<T | undefined>` and is already refused
//       (null in, null out) — we never wrap a non-provable type.
function returnsType(node) {
  if (node.asteriskToken) return null;  // generator -> refuse (needs @yields)
  const bare = inferBareReturnType(node);
  if (bare === null) return null;
  return isAsync(node) ? "Promise<" + bare + ">" : bare;
}

// A function-like declaration is a "throw-stub" iff its body is EXACTLY one
// `throw` statement (e.g. `throw new Error("Not implemented")`) — the JS image of
// Python's `raise NotImplementedError` stub. Returns the body block or null.
function throwStubBody(node) {
  const body = node.body;
  if (!body || !ts.isBlock(body)) return null;
  if (body.statements.length !== 1) return null;
  if (!ts.isThrowStatement(body.statements[0])) return null;
  return body;
}

// Collect the top-level fillable stub functions of a source file: a
// `function foo(...) { throw ... }` declaration, or a `const foo = (...) => {
// throw ... }` / `const foo = function (...) { throw ... }` arrow/function
// initializer. Each carries its name, plain param names, and the UTF-16 code-unit
// span of its body block (start = the `{`, end = just past the `}`).
function collectStubs(sf) {
  const out = [];
  function consider(name, fnNode) {
    const params = paramNames(fnNode);
    if (params === null) return;
    const body = throwStubBody(fnNode);
    if (body === null) return;
    out.push({
      name: name,
      params: params,
      bodyStart: body.getStart(sf),
      bodyEnd: body.getEnd(),
    });
  }
  for (const stmt of sf.statements) {
    if (ts.isFunctionDeclaration(stmt) && stmt.name) {
      consider(stmt.name.text, stmt);
    } else if (ts.isVariableStatement(stmt)) {
      for (const decl of stmt.declarationList.declarations) {
        const init = decl.initializer;
        if (!init || !ts.isIdentifier(decl.name)) continue;
        if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) {
          consider(decl.name.text, init);
        }
      }
    }
  }
  return out;
}

// The literal source text of an argument/expression node, trimmed. Used to
// surface witness args/expected as the exact bytes the test wrote.
function literalText(node, sf) {
  return node.getText(sf).trim();
}

// Mine witness tuples for <name> from a jest test source: every
// `expect(<name>(<args...>)).<matcher>(<expected>)` whose matcher is one of
// toBe / toEqual / toStrictEqual, with <name> called bare or as `mod.name(...)`.
function mineWitnesses(sf, name) {
  const witnesses = [];
  const matchers = new Set(["toBe", "toEqual", "toStrictEqual"]);
  function callTargetsName(callExpr) {
    const fn = callExpr.expression;
    if (ts.isIdentifier(fn)) return fn.text === name;
    if (ts.isPropertyAccessExpression(fn)) return fn.name.text === name;
    return false;
  }
  function visit(node) {
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
        && matchers.has(node.expression.name.text)) {
      const expectCall = node.expression.expression;
      if (ts.isCallExpression(expectCall) && ts.isIdentifier(expectCall.expression)
          && expectCall.expression.text === "expect"
          && expectCall.arguments.length === 1) {
        const inner = expectCall.arguments[0];
        if (ts.isCallExpression(inner) && callTargetsName(inner)
            && node.arguments.length === 1) {
          const args = inner.arguments.map((a) => literalText(a, sf));
          witnesses.push({ args: args, expected: literalText(node.arguments[0], sf) });
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sf);
  return witnesses;
}

// The leading `/** ... */` JSDoc text of the top-level declaration that defines
// <name> as a single-`throw` stub, or null. The DISJOINT mirror of the
// js-tdd-implement trigger: its contract lives ONLY in this comment block. Read
// straight off the source's leading comment trivia (the same trivia read
// `hasLeadingJSDoc` uses), so it is pure (no type info). Refuses (null) unless
// <name> is defined EXACTLY ONCE as a fillable stub carrying ONE JSDoc block —
// zero/many definitions or zero/many JSDoc blocks is ambiguous, never guessed.
function jsdocTextForStub(sf, name) {
  const full = sf.getFullText();
  const blocks = [];
  function consider(stmtNode, fnNode, declName) {
    if (declName !== name) return;
    if (throwStubBody(fnNode) === null) return;
    const ranges = ts.getLeadingCommentRanges(full, stmtNode.getFullStart()) || [];
    for (const r of ranges) {
      const text = full.slice(r.pos, r.end);
      if (text.startsWith("/**")) blocks.push(text);
    }
  }
  for (const stmt of sf.statements) {
    if (ts.isFunctionDeclaration(stmt) && stmt.name) {
      consider(stmt, stmt, stmt.name.text);
    } else if (ts.isVariableStatement(stmt)) {
      for (const decl of stmt.declarationList.declarations) {
        const init = decl.initializer;
        if (!init || !ts.isIdentifier(decl.name)) continue;
        if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) {
          // The JSDoc on a `const foo = ...` is leading trivia of the STATEMENT.
          consider(stmt, init, decl.name.text);
        }
      }
    }
  }
  // Exactly-one discipline (the JS image of "defined exactly once or refuse").
  return blocks.length === 1 ? blocks[0] : null;
}

// The body text of every `@example` tag inside one JSDoc block, in source order
// — the lines between `@example` and the next tag / the block end, with the
// leading ` * ` margin stripped. Pure string slicing, no type info.
function exampleBodies(jsdoc) {
  const inner = jsdoc.replace(/^\/\*\*/, "").replace(/\*\/$/, "");
  const lines = inner.split("\n").map((line) => line.replace(/^\s*\*?\s?/, ""));
  const bodies = [];
  let current = null;
  for (const line of lines) {
    const tag = line.match(/^@(\w+)\b(.*)$/);
    if (tag) {
      if (current !== null) bodies.push(current);
      current = tag[1] === "example" ? (tag[2].trim() ? tag[2].trim() + "\n" : "") : null;
    } else if (current !== null) {
      current += line + "\n";
    }
  }
  if (current !== null) bodies.push(current);
  return bodies;
}

// One witness `{args, expected}` from a single `@example` expression line for
// <name>, or null. Accepts the two proven shapes (parsing the line as its own
// source so nested commas in array/object args are handled by the real parser):
//   * `<name>(<args...>) === <expected>`  (a strict-equality BinaryExpression)
//   * `expect(<name>(<args...>)).toBe|toEqual|toStrictEqual(<expected>)`
// <name> may be bare or `mod.name(...)`. Any other shape yields null (refuse).
function witnessFromExampleExpr(exprSource, name) {
  const matchers = new Set(["toBe", "toEqual", "toStrictEqual"]);
  const sf = ts.createSourceFile("ex.ts", exprSource, ts.ScriptTarget.Latest, true);
  if ((sf.parseDiagnostics || []).length > 0) return null;
  if (sf.statements.length !== 1 || !ts.isExpressionStatement(sf.statements[0])) return null;
  const expr = sf.statements[0].expression;
  function callTargetsName(callExpr) {
    if (!ts.isCallExpression(callExpr)) return false;
    const fn = callExpr.expression;
    if (ts.isIdentifier(fn)) return fn.text === name;
    if (ts.isPropertyAccessExpression(fn)) return fn.name.text === name;
    return false;
  }
  // `<name>(...) === <expected>`
  if (ts.isBinaryExpression(expr)
      && expr.operatorToken.kind === ts.SyntaxKind.EqualsEqualsEqualsToken
      && callTargetsName(expr.left)) {
    return { args: expr.left.arguments.map((a) => literalText(a, sf)),
             expected: literalText(expr.right, sf) };
  }
  // `expect(<name>(...)).toBe(<expected>)`
  if (ts.isCallExpression(expr) && ts.isPropertyAccessExpression(expr.expression)
      && matchers.has(expr.expression.name.text) && expr.arguments.length === 1) {
    const expectCall = expr.expression.expression;
    if (ts.isCallExpression(expectCall) && ts.isIdentifier(expectCall.expression)
        && expectCall.expression.text === "expect" && expectCall.arguments.length === 1
        && callTargetsName(expectCall.arguments[0])) {
      return { args: expectCall.arguments[0].arguments.map((a) => literalText(a, sf)),
               expected: literalText(expr.arguments[0], sf) };
    }
  }
  return null;
}

// Mine witness tuples for <name> from the stub's OWN JSDoc `@example` block(s) —
// the same `{args, expected}` JSON `mine` emits, but sourced from the JSDoc
// contract instead of a jest test. Each non-blank line of each `@example` body
// is parsed as one expression; a line that is not a recognised shape is SKIPPED
// (so prose around the examples never breaks mining), and a block with NO usable
// example yields no witness (the planner then refuses).
function mineJsdocWitnesses(sf, name) {
  const jsdoc = jsdocTextForStub(sf, name);
  if (jsdoc === null) return [];
  const witnesses = [];
  for (const body of exampleBodies(jsdoc)) {
    for (const raw of body.split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      const w = witnessFromExampleExpr(line, name);
      if (w !== null) witnesses.push(w);
    }
  }
  return witnesses;
}

// True when `node` carries an ES `export` modifier — the only export form
// document-export-jsdoc documents in v0 (a trailing `module.exports`/`export {`
// is out of scope, kept provable). Uses `ts.getModifiers` when present (newer
// TS) and falls back to `node.modifiers` so the same walk works across compiler
// versions.
function isExported(node) {
  const mods = ts.getModifiers ? ts.getModifiers(node) : node.modifiers;
  if (!mods) return false;
  return mods.some((m) => m.kind === ts.SyntaxKind.ExportKeyword);
}

// True when `node` already carries a leading `/** ... */` JSDoc block — read
// straight off the source's leading comment trivia. A node that is already
// documented is SKIPPED (idempotence: a second run finds it documented and
// emits nothing), exactly as document-signature refuses an already-docstringed
// function.
function hasLeadingJSDoc(node, sf) {
  const full = sf.getFullText();
  const ranges = ts.getLeadingCommentRanges(full, node.getFullStart());
  if (!ranges) return false;
  return ranges.some((r) => full.slice(r.pos, r.end).startsWith("/**"));
}

// One documentable target: an EXPORTED, JSDoc-less function/const-arrow with its
// declared param names, the per-param DECLARED type texts (verbatim, or null per
// param), its DECLARED return-type text (verbatim, or null), the DISTINCT thrown
// constructor names of its body in source order (verbatim, or null when an
// unprovable throw shape is present), and the byte offset of its statement start
// (BEFORE the `export` keyword, so the JSDoc lands as leading trivia). `params`
// reuses `paramNames`, so a node with a non-identifier param (destructuring/rest/
// default) yields null and is SKIPPED — we never invent a `@param` name we cannot
// read off the AST. `paramTypes` runs the same gate and so is the SAME length as
// `params` (one verbatim type or null per param) — the js-document-param-types
// objective reads it; document-export-jsdoc ignores it. `throwsTypes` is the
// document-raises-jsdoc fact (the verbatim `@throws {Ctor}` set, or null = refuse);
// the other JSDoc objectives ignore it, exactly as document-export-jsdoc ignores
// `paramTypes`. `returnsInferred` is the js-document-returns-inferred fact (the
// type PROVEN from this function's own literal `return` statements, or null when
// unprovable) — DISJOINT from `returnType` by construction: that field is the
// DECLARED TS annotation (document-export-jsdoc's surface), this is inferred only
// for plain-JS functions a declared annotation does not cover; the Python side
// fires js-document-returns-inferred ONLY when `returnType is None`.
function docTargetFor(name, fnNode, stmtNode, sf) {
  if (!isExported(stmtNode) || hasLeadingJSDoc(stmtNode, sf)) return null;
  const params = paramNames(fnNode);
  if (params === null) return null;
  return {
    name: name,
    params: params,
    paramTypes: paramTypes(fnNode, sf),
    returnType: fnNode.type ? fnNode.type.getText(sf).trim() : null,
    returnsInferred: returnsType(fnNode),
    throwsTypes: throwsTypes(fnNode),
    insertOffset: stmtNode.getStart(sf),
  };
}

// Collect the documentable targets of a source file, in source order: an
// exported `function foo(...) {...}` declaration, or an exported
// `const foo = (...) => ...` / `const foo = function (...) {...}` initializer.
// The insertion offset is the STATEMENT start so the spliced JSDoc precedes the
// `export` keyword. Deterministic (source order), pure AST.
function collectDocTargets(sf) {
  const out = [];
  for (const stmt of sf.statements) {
    if (ts.isFunctionDeclaration(stmt) && stmt.name) {
      const t = docTargetFor(stmt.name.text, stmt, stmt, sf);
      if (t !== null) out.push(t);
    } else if (ts.isVariableStatement(stmt)) {
      for (const decl of stmt.declarationList.declarations) {
        const init = decl.initializer;
        if (!init || !ts.isIdentifier(decl.name)) continue;
        if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) {
          const t = docTargetFor(decl.name.text, init, stmt, sf);
          if (t !== null) out.push(t);
        }
      }
    }
  }
  return out;
}

// The SET of exported function/const-arrow names a source file declares, sorted.
// This is the behaviour-identical oracle's witness: a JSDoc is leading trivia and
// changes ZERO runtime bytes, so splicing one must leave this set unchanged. The
// re-parse path (`doc-verify`) emits it after a clean parse; Python compares the
// pre/post sets and refuses on any drift (it can never differ for a comment
// insert, so a difference means a corrupt splice — refuse rather than land).
function exportedNames(sf) {
  const names = [];
  for (const stmt of sf.statements) {
    if (ts.isFunctionDeclaration(stmt) && stmt.name && isExported(stmt)) {
      names.push(stmt.name.text);
    } else if (ts.isVariableStatement(stmt) && isExported(stmt)) {
      for (const decl of stmt.declarationList.declarations) {
        const init = decl.initializer;
        if (init && ts.isIdentifier(decl.name)
            && (ts.isArrowFunction(init) || ts.isFunctionExpression(init))) {
          names.push(decl.name.text);
        }
      }
    }
  }
  return names.sort();
}

// True when `node` carries a `default` modifier (an `export default function`/
// `export default class` declaration). Read like `isExported`, with the
// `ts.getModifiers`/`node.modifiers` fallback so the same walk works across
// compiler versions. A default-export declaration is the DEFERRED surface for
// js-wire-exports (its only honest "resolves" proof is a node loader), so its
// presence makes wire-targets refuse the whole file.
function hasDefaultModifier(node) {
  const mods = ts.getModifiers ? ts.getModifiers(node) : node.modifiers;
  if (!mods) return false;
  return mods.some((m) => m.kind === ts.SyntaxKind.DefaultKeyword);
}

// The root identifier text of a (possibly nested) property-access LHS, or null —
// e.g. `module.exports.x` -> "module", `exports.y` -> "exports". Used to spot a
// CJS export assignment without caring about the property depth.
function assignmentRootName(expr) {
  let cur = expr;
  while (ts.isPropertyAccessExpression(cur)) {
    cur = cur.expression;
  }
  return ts.isIdentifier(cur) ? cur.text : null;
}

// True when `stmt` is a CJS export assignment — `module.exports.x = ...`,
// `exports.x = ...`, or `module.exports = ...` (the LHS is a property access
// rooted at `module` or `exports`). CJS is the DEFERRED surface (appending a
// statement can change behaviour if `module.exports` is later reassigned), so its
// presence makes wire-targets refuse the whole file; the property NAME is also a
// CJS export, so `allExportedNames` reads it for the oracle's full surface.
function cjsExportTarget(stmt) {
  if (!ts.isExpressionStatement(stmt)) return null;
  const expr = stmt.expression;
  if (!ts.isBinaryExpression(expr)
      || expr.operatorToken.kind !== ts.SyntaxKind.EqualsToken) return null;
  const left = expr.left;
  if (!ts.isPropertyAccessExpression(left)) return null;
  const root = assignmentRootName(left);
  if (root !== "module" && root !== "exports") return null;
  // `module.exports.NAME = ...` / `exports.NAME = ...` export NAME; a bare
  // `module.exports = ...` reassigns the whole object (no single named binding).
  return left.name.text;
}

// True when the file carries ANY CJS (`module.exports`/`exports.`) assignment,
// `export default` (the declaration-modifier form OR the `export default <expr>`
// assignment form), or a TS `export =` — the DEFERRED surfaces. wire-targets
// emits an EMPTY target list for the whole file in that case (v0 is clean-ESM-
// named only), so we never splice an `export ` into a module whose public surface
// is shaped by a form this oracle cannot fully reason about.
function hasCjsOrDefaultExport(sf) {
  for (const stmt of sf.statements) {
    // `export default <expr>` and `export = <expr>` are both ExportAssignment.
    if (ts.isExportAssignment(stmt)) return true;
    // `export default function/class ...` carries a `default` modifier.
    if (hasDefaultModifier(stmt)) return true;
    // `module.exports`/`exports.` assignment (any depth).
    if (cjsExportTarget(stmt) !== null) return true;
    // `export * from "./m"` / `export * as ns from "./m"` re-export names we
    // CANNOT enumerate without a cross-file loader. Their re-exported set is
    // invisible to `allExportedNames`, so a splice could create a duplicate the
    // superset oracle can't see -> defer the WHOLE file (refuse). It is an
    // ExportDeclaration with a moduleSpecifier that is NOT a `export { ... }`
    // named clause (no clause = `export *`; a NamespaceExport clause =
    // `export * as ns`). A `export { a, b as c } from "./m"` IS a NamedExports
    // clause -> names enumerable -> not refused (handled by allExportedNames).
    if (ts.isExportDeclaration(stmt) && stmt.moduleSpecifier
        && !(stmt.exportClause && ts.isNamedExports(stmt.exportClause))) return true;
  }
  return false;
}

// The SET of ALL exported names a source file declares, sorted — the superset of
// `exportedNames`: ESM `export function`/`export const`, the named bindings of a
// trailing `export { a, b as c }` (the EXPORTED name `c`, not the local `b`), and
// CJS `module.exports.NAME`/`exports.NAME`. This is the wire oracle's witness: a
// pure export-surface GROW must leave it equal to the prior set UNION {the one
// added name}, so it must see every form to never miss a name the splice touched.
function allExportedNames(sf) {
  const names = new Set(exportedNames(sf));
  for (const stmt of sf.statements) {
    if (ts.isExportDeclaration(stmt) && stmt.exportClause
        && ts.isNamedExports(stmt.exportClause)) {
      for (const el of stmt.exportClause.elements) {
        names.add(el.name.text);
      }
    } else {
      const cjs = cjsExportTarget(stmt);
      // A bare `module.exports = ...` has property name "exports" off `module`;
      // it names no single binding, so skip it (its root is `module`, prop
      // `exports`). A `module.exports.NAME`/`exports.NAME` names NAME.
      if (cjs !== null && !(cjs === "exports"
          && ts.isPropertyAccessExpression(stmt.expression.left)
          && assignmentRootName(stmt.expression.left.expression) === "module")) {
        names.add(cjs);
      }
    }
  }
  return Array.from(names).sort();
}

// The LOCAL-side identifiers of every TRUE-LOCAL `export { local as pub }` /
// `export { x }` clause (one with NO moduleSpecifier) — the names ALREADY public
// (re-exported) even though the local binding carries no `export` modifier.
// wire-targets must treat these as COLLISIONS so it never re-publishes
// (`export function local`) a helper already exposed under a renamed re-export.
// `el.propertyName` is the local side when an alias is present (`local as pub` ->
// propertyName=local, name=pub); without an alias the local IS `el.name`
// (`export { x }` -> name=x). A clause WITH a moduleSpecifier
// (`export { foo as pub } from "./m"`) is SKIPPED: its identifiers name bindings in
// the OTHER module, not local ones, so they would over-refuse a genuine local of
// the same name. NOT folded into `allExportedNames` (that set is the oracle's
// exported-NAME witness — it must stay the true exported surface `{pub}`, not the
// locals); this is consumed ONLY by `collectWireTargets`.
function reexportedLocalNames(sf) {
  const names = new Set();
  for (const stmt of sf.statements) {
    if (ts.isExportDeclaration(stmt) && stmt.exportClause
        && ts.isNamedExports(stmt.exportClause)) {
      // A CROSS-MODULE re-export `export { foo as pub } from "./m"` carries a
      // moduleSpecifier: there `foo` is a name in `./m`, NOT a local binding, so it
      // must not mark a genuine local `foo` as already-public (that would
      // over-refuse wiring it). Only a TRUE-LOCAL re-export `export { foo as pub };`
      // (no specifier) re-publishes a local binding and belongs in the collision set.
      if (stmt.moduleSpecifier) continue;
      for (const el of stmt.exportClause.elements) {
        names.add(el.propertyName ? el.propertyName.text : el.name.text);
      }
    }
  }
  return names;
}

// One wireable target: a top-level PUBLIC function/const-arrow that is DEFINED but
// NOT exported, NOT private (`_`-prefixed), and NOT already named in the file's
// FULL exported-name set (so we never double-export). `kind` is "function" or
// "const" (advisory/audit — the splice just prepends `export `); `insertOffset` is
// the STATEMENT start, where prepending `export ` publishes the binding. `params`
// reuses the `paramNames` identifier gate so a node we cannot read off the AST is
// SKIPPED — never wire a name we cannot resolve structurally.
function wireTargetFor(name, fnNode, stmtNode, sf, kind, alreadyExported) {
  if (isExported(stmtNode)) return null;             // already exported -> skip
  if (name.startsWith("_")) return null;             // private -> not public surface
  if (alreadyExported.has(name)) return null;        // collides with an export -> skip
  if (paramNames(fnNode) === null) return null;      // unreadable binding -> skip
  return { name: name, kind: kind, insertOffset: stmtNode.getStart(sf) };
}

// Collect the wireable targets of a source file, in source order: an un-exported
// `function foo(...) {...}` declaration, or an un-exported `const foo = (...) =>
// ...` / `const foo = function (...) {...}` initializer, each PUBLIC and not
// otherwise exported. REFUSES the WHOLE file (empty list) when any CJS/default/
// `export =` form is present (the deferred surface). Deterministic (source order),
// pure AST.
function collectWireTargets(sf) {
  if (hasCjsOrDefaultExport(sf)) return [];
  // The collision set = the true exported-NAME surface PLUS the LOCAL side of
  // every `export { local as pub }` re-export (already public though the binding
  // carries no `export` modifier) — so we never double-export a renamed re-export.
  const alreadyExported = new Set(allExportedNames(sf));
  for (const local of reexportedLocalNames(sf)) alreadyExported.add(local);
  const out = [];
  for (const stmt of sf.statements) {
    if (ts.isFunctionDeclaration(stmt) && stmt.name) {
      const t = wireTargetFor(stmt.name.text, stmt, stmt, sf, "function", alreadyExported);
      if (t !== null) out.push(t);
    } else if (ts.isVariableStatement(stmt)) {
      for (const decl of stmt.declarationList.declarations) {
        const init = decl.initializer;
        if (!init || !ts.isIdentifier(decl.name)) continue;
        if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) {
          const t = wireTargetFor(decl.name.text, init, stmt, sf, "const", alreadyExported);
          if (t !== null) out.push(t);
        }
      }
    }
  }
  return out;
}

// --- js-cover-gaps: the PURITY (env/clock/IO-reproducibility) AST pre-filter ---
//
// A characterization test pins `fn(args) === <captured>`. If the captured value
// depends on the clock / a random source / the environment / IO, the assertion
// passes ONCE then goes RED later — a FLAKY test, the moat's cardinal "fake-green"
// sin. This scan is the cheap FIRST guard (the heavier env-reproducibility
// re-capture gate on the Python side is the second, load-bearing one): it REFUSES
// (returns false) the moment the function's OWN-SCOPE body references a known
// non-deterministic source OR any FREE identifier it cannot prove is a param /
// local / its own name / a small allow-list of provably-pure globals. Refuse-on-
// uncertainty: an unknown free identifier is a possible closure over external
// mutable state (non-reproducible), so it makes the target impure. Only the ROOT
// function's own scope is scanned for free vars (a nested function introduces its
// own scope), but a FORBIDDEN reference anywhere in the body — including inside a
// nested arrow — still taints the target (a nested `() => Date.now()` the root
// returns is just as flaky).

// Member-access ROOTS that are never pure to pin: a value derived from any of
// these reads the clock / randomness / the process env / IO / the network, so a
// captured return embedding it is not reproducible. Matches `Date.now()`,
// `Math.random()`, `process.env`, `performance.now()`, `crypto.*`, `fs.*`,
// `os.*`, `globalThis.*`, ... — the JS image of test_shield's clock/IO refusals.
const _FORBIDDEN_ROOTS = new Set([
  "Date", "Math", "process", "performance", "crypto", "fs", "fsPromises",
  "os", "globalThis", "global", "window", "self", "navigator", "document",
  "fetch", "XMLHttpRequest", "WebSocket", "require", "module", "exports",
  "__dirname", "__filename", "Intl", "Reflect", "WeakMap", "WeakSet",
  "WeakRef", "FinalizationRegistry", "Promise", "Symbol", "Proxy", "eval",
]);

// Bare callee identifiers that are non-deterministic / impure even called free
// (no member root): `eval`, `fetch`, `require`, `setTimeout`/`setInterval`
// (timing), `structuredClone` (fine, but conservatively excluded as a global we
// don't model). Most impure calls are member calls caught by `_FORBIDDEN_ROOTS`;
// this catches the bare-global forms.
const _FORBIDDEN_FREE = new Set([
  "eval", "fetch", "require", "import", "setTimeout", "setInterval",
  "setImmediate", "queueMicrotask",
]);

// The provably-pure GLOBALS a body may reference free without tainting the
// capture: the value constructors / pure helpers whose result is deterministic
// and JSON-stable (`Math` is NOT here — `Math.random` is forbidden, and a member
// access is checked separately, so a free `Math` identifier is conservatively
// refused). Deliberately small — refuse-on-uncertainty means an unknown free name
// is impure, so this list only whitelists the few whose purity is certain. Note
// `Math`/`Date`/`Promise`/`Symbol`/`crypto` are EXCLUDED (in `_FORBIDDEN_ROOTS`):
// even `new Date()` or `Math.PI`-via-`Math` is refused so a clock/PI-free-id slip
// can't happen.
const _PURE_GLOBALS = new Set([
  "Number", "String", "Boolean", "Array", "Object", "JSON", "parseInt",
  "parseFloat", "isNaN", "isFinite", "Infinity", "NaN", "undefined",
  "Map", "Set", "RegExp", "Error", "TypeError", "RangeError", "SyntaxError",
  "EvalError", "ReferenceError", "URIError", "encodeURIComponent",
  "decodeURIComponent", "encodeURI", "decodeURI",
]);

// Collect the names a function-like node BINDS in its OWN scope: its parameters
// (incl. defaulted/destructured pattern bindings), and the var/let/const,
// function, class and catch bindings declared anywhere inside its body that are
// NOT inside a deeper nested function (those belong to the nested scope). The
// function's own name (a named function declaration/expression) is added by the
// caller. Used so the free-identifier scan only flags names the body does not
// itself define. Conservative: a name BOUND here is treated as local even if it
// shadows a global (correct — the shadow is what runs).
function collectBoundNames(node) {
  const bound = new Set();
  function addBindingName(name) {
    if (ts.isIdentifier(name)) {
      bound.add(name.text);
    } else if (ts.isObjectBindingPattern(name) || ts.isArrayBindingPattern(name)) {
      for (const el of name.elements) {
        if (ts.isBindingElement(el)) addBindingName(el.name);
      }
    }
  }
  for (const p of node.parameters) addBindingName(p.name);
  function walk(n, isRoot) {
    if (!isRoot && ts.isFunctionLike(n)) {
      // A nested function's own name leaks into THIS scope (a hoisted
      // declaration / named expression is visible here), but its body/params are
      // its own scope — record the name, do not descend.
      if ((ts.isFunctionDeclaration(n) || ts.isFunctionExpression(n)) && n.name) {
        bound.add(n.name.text);
      }
      return;
    }
    if (ts.isVariableDeclaration(n) || ts.isBindingElement(n)) addBindingName(n.name);
    if ((ts.isFunctionDeclaration(n) || ts.isClassDeclaration(n)) && n.name) {
      bound.add(n.name.text);
    }
    if (ts.isCatchClause(n) && n.variableDeclaration) {
      addBindingName(n.variableDeclaration.name);
    }
    ts.forEachChild(n, (child) => walk(child, false));
  }
  if (node.body) walk(node.body, true);
  return bound;
}

// True when `node` is a PURE characterization target: its body references no
// forbidden (clock/random/env/IO/network) source and no FREE identifier outside
// the param/local/own-name set and the pure-globals allow-list. This is the AST
// pre-filter; the Python env-reproducibility re-capture gate is the load-bearing
// second layer. Refuse-on-uncertainty: ANY unrecognised free identifier, member
// access rooted at a forbidden global, or forbidden bare call makes it false.
function isPureTarget(node, ownName) {
  if (!node.body) return false;
  const bound = collectBoundNames(node);
  if (ownName) bound.add(ownName);
  let pure = true;
  function rootIdentifierOf(expr) {
    let cur = expr;
    while (ts.isPropertyAccessExpression(cur) || ts.isElementAccessExpression(cur)) {
      cur = cur.expression;
    }
    return ts.isIdentifier(cur) ? cur : null;
  }
  function isBindingNameId(id) {
    // An identifier that is the NAME side of a property/binding/param/label is
    // not a free VALUE reference — skip it (e.g. `{a: x}` key `a`, `obj.prop`
    // member `prop`, a `case` label). Only value-position identifiers count.
    const p = id.parent;
    if (!p) return false;
    if (ts.isPropertyAccessExpression(p) && p.name === id) return true;  // `.prop`
    if (ts.isQualifiedName(p) && p.right === id) return true;
    if ((ts.isPropertyAssignment(p) || ts.isPropertySignature(p)
         || ts.isShorthandPropertyAssignment(p)) && p.name === id
        && !ts.isShorthandPropertyAssignment(p)) return true;  // object KEY (non-shorthand)
    if (ts.isBindingElement(p) && p.propertyName === id) return true;  // `{a: b}` key in pattern
    if (ts.isParameter(p) || ts.isBindingElement(p)) {
      if (p.name === id) return true;  // a binding NAME, not a reference
    }
    if (ts.isVariableDeclaration(p) && p.name === id) return true;
    if (ts.isFunctionDeclaration(p) && p.name === id) return true;
    if (ts.isClassDeclaration(p) && p.name === id) return true;
    return false;
  }
  function visit(n) {
    if (!pure) return;
    // A member/element access rooted at a forbidden global (`Date.now`,
    // `process.env`, `Math.random` ...) taints the capture.
    if (ts.isPropertyAccessExpression(n) || ts.isElementAccessExpression(n)) {
      const root = rootIdentifierOf(n);
      if (root && !bound.has(root.text) && _FORBIDDEN_ROOTS.has(root.text)) {
        pure = false;
        return;
      }
    }
    // A dynamic `import(...)` expression is IO — refuse.
    if (n.kind === ts.SyntaxKind.ImportKeyword) { pure = false; return; }
    if (ts.isCallExpression(n) && n.expression
        && n.expression.kind === ts.SyntaxKind.ImportKeyword) { pure = false; return; }
    // A free VALUE identifier: not bound locally, not a pure global -> refuse.
    if (ts.isIdentifier(n) && !isBindingNameId(n)) {
      const name = n.text;
      if (bound.has(name)) {
        // local / param / own-name — fine
      } else if (_FORBIDDEN_FREE.has(name) || _FORBIDDEN_ROOTS.has(name)) {
        pure = false; return;
      } else if (!_PURE_GLOBALS.has(name)) {
        pure = false; return;  // unknown free identifier -> refuse-on-uncertainty
      }
    }
    ts.forEachChild(n, visit);
  }
  visit(node.body);
  return pure;
}

// True when `node` carries ANY decorator — a decorator may change the call
// contract entirely (the JS image of test_shield's `node.decorator_list` skip), so
// a decorated target is refused. `ts.getDecorators` (newer TS) with the
// `node.modifiers`/`node.decorators` fallback for older compiler versions.
function hasDecorator(node) {
  if (ts.canHaveDecorators && ts.canHaveDecorators(node) && ts.getDecorators) {
    const decs = ts.getDecorators(node);
    if (decs && decs.length > 0) return true;
  }
  if (node.decorators && node.decorators.length > 0) return true;
  const mods = node.modifiers || [];
  return mods.some((m) => m.kind === ts.SyntaxKind.Decorator);
}

// One CHARACTERIZATION target: an EXPORTED, public (non-`_`), undecorated,
// NON-async, NON-generator function/const-arrow with its parameter infos
// (name + verbatim type + verbatim literal default), a `pure` flag (the AST
// forbidden-call/free-identifier scan), and the export ADDRESSING the capture
// child needs (`exportKind`: "named" for an ESM/CJS-named export). `params` reuses
// the `coverParamInfos` identifier-or-defaulted gate, so a destructuring/rest param
// makes it null and the target is SKIPPED — never characterize a call we cannot
// build args for. A function whose name starts with `_` is private (not part of
// the public surface), and `main` is skipped (its contract is a CLI entry, like
// test_shield skips Python `main`). The Python side decides the SOUND input slice
// from `params` + `pure` and refuses the rest.
function coverTargetFor(name, fnNode, stmtNode, sf, exportKind) {
  if (name.startsWith("_") || name === "main") return null;       // private / CLI entry
  if (hasDecorator(stmtNode) || hasDecorator(fnNode)) return null; // decorated -> skip
  if (isAsync(fnNode)) return null;                                // async -> bare call is a Promise
  if (fnNode.asteriskToken) return null;                           // generator -> returns an iterator
  const params = coverParamInfos(fnNode, sf);
  if (params === null) return null;                                // unreadable params -> skip
  return {
    name: name,
    params: params,
    pure: isPureTarget(fnNode, name),
    exportKind: exportKind,
  };
}

// The top-level function/const-arrow DECLARATIONS of a source file, mapped by
// name to `{fnNode, stmtNode}`. Used to RESOLVE a CJS reference export
// (`module.exports.foo = foo` / `module.exports = { foo }`) to the declaration the
// name binds, so we can characterize it by its provable AST. Only a name defined
// EXACTLY ONCE as a top-level function/arrow is recorded (a re-declared name is
// ambiguous and dropped). Pure AST.
function topLevelFunctionDecls(sf) {
  const map = new Map();
  const dup = new Set();
  function record(name, fnNode, stmtNode) {
    if (map.has(name)) { dup.add(name); return; }
    map.set(name, { fnNode: fnNode, stmtNode: stmtNode });
  }
  for (const stmt of sf.statements) {
    if (ts.isFunctionDeclaration(stmt) && stmt.name) {
      record(stmt.name.text, stmt, stmt);
    } else if (ts.isVariableStatement(stmt)) {
      for (const decl of stmt.declarationList.declarations) {
        const init = decl.initializer;
        if (init && ts.isIdentifier(decl.name)
            && (ts.isArrowFunction(init) || ts.isFunctionExpression(init))) {
          record(decl.name.text, init, stmt);
        }
      }
    }
  }
  for (const name of dup) map.delete(name);  // ambiguous re-declaration -> drop
  return map;
}

// Collect the characterization targets of a source file, in source order. The
// EXPORTED, characterizable function/const-arrow declarations a capture child can
// reach as `mod.NAME` after transpile/require. FOUR addressing forms, all NAMED
// (never `default`/`export =`, the deferred surface):
//   * ESM `export function foo(...){...}` / `export const foo = (...) => ...`;
//   * inline CJS `module.exports.NAME = function...` / `exports.NAME = (...) => ...`
//     (the RHS is the function itself);
//   * REFERENCE CJS `module.exports.NAME = ident` / `exports.NAME = ident`, where
//     `ident` resolves to a top-level function/arrow declaration (`coverTargetFor`
//     is applied to the DECLARATION's node, under the EXPORTED name `NAME`);
//   * OBJECT CJS `module.exports = { foo, bar: baz }`, where each property value is
//     a bare identifier resolving to a top-level function/arrow declaration (the
//     EXPORTED name is the property key). A bare `module.exports = ident` /
//     `module.exports = expr` that is not an object literal names no single binding
//     and is skipped (export-addressing ambiguity -> refuse).
// The single-`package.json` gate + non-test source gate live on the Python side;
// here we only enumerate. Deterministic (source order), pure AST. A name reached by
// more than one form is emitted once (first occurrence). The Python side resolves
// addressing by name (`mod.NAME`), so the EXPORTED key — not the local — is used.
function collectCoverTargets(sf) {
  const decls = topLevelFunctionDecls(sf);
  const out = [];
  const seen = new Set();
  function push(t) {
    if (t !== null && !seen.has(t.name)) { seen.add(t.name); out.push(t); }
  }
  // A target reached by an EXPORTED name `pubName` whose function body is `fnNode`
  // (declared at `stmtNode`). `coverTargetFor` re-checks public/decorator/async/
  // generator/param gates and computes purity off the declaration's own node.
  function pushNamed(pubName, fnNode, stmtNode) {
    push(coverTargetFor(pubName, fnNode, stmtNode, sf, "named"));
  }
  // Resolve a bare identifier export to its top-level function declaration, under
  // the EXPORTED name `pubName` (which may differ from the local for an alias).
  function pushByRef(pubName, localName) {
    const d = decls.get(localName);
    if (d) pushNamed(pubName, d.fnNode, d.stmtNode);
  }
  for (const stmt of sf.statements) {
    if (ts.isFunctionDeclaration(stmt) && stmt.name && isExported(stmt)) {
      pushNamed(stmt.name.text, stmt, stmt);
    } else if (ts.isVariableStatement(stmt) && isExported(stmt)) {
      for (const decl of stmt.declarationList.declarations) {
        const init = decl.initializer;
        if (init && ts.isIdentifier(decl.name)
            && (ts.isArrowFunction(init) || ts.isFunctionExpression(init))) {
          pushNamed(decl.name.text, init, stmt);
        }
      }
    } else if (ts.isExpressionStatement(stmt) && ts.isBinaryExpression(stmt.expression)
               && stmt.expression.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
      const expr = stmt.expression;
      const lhs = expr.left;
      const rhs = expr.right;
      if (ts.isPropertyAccessExpression(lhs)) {
        const root = assignmentRootName(lhs);
        if ((root === "module" || root === "exports") && lhs.name) {
          const pub = lhs.name.text;
          if (pub === "exports") {
            // `module.exports = ...` (root `module`, prop `exports`): a whole-object
            // assignment, handled by the object-literal branch below.
          } else if (ts.isArrowFunction(rhs) || ts.isFunctionExpression(rhs)) {
            pushNamed(pub, rhs, stmt);                  // inline CJS
          } else if (ts.isIdentifier(rhs)) {
            pushByRef(pub, rhs.text);                   // reference CJS
          }
        }
      }
      // `module.exports = { foo, bar: baz }` — an object literal whose property
      // values are bare identifiers resolving to top-level function declarations.
      const isWholeExports = ts.isPropertyAccessExpression(lhs)
        && assignmentRootName(lhs) === "module" && lhs.name && lhs.name.text === "exports"
        && !ts.isPropertyAccessExpression(lhs.expression);
      const isBareExports = ts.isIdentifier(lhs) && lhs.text === "exports";
      if ((isWholeExports || isBareExports) && ts.isObjectLiteralExpression(rhs)) {
        for (const prop of rhs.properties) {
          if (ts.isShorthandPropertyAssignment(prop)) {
            pushByRef(prop.name.text, prop.name.text);          // { foo }
          } else if (ts.isPropertyAssignment(prop) && ts.isIdentifier(prop.name)
                     && ts.isIdentifier(prop.initializer)) {
            pushByRef(prop.name.text, prop.initializer.text);   // { pub: local }
          } else if (ts.isPropertyAssignment(prop) && ts.isIdentifier(prop.name)
                     && (ts.isArrowFunction(prop.initializer)
                         || ts.isFunctionExpression(prop.initializer))) {
            pushNamed(prop.name.text, prop.initializer, stmt);  // { pub: () => ... }
          }
        }
      }
    }
  }
  return out;
}

// --- js-strengthen-tests: the read-only single-token MUTATION seeder ----------
//
// The gap-FINDER for js-strengthen-tests (the LITE mined-witness variant). Given
// the name of one exported PURE function, locate the single-token operator/constant
// spans in its OWN body and emit a fixed, deterministic catalog of MUTANTS — each a
// UTF-16-code-unit span splice the Python side applies to an IN-MEMORY copy (NEVER
// persisted). The catalog MIRRORS the Python `mutation_tester` operator set:
// comparison flips (`===`->`!==`, `<`->`>=`, ...), the off-by-one BOUNDARY flips
// (`<`->`<=`), arithmetic (`+`->`-`), boolean (`&&`->`||`), bool-const (true<->false),
// numeric `n`->`n+1`, and `return X`->`return undefined`. Each mutant is a gap-finder
// ONLY: the Python side decides SURVIVAL against the function's MINED test witnesses
// (no per-mutant buyer-suite run) and lands a single env-gated characterization
// assertion that kills a survivor. Deterministic: sites in document (offset) order,
// a fixed per-token catalog, a fixed cap — no clock, no randomness.

// The cap on mutants emitted per function — a fixed bound (no clock/random) so a
// huge body's seed set stays bounded and deterministic. Mirrors the spirit of the
// Python mutation engine's own per-module cap.
const _MUTANT_CAP = 40;

// Comparison-operator flips, keyed by the VERBATIM operator-token text (read via
// `operatorToken.getText` so the `<`-is-`FirstBinaryOperator` kind-alias never
// trips us). Each maps the written token to the negated/flipped token. The JS image
// of mutation_tester's `_COMPARE_FLIPS` (`===`/`!==` are the JS strict forms).
const _COMPARE_FLIPS = {
  "===": "!==", "!==": "===", "==": "!=", "!=": "==",
  "<": ">=", ">=": "<", ">": "<=", "<=": ">",
};

// Comparison BOUNDARY flips — the off-by-one fault class (`<`<->`<=`, `>`<->`>=`),
// distinct from the negation flips above and carried under a distinct operator label
// so the two never collide. The JS image of `_COMPARE_BOUNDARY_FLIPS`.
const _COMPARE_BOUNDARY_FLIPS = {
  "<": "<=", "<=": "<", ">": ">=", ">=": ">",
};

// Arithmetic-operator flips on a binary expression. The JS image of `_BINOP_FLIPS`.
const _BINOP_FLIPS = { "+": "-", "-": "+", "*": "/", "/": "*" };

// Boolean-connective flips on a binary expression (`&&`/`||`). The JS image of
// `_BOOLOP_FLIPS` (`and`/`or` in Python).
const _BOOLOP_FLIPS = { "&&": "||", "||": "&&" };

// A binary-operator token's catalog mutations, as `[{operator, mutated}]` in a
// fixed order: comparison flip first, then boundary, then arithmetic, then boolean.
// A token appears under at most the categories that define it (a `<` yields both a
// `comparison:` and a `boundary:` mutant — exactly like the Python engine seeds both
// at one site). Pure table lookups, no clock/random.
function binaryOpMutations(opText) {
  const out = [];
  if (Object.prototype.hasOwnProperty.call(_COMPARE_FLIPS, opText)) {
    out.push({ operator: "comparison:" + opText, mutated: _COMPARE_FLIPS[opText] });
  }
  if (Object.prototype.hasOwnProperty.call(_COMPARE_BOUNDARY_FLIPS, opText)) {
    out.push({ operator: "boundary:" + opText, mutated: _COMPARE_BOUNDARY_FLIPS[opText] });
  }
  if (Object.prototype.hasOwnProperty.call(_BINOP_FLIPS, opText)) {
    out.push({ operator: "arith:" + opText, mutated: _BINOP_FLIPS[opText] });
  }
  if (Object.prototype.hasOwnProperty.call(_BOOLOP_FLIPS, opText)) {
    out.push({ operator: "boolop:" + opText, mutated: _BOOLOP_FLIPS[opText] });
  }
  return out;
}

// Collect the single-token mutants of a function-like node's body, in document
// order. Each entry is `{operator, original, mutated, start, end}` where
// `start`/`end` are the UTF-16 code-unit span of the token to splice (the Python
// side re-indexes them to code points). Walks the WHOLE body subtree (a mutant
// anywhere in the body is a valid gap-finder), collecting:
//   * binary-operator tokens -> comparison/boundary/arith/boolean flips;
//   * `true`/`false` keyword tokens -> the bool-const flip;
//   * numeric literals -> `n`->`<n+1>` (a deterministic numeric perturbation);
//   * a `return <expr>` whose expression is not already `undefined`/void ->
//     `return undefined` (splice the EXPRESSION span with `undefined`).
// The site list is sorted by (start, operator) and capped at `_MUTANT_CAP`, so the
// emission is deterministic and bounded.
function collectMutants(fnNode, sf) {
  const body = fnNode.body;
  if (!body) return [];
  const out = [];
  function pushSpan(operator, original, mutated, start, end) {
    out.push({ operator: operator, original: original, mutated: mutated,
               start: start, end: end });
  }
  function visit(n) {
    if (ts.isBinaryExpression(n)) {
      const tok = n.operatorToken;
      const opText = tok.getText(sf);
      const start = tok.getStart(sf);
      const end = tok.getEnd();
      for (const m of binaryOpMutations(opText)) {
        pushSpan(m.operator, opText, m.mutated, start, end);
      }
    }
    // A bare `true`/`false` keyword (a value-position boolean constant).
    if (n.kind === ts.SyntaxKind.TrueKeyword || n.kind === ts.SyntaxKind.FalseKeyword) {
      const isTrue = n.kind === ts.SyntaxKind.TrueKeyword;
      pushSpan("boolconst:" + (isTrue ? "true" : "false"),
               isTrue ? "true" : "false", isTrue ? "false" : "true",
               n.getStart(sf), n.getEnd());
    }
    // A numeric literal -> n+1 (a deterministic single-step perturbation). Only a
    // plain decimal integer/float we can re-emit as `Number(text) + 1` is mutated;
    // a non-finite or unparseable literal is skipped (conservative).
    if (ts.isNumericLiteral(n)) {
      const text = n.getText(sf);
      const val = Number(text);
      if (Number.isFinite(val)) {
        // Integer -> integer+1; otherwise the parsed value + 1 (still a literal).
        const next = Number.isInteger(val) ? String(val + 1) : String(val + 1);
        pushSpan("number:" + text, text, next, n.getStart(sf), n.getEnd());
      }
    }
    // `return <expr>` -> `return undefined` (splice the EXPRESSION span). Skip a
    // bare `return;` (no expression) and an already-`undefined` return (no fault).
    if (ts.isReturnStatement(n) && n.expression) {
      const exprText = n.expression.getText(sf);
      if (exprText !== "undefined") {
        pushSpan("return:undefined", exprText, "undefined",
                 n.expression.getStart(sf), n.expression.getEnd());
      }
    }
    ts.forEachChild(n, visit);
  }
  visit(body);
  // Deterministic order: by span start, then operator label (a token with two
  // mutants — e.g. a `<` comparison + boundary — orders them by label). Capped.
  out.sort((a, b) => (a.start - b.start) || (a.operator < b.operator ? -1
                      : a.operator > b.operator ? 1 : 0));
  return out.slice(0, _MUTANT_CAP);
}

// Resolve one EXPORTED, characterizable target by NAME to its function-like node,
// or null. Reuses `collectCoverTargets`'s addressing (ESM + CJS named/reference/
// object exports) by re-walking the SAME declaration map: the strengthen seeder
// only mutates a function that `cover-targets` would also surface (an exported,
// public, undecorated, non-async, non-generator, param-readable target), so the two
// objectives agree on what a target IS. Returns the function-like node whose body
// is mutated. Pure AST, deterministic (first matching declaration).
function resolveCoverTargetNode(sf, name) {
  const targets = collectCoverTargets(sf);
  if (!targets.some((t) => t.name === name)) return null;  // not a cover target
  // Re-walk to find the function NODE bound to `name` (collectCoverTargets returns
  // facts, not nodes). Mirror its addressing so the node matches the surfaced name.
  const decls = topLevelFunctionDecls(sf);
  let found = null;
  function consider(pubName, fnNode) {
    if (found === null && pubName === name) found = fnNode;
  }
  for (const stmt of sf.statements) {
    if (ts.isFunctionDeclaration(stmt) && stmt.name && isExported(stmt)) {
      consider(stmt.name.text, stmt);
    } else if (ts.isVariableStatement(stmt) && isExported(stmt)) {
      for (const decl of stmt.declarationList.declarations) {
        const init = decl.initializer;
        if (init && ts.isIdentifier(decl.name)
            && (ts.isArrowFunction(init) || ts.isFunctionExpression(init))) {
          consider(decl.name.text, init);
        }
      }
    } else if (ts.isExpressionStatement(stmt) && ts.isBinaryExpression(stmt.expression)
               && stmt.expression.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
      const lhs = stmt.expression.left;
      const rhs = stmt.expression.right;
      if (ts.isPropertyAccessExpression(lhs)) {
        const root = assignmentRootName(lhs);
        if ((root === "module" || root === "exports") && lhs.name && lhs.name.text !== "exports") {
          if (ts.isArrowFunction(rhs) || ts.isFunctionExpression(rhs)) {
            consider(lhs.name.text, rhs);
          } else if (ts.isIdentifier(rhs)) {
            const d = decls.get(rhs.text);
            if (d) consider(lhs.name.text, d.fnNode);
          }
        }
      }
      const isWholeExports = ts.isPropertyAccessExpression(lhs)
        && assignmentRootName(lhs) === "module" && lhs.name && lhs.name.text === "exports"
        && !ts.isPropertyAccessExpression(lhs.expression);
      const isBareExports = ts.isIdentifier(lhs) && lhs.text === "exports";
      if ((isWholeExports || isBareExports) && ts.isObjectLiteralExpression(rhs)) {
        for (const prop of rhs.properties) {
          if (ts.isShorthandPropertyAssignment(prop)) {
            const d = decls.get(prop.name.text);
            if (d) consider(prop.name.text, d.fnNode);
          } else if (ts.isPropertyAssignment(prop) && ts.isIdentifier(prop.name)
                     && ts.isIdentifier(prop.initializer)) {
            const d = decls.get(prop.initializer.text);
            if (d) consider(prop.name.text, d.fnNode);
          } else if (ts.isPropertyAssignment(prop) && ts.isIdentifier(prop.name)
                     && (ts.isArrowFunction(prop.initializer)
                         || ts.isFunctionExpression(prop.initializer))) {
            consider(prop.name.text, prop.initializer);
          }
        }
      }
    }
  }
  return found;
}

function fail(message) {
  process.stderr.write(String(message) + "\n");
  process.exit(REFUSE);
}

function readSource(file) {
  let source;
  try {
    source = fs.readFileSync(file, "utf8");
  } catch (e) {
    fail("cannot read " + file);
  }
  const sf = parse(file, source);
  // A file the TS parser cannot make sense of yields a syntactic diagnostic; we
  // treat ANY parse diagnostic as a refusal (never edit a file we can't model).
  const diags = sf.parseDiagnostics || [];
  if (diags.length > 0) fail("parse error in " + file);
  return { source: source, sf: sf };
}

function cmdScan(file) {
  const { sf } = readSource(file);
  process.stdout.write(JSON.stringify(collectStubs(sf)));
}

function cmdMine(file, name) {
  const { sf } = readSource(file);
  process.stdout.write(JSON.stringify(mineWitnesses(sf, name)));
}

function cmdMineJsdoc(file, name) {
  const { sf } = readSource(file);
  process.stdout.write(JSON.stringify(mineJsdocWitnesses(sf, name)));
}

function cmdFill(file, name, body) {
  const { source, sf } = readSource(file);
  const stubs = collectStubs(sf).filter((s) => s.name === name);
  // Exactly-one-definition discipline (the JS image of cross_file_rename's
  // "defined exactly once or refuse"): zero or many matches is ambiguous.
  if (stubs.length !== 1) {
    fail("'" + name + "' is not defined exactly once as a fillable stub");
  }
  const stub = stubs[0];
  const replacement = "{ " + body + " }";
  const next = source.slice(0, stub.bodyStart) + replacement + source.slice(stub.bodyEnd);
  fs.writeFileSync(file, next, "utf8");
  process.stdout.write(JSON.stringify({
    name: name,
    bodyStart: stub.bodyStart,
    bodyEnd: stub.bodyEnd,
  }));
}

function cmdDocTargets(file) {
  const { sf } = readSource(file);
  process.stdout.write(JSON.stringify(collectDocTargets(sf)));
}

function cmdDocVerify(file) {
  const { sf } = readSource(file);
  // readSource already refused (exit 2) on any parse diagnostic, so reaching here
  // proves the file parses; emit its exported-name set for the Python oracle.
  process.stdout.write(JSON.stringify({ names: exportedNames(sf) }));
}

function cmdWireTargets(file) {
  const { sf } = readSource(file);
  process.stdout.write(JSON.stringify(collectWireTargets(sf)));
}

function cmdWireVerify(file) {
  const { sf } = readSource(file);
  // readSource already refused (exit 2) on any parse diagnostic, so reaching here
  // proves the file parses; emit its FULL exported-name set for the superset
  // oracle (Python proves the post-splice set == prior set UNION {the added name}).
  process.stdout.write(JSON.stringify({ names: allExportedNames(sf) }));
}

function cmdCoverTargets(file) {
  const { sf } = readSource(file);
  process.stdout.write(JSON.stringify(collectCoverTargets(sf)));
}

function cmdMutate(file, name) {
  const { sf } = readSource(file);
  // <name> must resolve to an EXPORTED cover target (the same surface js-cover-gaps
  // characterizes); otherwise emit an empty mutant list (the Python side refuses).
  const fnNode = resolveCoverTargetNode(sf, name);
  if (fnNode === null) {
    process.stdout.write(JSON.stringify([]));
    return;
  }
  process.stdout.write(JSON.stringify(collectMutants(fnNode, sf)));
}

function main() {
  const argv = process.argv.slice(2);
  const sub = argv[0];
  if (sub === "scan" && argv.length === 2) return cmdScan(argv[1]);
  if (sub === "mine" && argv.length === 3) return cmdMine(argv[1], argv[2]);
  if (sub === "mine-jsdoc" && argv.length === 3) return cmdMineJsdoc(argv[1], argv[2]);
  if (sub === "fill" && argv.length === 4) return cmdFill(argv[1], argv[2], argv[3]);
  if (sub === "doc-targets" && argv.length === 2) return cmdDocTargets(argv[1]);
  if (sub === "doc-verify" && argv.length === 2) return cmdDocVerify(argv[1]);
  if (sub === "wire-targets" && argv.length === 2) return cmdWireTargets(argv[1]);
  if (sub === "wire-verify" && argv.length === 2) return cmdWireVerify(argv[1]);
  if (sub === "cover-targets" && argv.length === 2) return cmdCoverTargets(argv[1]);
  if (sub === "mutate" && argv.length === 3) return cmdMutate(argv[1], argv[2]);
  fail("usage: ts_driver.js scan <file> | mine <file> <name> "
       + "| mine-jsdoc <file> <name> | fill <file> <name> <body> "
       + "| doc-targets <file> | doc-verify <file> | wire-targets <file> | wire-verify <file> "
       + "| cover-targets <file> | mutate <file> <name>");
}

main();
