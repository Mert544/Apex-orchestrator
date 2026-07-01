// ApexJavaDriver.java — Apex's bundled, deterministic Java parse/analyse driver.
//
// The LLM-free parse engine behind the java-finalize-field objective and Apex's
// Java support, the exact analogue of the bundled `ts_driver.js`. Apex (Python)
// spawns this script through the existing CommandRunner as a single-file source
// launcher (`java ApexJavaDriver.java <subcommand> <file>`); it speaks canonical
// JSON on stdout and exits 2 on REFUSE. It depends ONLY on the JDK's OWN Compiler
// Tree API (`com.sun.source.util.JavacTask.parse()` + `Trees`/`SourcePositions`) —
// NO third-party jar is ever installed, NO symbol resolution, NO classpath, NO
// network. `JavacTask.parse()` is a pure function of the bytes and every emission
// is in source order with fixed JSON key order, so the same input yields the same
// output (the determinism invariant the Python spine keeps). Because the parser is
// shipped INSIDE the JDK we already require, there is no `NODE_PATH`/global-package
// analogue — the install story is just "a JDK is on PATH".
//
// Subcommands (argv[0]):
//   parse-verify <file> -> JSON {"types":[...],"fields":[...],"methods":[...]}: the
//                          canonical structural fact-set of <file> — the sorted
//                          declared top-level/nested type names, the
//                          "<Type>.<field>" names, and the "<Type>.<method>/<arity>"
//                          signatures. This is BOTH the well-formedness oracle and
//                          the behaviour-identical witness for a splice (a leading
//                          modifier-only edit changes ZERO of these facts, so the
//                          spliced file must re-parse AND carry the same fact-set —
//                          Python compares the pre/post sets and refuses on drift).
//                          Exit 2 (REFUSE) on ANY parse error diagnostic (the exact
//                          analogue of `sf.parseDiagnostics.length > 0` -> exit 2).
//   final-targets <file> -> JSON [{name, insertOffset}]: every PRIVATE instance
//                          field that is NEVER reassigned anywhere in <file> (the
//                          whole assignment surface of a private field lives in this
//                          one file's AST — no other file can write it), in source
//                          order, where `insertOffset` is the byte offset just past
//                          the field's existing modifier keywords (`public`/`private`/
//                          `static`/... ) at which splicing ` final` makes it
//                          `private final ...`. REFUSES (omits) a field that is: not
//                          private; already final; static; assigned ANYWHERE but its
//                          own initializer (a plain `=`, a compound `+=`, or a `++`/
//                          `--`, in any method/constructor); OR one of several
//                          declarators sharing a single statement (`int a, b;`) — any
//                          shape it cannot read verbatim is omitted (never a guess).
//                          REFUSES the WHOLE unit (emits []) when it references
//                          `java.lang.reflect` (an import or a Field-setter member
//                          select like `setAccessible`/`setInt`) OR any class
//                          `implements Serializable`: a reflective/deserialization
//                          writer can set ANY private field WITHOUT a syntactic `=`,
//                          so sealing one `final` would throw/no-op at RUNTIME (the
//                          fact-set reparse oracle cannot see it — `final` is not a
//                          fact), and a single-file parser cannot prove WHICH field is
//                          safe. Conservative whole-file refusal, the same spirit as
//                          the multi-declarator refusal.
//                          Exit 2 (REFUSE) on ANY parse error diagnostic.
//   doc-targets <file> -> JSON [{name, throws:[Type,...], insertOffset}]: every method
//                          that DECLARES a `throws` clause (`MethodTree.getThrows()` is
//                          non-empty) but has NO Javadoc (`Trees.getDocComment(path)`
//                          is null), in source order, where `insertOffset` is the byte
//                          offset just before the method's start (at its modifiers) at
//                          which splicing a `/** ... @throws <Type> ... */` Javadoc
//                          block documents the DECLARED checked-exception types. The
//                          `throws` names are the SIMPLE type names of the declared
//                          throws clause IN SOURCE ORDER (the exact, behaviour-identical
//                          contract — NOT inferred from `throw new X()` statements). A
//                          Javadoc is a COMMENT, so it changes ZERO declared structure
//                          (the fact-set re-parse oracle stays identical). REFUSES
//                          (omits) a method that ALREADY carries a Javadoc (merging an
//                          existing block is out of scope), or that has an empty throws
//                          clause, or whose start position is unreadable. This is the
//                          Java analogue of document-raises / document-raises-jsdoc.
//                          Exit 2 (REFUSE) on ANY parse error diagnostic.
//   param-targets <file> -> JSON [{name, params:[paramName,...], insertOffset}]: every
//                          method that DECLARES at least one parameter
//                          (`MethodTree.getParameters()` is non-empty) but has NO Javadoc
//                          (`Trees.getDocComment(path)` is null), in source order, where
//                          `insertOffset` is the byte offset just before the method's
//                          start (at its modifiers) at which splicing a
//                          `/** ... @param <name> ... */` Javadoc block documents the
//                          DECLARED parameters. The `params` names are the SIMPLE
//                          declared parameter names IN SOURCE ORDER (verbatim off
//                          `VariableTree.getName()` — no types, the standard bare
//                          `@param name` Javadoc form). A Javadoc is a COMMENT, so it
//                          changes ZERO declared structure (the fact-set re-parse oracle
//                          stays identical). REFUSES (omits) a method that ALREADY carries
//                          a Javadoc (merging an existing block is out of scope, AND keeps
//                          this disjoint from doc-targets — whichever lands first makes
//                          the method documented, so the other then refuses it), or that
//                          has zero parameters, or whose start position is unreadable.
//                          This is the Java analogue of document-param /
//                          js-document-param-types.
//                          Exit 2 (REFUSE) on ANY parse error diagnostic.
//   return-targets <file> -> JSON [{name, returnType, insertOffset}]: every method that
//                          DECLARES a NON-void, NON-constructor return type
//                          (`MethodTree.getReturnType()` is non-null and not the `void`
//                          PrimitiveTypeTree) but has NO Javadoc
//                          (`Trees.getDocComment(path)` is null), in source order, where
//                          `insertOffset` is the byte offset just before the method's
//                          start (at its modifiers) at which splicing a
//                          `/** ... @return <type> ... */` Javadoc block documents the
//                          DECLARED return type. `returnType` is the VERBATIM source text
//                          of the return-type tree (sliced out of the source between the
//                          tree's start/end byte offsets — NOT `Tree.toString()`, which can
//                          normalize generics/annotations/whitespace; the source slice is
//                          byte-faithful, the "verbatim declared fact" discipline). A
//                          Javadoc is a COMMENT, so it changes ZERO declared structure (the
//                          fact-set re-parse oracle stays identical). REFUSES (omits) a
//                          method that ALREADY carries a Javadoc (merging an existing block
//                          is out of scope, AND keeps this disjoint from param-targets /
//                          doc-targets — whichever lands first makes the method documented,
//                          so the others then refuse it), a `void`-returning method (a
//                          `@return void` is content-free), a CONSTRUCTOR (no return type),
//                          or one whose return-type/start span is unreadable. This is the
//                          Java analogue of document-returns / js-document-returns-inferred.
//                          Exit 2 (REFUSE) on ANY parse error diagnostic.
//   final-param-targets <file> -> JSON [{method, name, insertOffset}]: every DECLARED
//                          method/constructor parameter that is NEVER reassigned anywhere
//                          in that SAME method's OWN body — a PER-METHOD scan
//                          (`MethodTree.getBody()`), not the whole-file scan
//                          `final-targets` uses, because a parameter's entire assignment
//                          surface is the stack frame of its own method (never another
//                          method, never reflection — no other code can write a Java
//                          local). `insertOffset` is the byte offset just before the
//                          parameter's own type token where splicing `final ` makes it
//                          read `final <Type> <name>`. `method` is the enclosing method's
//                          fact-only summary name (a constructor's synthetic `<init>` is
//                          rendered as the enclosing class simple name, exactly as
//                          `doc-targets`/`param-targets` do, so a doclint-style summary
//                          never emits `<init>`). REFUSES (omits) a parameter that is:
//                          already `final`; reassigned anywhere in the method body (a
//                          plain `=`, a compound `+=`, or a `++`/`--`); OR belongs to an
//                          ABSTRACT/INTERFACE method or a NATIVE method (`getBody()` is
//                          `null` — nothing to scan, so the WHOLE method's parameters are
//                          skipped rather than vacuously accepted). Scope: declared
//                          method/constructor parameters only — a lambda parameter, an
//                          enhanced-`for` variable, and a `catch` variable are OUT OF
//                          SCOPE for this first cut (never touched, never reported).
//                          Exit 2 (REFUSE) on ANY parse error diagnostic.
//   final-local-targets <file> -> JSON [{method, name, insertOffset}]: every LOCAL
//                          VARIABLE declared as a DIRECT STATEMENT of a method/
//                          constructor body block (`BlockTree.getStatements()` holds a
//                          `VariableTree`) that is NEVER reassigned anywhere in that
//                          SAME method's OWN body — a PER-METHOD scan, the exact spine
//                          `final-param-targets` uses, because a local's entire
//                          assignment surface is the stack frame of its own method
//                          (never another method, never reflection — no other code can
//                          write a Java local). `insertOffset` is the byte offset just
//                          before the local's own type token where splicing `final `
//                          makes it read `final <Type> <name> = ...`. `method` is the
//                          enclosing method's fact-only summary name (a constructor's
//                          synthetic `<init>` rendered as the enclosing class simple
//                          name, exactly as `final-param-targets`/`doc-targets` do).
//                          REFUSES (omits) a local that is: already `final`; reassigned
//                          anywhere in the method body (a plain `=`, a compound `+=`, or
//                          a `++`/`--`); has NO initializer (`getInitializer()` is null
//                          — a bare `int x;` split from its assignment would need
//                          definite-assignment analysis the parse-only oracle cannot do,
//                          so it is refused rather than guessed). SCOPE BOUNDARY (an
//                          EXPLICIT, TESTED decision, not an accidental byproduct): ONLY
//                          a plain `VariableTree` that is a DIRECT statement of a
//                          `BlockTree` is considered — a `for`-loop init variable
//                          (`ForLoopTree.getInitializer()`), an enhanced-`for` variable
//                          (`EnhancedForLoopTree.getVariable()`), and a
//                          try-with-resources resource (`TryTree.getResources()`) are
//                          NOT block statements, so scanning `getStatements()` EXCLUDES
//                          them BY OMISSION. A variable captured by a lambda or an
//                          anonymous inner class IS a block statement, so it is refused
//                          EXPLICITLY (a per-body capture scan over every lambda /
//                          anonymous-class body) rather than by omission — such a local
//                          is already effectively-final and would compile if sealed, but
//                          this first cut declines to reason about capture semantics
//                          (over-refusal is safe: it never seals a variable it should
//                          not). This is the local-scope analogue of
//                          `final-param-targets`, one step deeper into the same
//                          never-reassigned proof.
//                          Exit 2 (REFUSE) on ANY parse error diagnostic.
//
// Determinism: no clock, no randomness; types/fields/methods are SORTED, targets are
// reported in source order; JSON keys are emitted in a fixed order. `insertOffset`
// comes from `SourcePositions` (a byte offset into the source), so a splice is a
// precise byte insert, never an AST unparse — the surrounding source is untouched.

