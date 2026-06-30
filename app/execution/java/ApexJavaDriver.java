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
//
// Determinism: no clock, no randomness; types/fields/methods are SORTED, targets are
// reported in source order; JSON keys are emitted in a fixed order. `insertOffset`
// comes from `SourcePositions` (a byte offset into the source), so a splice is a
// precise byte insert, never an AST unparse — the surrounding source is untouched.

import com.sun.source.tree.AssignmentTree;
import com.sun.source.tree.ClassTree;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.CompoundAssignmentTree;
import com.sun.source.tree.ExpressionTree;
import com.sun.source.tree.IdentifierTree;
import com.sun.source.tree.ImportTree;
import com.sun.source.tree.MemberSelectTree;
import com.sun.source.tree.MethodInvocationTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.tree.ModifiersTree;
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

    /** The simple names that are an assignment TARGET anywhere in the file — a plain
     * `=`, a compound `+=`/`-=`/..., or a `++`/`--`. Conservative: for a member
     * select (`this.b`, `obj.b`) we record the trailing identifier, so a write to
     * ANY `.b` marks the field `b` reassigned (soundness over recall — we never
     * want a false `final`). */
    private static Set<String> collectAssignedNames(CompilationUnitTree unit) {
        Set<String> assigned = new HashSet<>();
        new TreePathScanner<Void, Void>() {
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
        }.scan(unit, null);
        return assigned;
    }

    private static void recordTarget(ExpressionTree target, Set<String> assigned) {
        if (target instanceof IdentifierTree) {
            assigned.add(String.valueOf(((IdentifierTree) target).getName()));
        } else if (target instanceof MemberSelectTree) {
            assigned.add(String.valueOf(((MemberSelectTree) target).getIdentifier()));
        }
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
        names.add(String.valueOf(method.getName()));
        throwsLists.add(types);
        offsets.add(insert);
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
        names.add(String.valueOf(method.getName()));
        paramLists.add(params);
        offsets.add(insert);
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
        System.err.println("usage: ApexJavaDriver.java parse-verify <file> | "
                + "final-targets <file> | doc-targets <file> | param-targets <file>");
        System.exit(REFUSE);
    }
}
