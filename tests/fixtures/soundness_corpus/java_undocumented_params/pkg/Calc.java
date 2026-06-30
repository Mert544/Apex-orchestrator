package pkg;

// A Java UNDOCUMENTED-PARAMS LANDABLE for the soundness corpus — the standing, in-repo
// proof that java-document-param lands a behaviour-identical bare-`@param` Javadoc.
//
// The method `add` DECLARES two parameters (`a`, `b`) but carries NO Javadoc, so
// java-document-param documents it with a FRESH Javadoc block: one bare `@param a` /
// `@param b` line drawn from the DECLARED parameter names verbatim (off
// `VariableTree.getName()`, no types — the standard Javadoc form). A Javadoc is a
// COMMENT, so the edit changes ZERO declared structure (types/fields/method-signatures)
// and the documented file re-parses with the IDENTICAL fact-set — BEHAVIOUR-IDENTICAL by
// construction, Tier-A (no Maven/Gradle/JUnit run). This shape is therefore a LANDABLE,
// NOT a `_SHAPE_MUST_REFUSE` trap.
//
// It deliberately declares NO private instance field and NO `throws` clause, so
// java-finalize-field (no field to finalise) and java-document-throws (no throws clause)
// — both also swept over this fixture — find nothing and cleanly REFUSE. Each Java
// objective lands ONLY its own shape.
public class Calc {

    public int add(int a, int b) {
        return a + b;
    }
}