import com.sun.source.tree.AssignmentTree;
import com.sun.source.tree.BlockTree;
import com.sun.source.tree.ClassTree;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.CompoundAssignmentTree;
import com.sun.source.tree.ExpressionTree;
import com.sun.source.tree.IdentifierTree;
import com.sun.source.tree.ImportTree;
import com.sun.source.tree.LambdaExpressionTree;
import com.sun.source.tree.MemberSelectTree;
import com.sun.source.tree.MethodInvocationTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.tree.ModifiersTree;
import com.sun.source.tree.NewClassTree;
import com.sun.source.tree.PrimitiveTypeTree;
import com.sun.source.tree.StatementTree;
import com.sun.source.tree.Tree;
import com.sun.source.tree.UnaryTree;
import com.sun.source.tree.VariableTree;
import com.sun.source.util.JavacTask;
import com.sun.source.util.SourcePositions;
import com.sun.source.util.TreePath;
import com.sun.source.util.TreePathScanner;
import com.sun.source.util.TreeScanner;
import com.sun.source.util.Trees;

import javax.lang.model.element.Modifier;
import javax.lang.model.type.TypeKind;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.SimpleJavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;

public final class ApexJavaDriver {

    private static final int REFUSE = 2;

    private ApexJavaDriver() {
    }

    // --- parse seam ----------------------------------------------------------

    /** A parse-only compilation unit plus the positions table, or REFUSE (exit 2)
     * on any parse-error diagnostic or unreadable file — the exact analogue of the
     * JS driver's readSource(). NO symbol resolution (only parse()), NO classpath. */
    private static final class Parsed {
        final CompilationUnitTree unit;
        final SourcePositions positions;
        final String source;
        final Trees trees;

        Parsed(CompilationUnitTree unit, SourcePositions positions, String source,
               Trees trees) {
            this.unit = unit;
            this.positions = positions;
            this.source = source;
            this.trees = trees;
        }
    }

