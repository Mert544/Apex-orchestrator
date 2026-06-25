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
//   fill  <file> <name> <body>
//                          -> replace the body BLOCK of the single top-level
//                             function <name> with `{ <body> }` (exact byte-span
//                             splice — formatting/comments around it survive),
//                             write <file> in place, print the touched span.
//                             Exit 2 (REFUSE) when <name> is not defined exactly
//                             once as a fillable stub.
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

function main() {
  const argv = process.argv.slice(2);
  const sub = argv[0];
  if (sub === "scan" && argv.length === 2) return cmdScan(argv[1]);
  if (sub === "mine" && argv.length === 3) return cmdMine(argv[1], argv[2]);
  if (sub === "fill" && argv.length === 4) return cmdFill(argv[1], argv[2], argv[3]);
  fail("usage: ts_driver.js scan <file> | mine <file> <name> | fill <file> <name> <body>");
}

main();
