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
//                             paramTypes, returnType|null, throwsTypes|null,
//                             insertOffset}] — the facts the document-export-jsdoc
//                             (names + returnType), js-document-param-types (the
//                             verbatim per-param `paramTypes`) and
//                             document-raises-jsdoc (the `throwsTypes` set) objectives
//                             splice a minimal JSDoc from (pure AST). `paramTypes` is
//                             parallel to `params` (one verbatim type or null per
//                             param). `throwsTypes` is the DISTINCT thrown constructor
//                             names in source order — but ONLY when EVERY `throw` in
//                             the body is a literal `new <Identifier>(...)`; any other
//                             throw shape makes it null (the document-raises-jsdoc
//                             refusal). Exit 2 on parse error.
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
//
// Determinism: no clock, no randomness; functions are reported in source order;
// JSON keys are emitted in a fixed order. A byte-span splice (getStart/getEnd),
// never an AST unparse, so the surrounding source is untouched.

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
function throwsTypes(node) {
  const body = node.body;
  if (!body || !ts.isBlock(body)) return [];
  const seen = new Set();
  const names = [];
  let provable = true;
  function visit(n) {
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
    ts.forEachChild(n, visit);
  }
  visit(body);
  return provable ? names : null;
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
// initializer. Each carries its name, plain param names, and the BYTE span of
// its body block (start = the `{`, end = just past the `}`).
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
// `paramTypes`.
function docTargetFor(name, fnNode, stmtNode, sf) {
  if (!isExported(stmtNode) || hasLeadingJSDoc(stmtNode, sf)) return null;
  const params = paramNames(fnNode);
  if (params === null) return null;
  return {
    name: name,
    params: params,
    paramTypes: paramTypes(fnNode, sf),
    returnType: fnNode.type ? fnNode.type.getText(sf).trim() : null,
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
  const alreadyExported = new Set(allExportedNames(sf));
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
  fail("usage: ts_driver.js scan <file> | mine <file> <name> "
       + "| mine-jsdoc <file> <name> | fill <file> <name> <body> "
       + "| doc-targets <file> | doc-verify <file> | wire-targets <file> | wire-verify <file>");
}

main();