    private static Parsed parseOrRefuse(String file) {
        String source;
        try {
            source = new String(Files.readAllBytes(Paths.get(file)), StandardCharsets.UTF_8);
        } catch (Exception e) {
            return fail("cannot read " + file);
        }
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) {
            return fail("no system Java compiler");
        }
        DiagnosticCollector<JavaFileObject> diags = new DiagnosticCollector<>();
        JavaFileObject jfo = new SimpleJavaFileObject(
                URI.create("string:///In.java"), JavaFileObject.Kind.SOURCE) {
            @Override
            public CharSequence getCharContent(boolean ignoreEncodingErrors) {
                return source;
            }
        };
        try {
            StandardJavaFileManager fm =
                    compiler.getStandardFileManager(diags, null, StandardCharsets.UTF_8);
            // -proc:none keeps it parse/scan only — never runs annotation processors,
            // never resolves a classpath; the whole point is no network / no deps.
            JavacTask task = (JavacTask) compiler.getTask(
                    null, fm, diags, List.of("-proc:none"), null, List.of(jfo));
            Iterable<? extends CompilationUnitTree> units = task.parse();
            Trees trees = Trees.instance(task);
            CompilationUnitTree unit = null;
            for (CompilationUnitTree u : units) {
                unit = u;
                break;
            }
            // ANY parse-error diagnostic is a refusal — never edit a file we cannot model.
            if (hasError(diags) || unit == null) {
                return fail("parse error in " + file);
            }
            return new Parsed(unit, trees.getSourcePositions(), source, trees);
        } catch (Exception e) {
            return fail("parse error in " + file);
        }
    }

    private static boolean hasError(DiagnosticCollector<JavaFileObject> diags) {
        for (javax.tools.Diagnostic<? extends JavaFileObject> d : diags.getDiagnostics()) {
            if (d.getKind() == javax.tools.Diagnostic.Kind.ERROR) {
                return true;
            }
        }
        return false;
    }

    // --- parse-verify: the canonical structural fact-set ---------------------

    private static void cmdParseVerify(String file) {
        Parsed p = parseOrRefuse(file);
        Set<String> types = new TreeSet<>();
        Set<String> fields = new TreeSet<>();
        Set<String> methods = new TreeSet<>();
        collectFacts(p.unit, types, fields, methods);
        StringBuilder sb = new StringBuilder();
        sb.append("{\"types\":");
        appendStringArray(sb, types);
        sb.append(",\"fields\":");
        appendStringArray(sb, fields);
        sb.append(",\"methods\":");
        appendStringArray(sb, methods);
        sb.append("}");
        System.out.print(sb);
    }

    /** Walk every class/interface/enum/record and record its declared type names,
     * "<Type>.<field>" names, and "<Type>.<method>/<arity>" signatures — the
     * structural fact-set a behaviour-identical edit must leave UNCHANGED. */
    private static void collectFacts(CompilationUnitTree unit, Set<String> types,
                                     Set<String> fields, Set<String> methods) {
        new TreeScanner<Void, String>() {
            @Override
            public Void visitClass(ClassTree node, String outer) {
                String simple = String.valueOf(node.getSimpleName());
                if (simple.isEmpty()) {
                    return super.visitClass(node, outer);  // anonymous — skip the name
                }
                String qualified = outer.isEmpty() ? simple : outer + "." + simple;
                types.add(qualified);
                for (Tree member : node.getMembers()) {
                    if (member instanceof VariableTree) {
                        fields.add(qualified + "." + ((VariableTree) member).getName());
                    } else if (member instanceof MethodTree) {
                        MethodTree m = (MethodTree) member;
                        methods.add(qualified + "." + m.getName() + "/" + m.getParameters().size());
                    }
                }
                return super.visitClass(node, qualified);
            }
        }.scan(unit, "");
    }

    // --- final-targets: never-reassigned private fields ----------------------

    private static void cmdFinalTargets(String file) {
        Parsed p = parseOrRefuse(file);
        // Whole-unit refusal: a reflective writer (`java.lang.reflect.Field` set*) or a
        // deserializer (`implements Serializable`) can write ANY private field WITHOUT a
        // syntactic assignment the scan can see, so sealing one `final` would throw /
        // no-op at RUNTIME — and the fact-set reparse oracle cannot catch it (`final` is
        // not a declared type/field/method fact). A single-file parser cannot prove
        // WHICH private field such a writer leaves alone, so the conservative, sound
        // answer is to finalise NOTHING in the whole unit (mirrors the multi-declarator
        // refusal). Emit [] and stop.
        if (referencesReflectionOrSerializable(p)) {
            System.out.print("[]");
            return;
        }
        Set<String> assigned = collectAssignedNames(p.unit);
        Set<String> multiDeclared = collectMultiDeclaredFieldNames(p.unit, p.positions);
        List<long[]> orderedOffsets = new ArrayList<>();  // [insertOffset]
        List<String> orderedNames = new ArrayList<>();
        collectFinalTargets(p, assigned, multiDeclared, orderedNames, orderedOffsets);
        // Emit in source order (the field-declaration order the scanner visits).
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < orderedNames.size(); i++) {
            if (i > 0) {
                sb.append(",");
            }
            sb.append("{\"name\":");
            appendJsonString(sb, orderedNames.get(i));
            sb.append(",\"insertOffset\":").append(orderedOffsets.get(i)[0]).append("}");
        }
        sb.append("]");
        System.out.print(sb);
    }

    // --- whole-unit refusal: reflection / serialization writers --------------

    /** The member-select method names a `java.lang.reflect.Field` exposes to WRITE a
     * field's value (`f.setInt(this, 99)`, `f.set(obj, v)`, `f.setAccessible(true)`).
     * Seeing any of these as the selected method of an invocation is a strong signal
     * the unit writes a private field reflectively, so we refuse the whole unit. */
    private static final Set<String> REFLECT_FIELD_WRITERS = Set.of(
            "setAccessible", "set", "setInt", "setLong", "setShort", "setByte",
            "setBoolean", "setChar", "setDouble", "setFloat", "setObject");

    /** True when the unit references reflection (an import of `java.lang.reflect.*` /
     * `java.lang.reflect.Field`, OR an invocation of a `Field`-writer member select)
     * OR declares a class that `implements Serializable` — in either case a writer
     * outside the syntactic-assignment scan can set a private field, so NO field in
     * the unit may be sealed `final`. Conservative by design: a false positive only
     * declines a finalisation (lands nothing), never an unsound seal. */
    private static boolean referencesReflectionOrSerializable(Parsed p) {
        return importsJavaLangReflect(p.unit)
                || usesReflectFieldWriter(p.unit)
                || implementsSerializable(p.unit);
    }

    /** True when any import names the reflection package — `java.lang.reflect.Field`,
     * `java.lang.reflect.*`, or any `java.lang.reflect.<X>`. The simplest conservative
     * gate: a unit that imports reflection is presumed to write a field reflectively. */
    private static boolean importsJavaLangReflect(CompilationUnitTree unit) {
        for (ImportTree imp : unit.getImports()) {
            Tree id = imp.getQualifiedIdentifier();
            if (id == null) {
                continue;
            }
            String name = id.toString();
            if (name.equals("java.lang.reflect.*")
                    || name.equals("java.lang.reflect.Field")
                    || name.startsWith("java.lang.reflect.")) {
                return true;
            }
        }
        return false;
    }

    /** True when the unit invokes a `Field`-writer member select (`x.setInt(...)`,
     * `x.set(...)`, `x.setAccessible(...)`) anywhere — the robust signal a reflective
     * write happens even when the `Field` is obtained without an `import` (a
     * fully-qualified `java.lang.reflect.Field`). Conservative on the method NAME (no
     * symbol resolution): any same-named member-select invocation flags the unit. */
    private static boolean usesReflectFieldWriter(CompilationUnitTree unit) {
        boolean[] found = {false};
        new TreePathScanner<Void, Void>() {
            @Override
            public Void visitMethodInvocation(MethodInvocationTree node, Void unused) {
                ExpressionTree select = node.getMethodSelect();
                if (select instanceof MemberSelectTree) {
                    String method = String.valueOf(
                            ((MemberSelectTree) select).getIdentifier());
                    if (REFLECT_FIELD_WRITERS.contains(method)) {
                        found[0] = true;
                    }
                }
                return super.visitMethodInvocation(node, unused);
            }
        }.scan(unit, null);
        return found[0];
    }

    /** True when ANY class/enum/record in the unit lists `Serializable` (or
     * `java.io.Serializable`) in its implements clause — a deserializer sets such a
     * class's private fields reflectively, so none may be sealed `final`. The trailing
     * simple name is compared (a `MemberSelectTree` for the qualified form), so both
     * `implements Serializable` and `implements java.io.Serializable` are caught. */
    private static boolean implementsSerializable(CompilationUnitTree unit) {
        boolean[] found = {false};
        new TreeScanner<Void, Void>() {
            @Override
            public Void visitClass(ClassTree node, Void unused) {
                for (Tree iface : node.getImplementsClause()) {
                    if (simpleTypeName(iface).equals("Serializable")) {
                        found[0] = true;
                    }
                }
                return super.visitClass(node, unused);
            }
        }.scan(unit, null);
        return found[0];
    }

    /** The trailing simple name of a (possibly qualified) type tree: the identifier
     * for `Serializable`, the selected name for `java.io.Serializable`, else the raw
     * string (e.g. a parameterized type's text — never matched here). */
    private static String simpleTypeName(Tree type) {
        if (type instanceof IdentifierTree) {
            return String.valueOf(((IdentifierTree) type).getName());
        }
        if (type instanceof MemberSelectTree) {
            return String.valueOf(((MemberSelectTree) type).getIdentifier());
        }
        return String.valueOf(type);
    }

    /** Every PRIVATE, non-static, non-final, single-declarator instance field that
     * is NEVER an assignment target anywhere in the file, with the byte offset just
     * past its modifier keywords where ` final` splices in. Source order. */
    private static void collectFinalTargets(Parsed p, Set<String> assigned,
                                            Set<String> multiDeclared,
                                            List<String> names, List<long[]> offsets) {
        new TreeScanner<Void, Void>() {
            @Override
            public Void visitClass(ClassTree node, Void unused) {
                for (Tree member : node.getMembers()) {
                    if (member instanceof VariableTree) {
                        considerField((VariableTree) member, p, assigned, multiDeclared,
                                names, offsets);
                    }
                }
                return super.visitClass(node, unused);
            }
        }.scan(p.unit, null);
    }

    private static void considerField(VariableTree field, Parsed p, Set<String> assigned,
                                      Set<String> multiDeclared, List<String> names,
                                      List<long[]> offsets) {
        String name = String.valueOf(field.getName());
        ModifiersTree mods = field.getModifiers();
        Set<Modifier> flags = mods.getFlags();
        // REFUSE: not private / already final / static (a static field's "instance"
        // framing does not apply; keep the first objective to instance fields only).
        if (!flags.contains(Modifier.PRIVATE)
                || flags.contains(Modifier.FINAL)
                || flags.contains(Modifier.STATIC)) {
            return;
        }
        // REFUSE: assigned anywhere but its own initializer (any `=`, `+=`, `++`).
        if (assigned.contains(name)) {
            return;
        }
        // REFUSE: a multi-declarator statement (`private int a, b;`) — a single
        // ` final` cannot be placed verbatim without re-emitting the declaration.
        if (multiDeclared.contains(name)) {
            return;
        }
        // REFUSE: a blank field (no initializer) that survived the `assigned` check
        // is never definitely assigned, so a blank `final` cannot compile (JLS §16
        // definite-assignment: a blank final must be assigned in every constructor).
        // A constructor-assigned field is already excluded above via `assigned`, so
        // only genuinely never-assigned blanks reach here — sealing them is a compile
        // error the parse-only oracle cannot catch, so refuse statically.
        if (field.getInitializer() == null) {
            return;
        }
        long insert = modifierInsertOffset(field, p);
        if (insert < 0) {
            return;  // a modifier span we cannot read verbatim — refuse
        }
        names.add(name);
        offsets.add(new long[]{insert});
    }

    /** The byte offset just past the field's modifier keywords (where ` final`
     * inserts cleanly), or -1 when the modifier/field span is unreadable. A private
     * field always carries the `private` keyword, so the keyword-end is the normal
     * path; the bounds checks make an unreadable/synthetic span refuse rather than
     * splice at a wrong offset. */
    private static long modifierInsertOffset(VariableTree field, Parsed p) {
        ModifiersTree mods = field.getModifiers();
        long modEnd = p.positions.getEndPosition(p.unit, mods);
        long fieldStart = p.positions.getStartPosition(p.unit, field);
        if (modEnd >= 0 && modEnd <= p.source.length() && fieldStart >= 0 && modEnd >= fieldStart) {
            return modEnd;  // splice ` final` right after `private`/the modifier list
        }
        return -1;
    }

    /** The simple names that are an assignment TARGET anywhere in ``root`` — a plain
     * `=`, a compound `+=`/`-=`/..., or a `++`/`--`. Conservative: for a member
     * select (`this.b`, `obj.b`) we record the trailing identifier, so a write to
     * ANY `.b` marks the name `b` reassigned (soundness over recall — we never want
     * a false `final`). ``root`` may be the WHOLE compilation unit (final-targets'
     * whole-file field scan) or a SINGLE method's body
     * (final-param-targets' per-method parameter scan) — the walk is identical
     * either way, only the subtree scanned differs. */
    private static Set<String> collectAssignedNames(Tree root) {
        // A plain TreeScanner (NOT TreePathScanner): this walk never needs a
        // TreePath, and TreePathScanner.scan(Tree, P) requires an ALREADY-ACTIVE
        // path context (it seeds from getCurrentPath(), null outside a nested
        // scan) — which final-param-targets' per-method call (from inside another
        // scanner's visitMethod) does not have. A bare TreeScanner has no such
        // requirement and walks any subtree (the whole unit, or one method's
        // body) identically.
        Set<String> assigned = new HashSet<>();
        new TreeScanner<Void, Void>() {
            @Override
            public Void visitAssignment(AssignmentTree node, Void unused) {
                recordTarget(node.getVariable(), assigned);
                return super.visitAssignment(node, unused);
            }

            @Override
            public Void visitCompoundAssignment(CompoundAssignmentTree node, Void unused) {
                recordTarget(node.getVariable(), assigned);
                return super.visitCompoundAssignment(node, unused);
            }

            @Override
            public Void visitUnary(UnaryTree node, Void unused) {
                String kind = node.getKind().toString();
                if (kind.contains("INCREMENT") || kind.contains("DECREMENT")) {
                    recordTarget(node.getExpression(), assigned);
                }
                return super.visitUnary(node, unused);
            }
        }.scan(root, null);
        return assigned;
    }

    private static void recordTarget(ExpressionTree target, Set<String> assigned) {
        if (target instanceof IdentifierTree) {
            assigned.add(String.valueOf(((IdentifierTree) target).getName()));
        } else if (target instanceof MemberSelectTree) {
            assigned.add(String.valueOf(((MemberSelectTree) target).getIdentifier()));
        }
    }

    /** Every simple identifier NAME referenced anywhere inside a lambda body or an
     * anonymous-inner-class body within ``root`` — the CAPTURE surface of ``root``'s
     * own locals. Used ONLY by final-local-targets: a local captured by a lambda /
     * anonymous inner class is CONSERVATIVELY refused (never sealed), even though a
     * captured variable is already required to be effectively-final by javac (so
     * sealing it would in fact compile) — this objective's first cut deliberately
     * declines to reason about capture semantics, scoping to the locals whose whole
     * lifetime is a plain block statement. Over-refusal is safe: it never seals a
     * variable it should not, it only leaves some sound seals on the table. A lambda's
     * OWN parameters and an anonymous class's OWN declarations are recorded too (a
     * superset — conservative-by-design; the objective never wants a false ``final``
     * on a name that also names a captured outer local). */
    private static Set<String> collectCapturedNames(Tree root) {
        Set<String> captured = new HashSet<>();
        new TreeScanner<Void, Void>() {
            @Override
            public Void visitLambdaExpression(LambdaExpressionTree node, Void unused) {
                recordIdentifiers(node.getBody(), captured);
                return super.visitLambdaExpression(node, unused);
            }

            @Override
            public Void visitNewClass(NewClassTree node, Void unused) {
                // Only an ANONYMOUS inner class (one with a class body) captures
                // enclosing locals; a plain `new Foo(...)` does not.
                if (node.getClassBody() != null) {
                    recordIdentifiers(node.getClassBody(), captured);
                }
                return super.visitNewClass(node, unused);
            }
        }.scan(root, null);
        return captured;
    }

    /** Record every simple identifier NAME appearing anywhere in ``subtree`` (a lambda
     * body or an anonymous-class body) — the conservative capture set. */
    private static void recordIdentifiers(Tree subtree, Set<String> names) {
        if (subtree == null) {
            return;
        }
        new TreeScanner<Void, Void>() {
            @Override
            public Void visitIdentifier(IdentifierTree node, Void unused) {
                names.add(String.valueOf(node.getName()));
                return super.visitIdentifier(node, unused);
            }
        }.scan(subtree, null);
    }

    /** The simple field names declared as one of SEVERAL declarators in a single
     * statement (`private int a, b;`). Detected structurally: two field members of
     * the SAME class whose declarations share a modifiers START position belong to
     * the same `int a, b;` statement, so BOTH names are flagged (a single ` final`
     * cannot be spliced into a shared declaration verbatim). */
    private static Set<String> collectMultiDeclaredFieldNames(CompilationUnitTree unit,
                                                              SourcePositions positions) {
        Set<String> multi = new HashSet<>();
        new TreeScanner<Void, Void>() {
            @Override
            public Void visitClass(ClassTree node, Void unused) {
                List<VariableTree> fields = new ArrayList<>();
                for (Tree member : node.getMembers()) {
                    if (member instanceof VariableTree) {
                        fields.add((VariableTree) member);
                    }
                }
                flagShared(fields);
                return super.visitClass(node, unused);
            }

            private void flagShared(List<VariableTree> fields) {
                for (int i = 0; i < fields.size(); i++) {
                    long si = positions.getStartPosition(unit, fields.get(i).getModifiers());
                    for (int j = i + 1; j < fields.size(); j++) {
                        long sj = positions.getStartPosition(unit, fields.get(j).getModifiers());
                        if (si >= 0 && si == sj) {
                            multi.add(String.valueOf(fields.get(i).getName()));
                            multi.add(String.valueOf(fields.get(j).getName()));
                        }
                    }
                }
            }
        }.scan(unit, null);
        return multi;
    }

    // --- doc-targets: undocumented methods with a declared `throws` clause ----

    private static void cmdDocTargets(String file) {
        Parsed p = parseOrRefuse(file);
        List<String> orderedNames = new ArrayList<>();
        List<List<String>> orderedThrows = new ArrayList<>();
        List<Long> orderedOffsets = new ArrayList<>();
        collectDocTargets(p, orderedNames, orderedThrows, orderedOffsets);
        // Emit in source order (the method-declaration order the scanner visits).
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < orderedNames.size(); i++) {
            if (i > 0) {
                sb.append(",");
            }
            sb.append("{\"name\":");
            appendJsonString(sb, orderedNames.get(i));
            sb.append(",\"throws\":");
            appendStringList(sb, orderedThrows.get(i));
            sb.append(",\"insertOffset\":").append(orderedOffsets.get(i)).append("}");
        }
        sb.append("]");
        System.out.print(sb);
    }

    /** Every method that DECLARES a non-empty throws clause but carries NO Javadoc,
     * with the simple type names of its declared throws clause (source order) and the
     * byte offset just before the method's start where a leading Javadoc block splices
     * in. A TreePathScanner is used because Trees.getDocComment needs the method's
     * TreePath: an EXISTING Javadoc is refused (merging is out of scope, exactly as
     * Python document-raises documents only the undocumented). Source order is the
     * visit order of the methods. */
    private static void collectDocTargets(Parsed p, List<String> names,
                                          List<List<String>> throwsLists,
                                          List<Long> offsets) {
        Trees trees = p.trees;
        new TreePathScanner<Void, Void>() {
            @Override
            public Void visitMethod(MethodTree node, Void unused) {
                considerDocMethod(node, getCurrentPath(), trees, p, names, throwsLists,
                        offsets);
                return super.visitMethod(node, unused);
            }
        }.scan(p.unit, null);
    }

    private static void considerDocMethod(MethodTree method, TreePath path, Trees trees,
                                          Parsed p, List<String> names,
                                          List<List<String>> throwsLists,
                                          List<Long> offsets) {
        List<? extends ExpressionTree> declared = method.getThrows();
        // REFUSE: no declared `throws` clause — nothing to document (exact, not inferred).
        if (declared == null || declared.isEmpty()) {
            return;
        }
        // REFUSE: a method that ALREADY carries a Javadoc — merging an existing block is
        // out of scope (mirrors document-raises documenting only the undocumented). A
        // null doc-comment is the "no Javadoc" signal.
        if (trees.getDocComment(path) != null) {
            return;
        }
        List<String> types = new ArrayList<>();
        for (ExpressionTree thrown : declared) {
            types.add(simpleTypeName(thrown));
        }
        long insert = methodInsertOffset(method, p);
        if (insert < 0) {
            return;  // an unreadable method span — refuse rather than splice at a guess
        }
        // A ctor's name is the synthetic `<init>`; the summary uses the enclosing class
        // simple name (`Circle`) so the rendered `* Circle.` is doclint-clean (a `* <init>.`
        // is rejected as `unknown tag: init`, javadoc exit 1 — the field-found P1 defect).
        names.add(summaryName(method, path));
        throwsLists.add(types);
        offsets.add(insert);
    }

    /** The simple name of the nearest enclosing class/interface/enum/record for a
     * method's TreePath (walk `getParentPath()` up to the first `ClassTree` and return
     * its `getSimpleName()`), or null when none is found (a top-level/synthetic path).
     * Used as the fact-only summary NAME for a CONSTRUCTOR: a ctor's `MethodTree.getName()`
     * is the synthetic `<init>`, and rendering `* <init>.` breaks `javadoc`/doclint
     * (`unknown tag: init`, exit 1) — the field-found P1 defect — whereas the enclosing
     * class simple name (`* Circle.`) is both doclint-clean AND the correct prose. The
     * same `getSimpleName()` walk `collectFacts`'s `visitClass` uses; a comment-only text
     * change, so the fact-set re-parse stays identical. */
    private static String enclosingClassSimpleName(TreePath path) {
        for (TreePath cur = path == null ? null : path.getParentPath();
                cur != null; cur = cur.getParentPath()) {
            if (cur.getLeaf() instanceof ClassTree) {
                String simple = String.valueOf(((ClassTree) cur.getLeaf()).getSimpleName());
                return simple.isEmpty() ? null : simple;  // anonymous class — no usable name
            }
        }
        return null;
    }

    /** The fact-only summary NAME for a method: its own `getName()` normally, but the
     * ENCLOSING CLASS simple name for a constructor (`getName()` is the synthetic `<init>`,
     * which `javadoc`/doclint rejects as `unknown tag: init`). Falls back to the raw
     * `<init>` only when no enclosing class name is resolvable (a synthetic path — the
     * offset/parse would already have refused), never inventing a name. */
    private static String summaryName(MethodTree method, TreePath path) {
        String name = String.valueOf(method.getName());
        if (name.equals("<init>")) {
            String enclosing = enclosingClassSimpleName(path);
            if (enclosing != null) {
                return enclosing;
            }
        }
        return name;
    }

    /** The byte offset of the method's START (its modifiers/return-type), or -1 when
     * the span is unreadable. Splicing a Javadoc block here places it immediately
     * before the method declaration — a leading comment that changes ZERO declared
     * structure. The Python spine indents the block to the method's column. */
    private static long methodInsertOffset(MethodTree method, Parsed p) {
        long start = p.positions.getStartPosition(p.unit, method);
        if (start >= 0 && start <= p.source.length()) {
            return start;
        }
        return -1;
    }

    // --- param-targets: undocumented methods with >=1 declared parameter ------

    private static void cmdParamTargets(String file) {
        Parsed p = parseOrRefuse(file);
        List<String> orderedNames = new ArrayList<>();
        List<List<String>> orderedParams = new ArrayList<>();
        List<Long> orderedOffsets = new ArrayList<>();
        collectParamTargets(p, orderedNames, orderedParams, orderedOffsets);
        // Emit in source order (the method-declaration order the scanner visits).
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < orderedNames.size(); i++) {
            if (i > 0) {
                sb.append(",");
            }
            sb.append("{\"name\":");
            appendJsonString(sb, orderedNames.get(i));
            sb.append(",\"params\":");
            appendStringList(sb, orderedParams.get(i));
            sb.append(",\"insertOffset\":").append(orderedOffsets.get(i)).append("}");
        }
        sb.append("]");
        System.out.print(sb);
    }

    /** Every method that DECLARES at least one parameter but carries NO Javadoc, with
     * the simple names of its declared parameters (source order) and the byte offset
     * just before the method's start where a leading Javadoc block splices in. A
     * TreePathScanner is used because Trees.getDocComment needs the method's TreePath:
     * an EXISTING Javadoc is refused (merging is out of scope, exactly as the
     * doc-targets / Python document-param document only the undocumented). Source order
     * is the visit order of the methods. */
    private static void collectParamTargets(Parsed p, List<String> names,
                                            List<List<String>> paramLists,
                                            List<Long> offsets) {
        Trees trees = p.trees;
        new TreePathScanner<Void, Void>() {
            @Override
            public Void visitMethod(MethodTree node, Void unused) {
                considerParamMethod(node, getCurrentPath(), trees, p, names, paramLists,
                        offsets);
                return super.visitMethod(node, unused);
            }
        }.scan(p.unit, null);
    }

    private static void considerParamMethod(MethodTree method, TreePath path, Trees trees,
                                            Parsed p, List<String> names,
                                            List<List<String>> paramLists,
                                            List<Long> offsets) {
        List<? extends VariableTree> declared = method.getParameters();
        // REFUSE: no declared parameter — a `@param`-less Javadoc is content-free.
        if (declared == null || declared.isEmpty()) {
            return;
        }
        // REFUSE: a method that ALREADY carries a Javadoc — merging an existing block is
        // out of scope (mirrors doc-targets / document-param documenting only the
        // undocumented, AND keeps java-document-param disjoint from java-document-throws:
        // whichever lands first makes the method documented, so the other then refuses
        // it — no double Javadoc block). A null doc-comment is the "no Javadoc" signal.
        if (trees.getDocComment(path) != null) {
            return;
        }
        List<String> params = new ArrayList<>();
        for (VariableTree param : declared) {
            params.add(String.valueOf(param.getName()));  // the declared name, verbatim
        }
        long insert = methodInsertOffset(method, p);
        if (insert < 0) {
            return;  // an unreadable method span — refuse rather than splice at a guess
        }
        // A ctor's name is the synthetic `<init>`; the summary uses the enclosing class
        // simple name (`Circle`) so the rendered `* Circle.` is doclint-clean (a `* <init>.`
        // is rejected as `unknown tag: init`, javadoc exit 1 — the field-found P1 defect).
        names.add(summaryName(method, path));
        paramLists.add(params);
        offsets.add(insert);
    }

    // --- return-targets: undocumented methods with a non-void return type -----

    private static void cmdReturnTargets(String file) {
        Parsed p = parseOrRefuse(file);
        List<String> orderedNames = new ArrayList<>();
        List<String> orderedReturns = new ArrayList<>();
        List<Long> orderedOffsets = new ArrayList<>();
        collectReturnTargets(p, orderedNames, orderedReturns, orderedOffsets);
        // Emit in source order (the method-declaration order the scanner visits).
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < orderedNames.size(); i++) {
            if (i > 0) {
                sb.append(",");
            }
            sb.append("{\"name\":");
            appendJsonString(sb, orderedNames.get(i));
            sb.append(",\"returnType\":");
            appendJsonString(sb, orderedReturns.get(i));
            sb.append(",\"insertOffset\":").append(orderedOffsets.get(i)).append("}");
        }
        sb.append("]");
        System.out.print(sb);
    }

    /** Every method that DECLARES a non-void, non-constructor return type but carries
     * NO Javadoc, with the VERBATIM source text of its declared return type (read off
     * the type tree's source span, source order) and the byte offset just before the
     * method's start where a leading Javadoc block splices in. A TreePathScanner is used
     * because Trees.getDocComment needs the method's TreePath: an EXISTING Javadoc is
     * refused (merging is out of scope, exactly as the param-targets / doc-targets /
     * Python document-returns document only the undocumented). Source order is the visit
     * order of the methods. */
    private static void collectReturnTargets(Parsed p, List<String> names,
                                             List<String> returnTypes,
                                             List<Long> offsets) {
        Trees trees = p.trees;
        new TreePathScanner<Void, Void>() {
            @Override
            public Void visitMethod(MethodTree node, Void unused) {
                considerReturnMethod(node, getCurrentPath(), trees, p, names, returnTypes,
                        offsets);
                return super.visitMethod(node, unused);
            }
        }.scan(p.unit, null);
    }

    private static void considerReturnMethod(MethodTree method, TreePath path, Trees trees,
                                             Parsed p, List<String> names,
                                             List<String> returnTypes,
                                             List<Long> offsets) {
        Tree rt = method.getReturnType();
        // REFUSE: a constructor has no return type (getReturnType() is null) — nothing to
        // document, exactly as the Python document-returns refuses a function with no
        // declared return.
        if (rt == null) {
            return;
        }
        // REFUSE: a `void` return type — a `@return` on a void method is content-free (the
        // direct analogue of param-targets refusing zero params, and the Python
        // document-returns refusing a `None`/`NoReturn` head). `void` is the ONLY
        // PrimitiveTypeTree whose kind is VOID.
        if (rt instanceof PrimitiveTypeTree
                && ((PrimitiveTypeTree) rt).getPrimitiveTypeKind() == TypeKind.VOID) {
            return;
        }
        // REFUSE: a method that ALREADY carries a Javadoc — merging an existing block is
        // out of scope (mirrors param-targets / doc-targets / document-returns documenting
        // only the undocumented, AND keeps java-document-returns disjoint from
        // java-document-param / java-document-throws: whichever lands first makes the
        // method documented, so the others then refuse it — no double Javadoc block). A
        // null doc-comment is the "no Javadoc" signal.
        if (trees.getDocComment(path) != null) {
            return;
        }
        // Read the declared return-type text VERBATIM off the type tree's SOURCE SPAN
        // (start..end byte offsets sliced out of p.source) — NOT Tree.toString(), which can
        // normalize generics/annotations/whitespace. The source slice is byte-faithful,
        // the family's "verbatim declared fact, never invented" discipline.
        String returnType = returnTypeText(rt, p);
        if (returnType == null) {
            return;  // an unreadable return-type span — refuse rather than guess the text
        }
        long insert = methodInsertOffset(method, p);
        if (insert < 0) {
            return;  // an unreadable method span — refuse rather than splice at a guess
        }
        names.add(String.valueOf(method.getName()));
        returnTypes.add(returnType);
        offsets.add(insert);
    }

    /** The VERBATIM source text of a return-type tree (the slice of p.source between the
     * tree's start and end byte offsets), or null when the span is unreadable / empty.
     * Byte-faithful (preserves the author's generics/annotations/whitespace exactly),
     * never an AST unparse. */
    private static String returnTypeText(Tree rt, Parsed p) {
        long start = p.positions.getStartPosition(p.unit, rt);
        long end = p.positions.getEndPosition(p.unit, rt);
        if (start < 0 || end < start || end > p.source.length()) {
            return null;  // an unreadable/synthetic span — refuse rather than guess
        }
        String text = p.source.substring((int) start, (int) end);
        return text.isEmpty() ? null : text;
    }

    // --- final-param-targets: never-reassigned method/constructor parameters -

    private static void cmdFinalParamTargets(String file) {
        Parsed p = parseOrRefuse(file);
        List<String> orderedMethods = new ArrayList<>();
        List<String> orderedNames = new ArrayList<>();
        List<Long> orderedOffsets = new ArrayList<>();
        collectFinalParamTargets(p, orderedMethods, orderedNames, orderedOffsets);
        // Emit in source order (the method-declaration / parameter order the scanner
        // visits — a per-method scan, unlike final-targets' whole-file scan).
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < orderedNames.size(); i++) {
            if (i > 0) {
                sb.append(",");
            }
            sb.append("{\"method\":");
            appendJsonString(sb, orderedMethods.get(i));
            sb.append(",\"name\":");
            appendJsonString(sb, orderedNames.get(i));
            sb.append(",\"insertOffset\":").append(orderedOffsets.get(i)).append("}");
        }
        sb.append("]");
        System.out.print(sb);
    }

    /** Every method/constructor's never-reassigned declared parameters, scanned ONE
     * method at a time (unlike final-targets' whole-file field scan): a parameter's
     * ENTIRE assignment surface is its own method's body (no other code — not another
     * method, not reflection — can write a Java local), so a per-method scan is both
     * sufficient and sound. A TreePathScanner is used only to get each method's
     * TreePath for the fact-only summary name; the actual work is per-``MethodTree``. */
    private static void collectFinalParamTargets(Parsed p, List<String> methods,
                                                  List<String> names, List<Long> offsets) {
        new TreePathScanner<Void, Void>() {
            @Override
            public Void visitMethod(MethodTree node, Void unused) {
                considerFinalParamMethod(node, getCurrentPath(), p, methods, names, offsets);
                return super.visitMethod(node, unused);
            }
        }.scan(p.unit, null);
    }

    private static void considerFinalParamMethod(MethodTree method, TreePath path, Parsed p,
                                                  List<String> methods, List<String> names,
                                                  List<Long> offsets) {
        BlockTree body = method.getBody();
        // REFUSE the WHOLE method: an abstract/interface method or a native method has
        // NO body (`getBody()` is null) — nothing to scan, so its parameters are
        // skipped rather than vacuously accepted (a body-less method could be
        // implemented/overridden anywhere with a reassigning body we cannot see).
        if (body == null) {
            return;
        }
        Set<String> reassigned = collectAssignedNames(body);
        String summary = summaryName(method, path);
        for (VariableTree param : method.getParameters()) {
            considerFinalParam(param, p, reassigned, summary, methods, names, offsets);
        }
    }

    private static void considerFinalParam(VariableTree param, Parsed p,
                                           Set<String> reassigned, String methodSummary,
                                           List<String> methods, List<String> names,
                                           List<Long> offsets) {
        String name = String.valueOf(param.getName());
        // REFUSE: already final — nothing to add (the idempotency guard).
        if (param.getModifiers().getFlags().contains(Modifier.FINAL)) {
            return;
        }
        // REFUSE: reassigned anywhere in THIS method's own body (`=`, `+=`, `++`/`--`)
        // — sealing it `final` would be a COMPILE ERROR, not a runtime no-op.
        if (reassigned.contains(name)) {
            return;
        }
        long insert = paramInsertOffset(param, p);
        if (insert < 0) {
            return;  // an unreadable parameter span — refuse rather than splice at a guess
        }
        methods.add(methodSummary);
        names.add(name);
        offsets.add(insert);
    }

    /** The byte offset of the parameter's own START (its type token, just past any
     * annotations — `VariableTree.getStartPosition` via the positions table already
     * skips leading annotations to the type), or -1 when the span is unreadable.
     * Splicing `"final "` here reads `final <Type> <name>`. */
    private static long paramInsertOffset(VariableTree param, Parsed p) {
        long start = p.positions.getStartPosition(p.unit, param);
        if (start >= 0 && start <= p.source.length()) {
            return start;
        }
        return -1;
    }

    // --- final-local-targets: never-reassigned local variable declarations ----

    private static void cmdFinalLocalTargets(String file) {
        Parsed p = parseOrRefuse(file);
        List<String> orderedMethods = new ArrayList<>();
        List<String> orderedNames = new ArrayList<>();
        List<Long> orderedOffsets = new ArrayList<>();
        collectFinalLocalTargets(p, orderedMethods, orderedNames, orderedOffsets);
        // Emit in source order (the method-declaration / statement order the scanner
        // visits — a per-method scan, exactly as final-param-targets).
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < orderedNames.size(); i++) {
            if (i > 0) {
                sb.append(",");
            }
            sb.append("{\"method\":");
            appendJsonString(sb, orderedMethods.get(i));
            sb.append(",\"name\":");
            appendJsonString(sb, orderedNames.get(i));
            sb.append(",\"insertOffset\":").append(orderedOffsets.get(i)).append("}");
        }
        sb.append("]");
        System.out.print(sb);
    }

    /** Every method/constructor's never-reassigned DIRECT-BLOCK-STATEMENT local
     * variables, scanned ONE method at a time (the exact spine
     * `collectFinalParamTargets` uses): a local's ENTIRE assignment surface is its own
     * method's body (no other code — not another method, not reflection — can write a
     * Java local), so a per-method scan is both sufficient and sound. A TreePathScanner
     * is used only to get each method's TreePath for the fact-only summary name; the
     * actual work is per-``MethodTree``. */
    private static void collectFinalLocalTargets(Parsed p, List<String> methods,
                                                 List<String> names, List<Long> offsets) {
        new TreePathScanner<Void, Void>() {
            @Override
            public Void visitMethod(MethodTree node, Void unused) {
                considerFinalLocalMethod(node, getCurrentPath(), p, methods, names, offsets);
                return super.visitMethod(node, unused);
            }
        }.scan(p.unit, null);
    }

    private static void considerFinalLocalMethod(MethodTree method, TreePath path, Parsed p,
                                                 List<String> methods, List<String> names,
                                                 List<Long> offsets) {
        BlockTree body = method.getBody();
        // REFUSE the WHOLE method: an abstract/interface method or a native method has
        // NO body (`getBody()` is null) — nothing to scan, so it declares no locals.
        if (body == null) {
            return;
        }
        Set<String> reassigned = collectAssignedNames(body);
        Set<String> captured = collectCapturedNames(body);
        String summary = summaryName(method, path);
        // SCOPE BOUNDARY (explicit, not accidental): iterate ONLY the DIRECT statements
        // of the body block. A for-loop init var (ForLoopTree), an enhanced-for var
        // (EnhancedForLoopTree), and a try-with-resources resource (TryTree.getResources())
        // are NOT block statements, so they are excluded here BY OMISSION — a plain
        // `VariableTree` is the only statement shape considered. A local captured by a
        // lambda / anonymous inner class IS a block statement, so it is refused
        // EXPLICITLY in considerFinalLocal (via `captured`), not by omission.
        // This deliberately mirrors the parameter scan: only the shape whose whole
        // assignment surface is provably closed is sealed.
        for (StatementTree statement : body.getStatements()) {
            if (statement instanceof VariableTree) {
                considerFinalLocal((VariableTree) statement, p, reassigned, captured,
                        summary, methods, names, offsets);
            }
        }
    }

    private static void considerFinalLocal(VariableTree local, Parsed p,
                                           Set<String> reassigned, Set<String> captured,
                                           String methodSummary,
                                           List<String> methods, List<String> names,
                                           List<Long> offsets) {
        String name = String.valueOf(local.getName());
        // REFUSE: already final — nothing to add (the idempotency guard).
        if (local.getModifiers().getFlags().contains(Modifier.FINAL)) {
            return;
        }
        // REFUSE: no initializer (`int x;` with the assignment split off). Sealing a
        // definitely-assigned-once split local needs definite-assignment analysis the
        // parse-only oracle cannot do; scope to the initializer-bearing shape, which
        // always compiles when sealed — the local analogue of java-finalize-field's
        // blank-`final` refusal.
        if (local.getInitializer() == null) {
            return;
        }
        // REFUSE: reassigned anywhere in THIS method's own body (`=`, `+=`, `++`/`--`)
        // — sealing it `final` would be a COMPILE ERROR, not a runtime no-op.
        if (reassigned.contains(name)) {
            return;
        }
        // REFUSE (EXPLICIT, conservative): a local captured by a lambda / anonymous
        // inner class. Such a local is already effectively-final (javac enforces it),
        // so sealing it WOULD compile — but this first cut deliberately declines to
        // reason about capture semantics and leaves the seal on the table rather than
        // risk it. Over-refusal is safe; it never seals a variable it should not.
        if (captured.contains(name)) {
            return;
        }
        long insert = localInsertOffset(local, p);
        if (insert < 0) {
            return;  // an unreadable local span — refuse rather than splice at a guess
        }
        methods.add(methodSummary);
        names.add(name);
        offsets.add(insert);
    }

    /** The byte offset of the local's own START (its type token, just past any
     * annotations — `VariableTree.getStartPosition` via the positions table already
     * skips leading annotations to the type), or -1 when the span is unreadable.
     * Splicing `"final "` here reads `final <Type> <name> = ...`. */
    private static long localInsertOffset(VariableTree local, Parsed p) {
        long start = p.positions.getStartPosition(p.unit, local);
        if (start >= 0 && start <= p.source.length()) {
            return start;
        }
        return -1;
    }

    // --- JSON emit (fixed key order, deterministic) --------------------------

    private static void appendStringList(StringBuilder sb, List<String> values) {
        sb.append("[");
        for (int i = 0; i < values.size(); i++) {  // source order — NOT sorted
            if (i > 0) {
                sb.append(",");
            }
            appendJsonString(sb, values.get(i));
        }
        sb.append("]");
    }

    private static void appendStringArray(StringBuilder sb, Set<String> values) {
        sb.append("[");
        boolean first = true;
        for (String value : values) {  // TreeSet -> already sorted, deterministic
            if (!first) {
                sb.append(",");
            }
            first = false;
            appendJsonString(sb, value);
        }
        sb.append("]");
    }

    private static void appendJsonString(StringBuilder sb, String raw) {
        sb.append('"');
        for (int i = 0; i < raw.length(); i++) {
            char c = raw.charAt(i);
            switch (c) {
                case '"':
                    sb.append("\\\"");
                    break;
                case '\\':
                    sb.append("\\\\");
                    break;
                case '\n':
                    sb.append("\\n");
                    break;
                case '\r':
                    sb.append("\\r");
                    break;
                case '\t':
                    sb.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        sb.append('"');
    }

    // --- dispatch ------------------------------------------------------------

    private static Parsed fail(String message) {
        System.err.println(message);
        System.exit(REFUSE);
        throw new IllegalStateException("unreachable");  // System.exit does not return
    }

    public static void main(String[] args) {
        if (args.length == 2 && "parse-verify".equals(args[0])) {
            cmdParseVerify(args[1]);
            return;
        }
        if (args.length == 2 && "final-targets".equals(args[0])) {
            cmdFinalTargets(args[1]);
            return;
        }
        if (args.length == 2 && "doc-targets".equals(args[0])) {
            cmdDocTargets(args[1]);
            return;
        }
        if (args.length == 2 && "param-targets".equals(args[0])) {
            cmdParamTargets(args[1]);
            return;
        }
        if (args.length == 2 && "return-targets".equals(args[0])) {
            cmdReturnTargets(args[1]);
            return;
        }
        if (args.length == 2 && "final-param-targets".equals(args[0])) {
            cmdFinalParamTargets(args[1]);
            return;
        }
        if (args.length == 2 && "final-local-targets".equals(args[0])) {
            cmdFinalLocalTargets(args[1]);
            return;
        }
        System.err.println("usage: ApexJavaDriver.java parse-verify <file> | "
                + "final-targets <file> | doc-targets <file> | param-targets <file> | "
                + "return-targets <file> | final-param-targets <file> | "
                + "final-local-targets <file>");
        System.exit(REFUSE);
    }
}
