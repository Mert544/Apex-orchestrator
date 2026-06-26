package pkg;

import java.io.IOException;

// A Java UNDOCUMENTED-THROWS LANDABLE for the soundness corpus — the standing, in-repo
// proof that java-document-throws lands a behaviour-identical `@throws` Javadoc.
//
// The method `load` DECLARES a `throws IOException` clause but carries NO Javadoc, so
// java-document-throws documents it with a FRESH Javadoc block: one `@throws IOException`
// line drawn from the DECLARED throws clause verbatim (NOT inferred from any
// `throw new X()` statement). A Javadoc is a COMMENT, so the edit changes ZERO declared
// structure (types/fields/method-signatures) and the sealed file re-parses with the
// IDENTICAL fact-set — BEHAVIOUR-IDENTICAL by construction, Tier-A (no Maven/Gradle/JUnit
// run). This shape is therefore a LANDABLE, NOT a `_SHAPE_MUST_REFUSE` trap.
//
// It deliberately declares NO private instance field, so java-finalize-field (which is
// also swept over this fixture) finds nothing to finalise and cleanly REFUSES — exactly
// as the java_false_final / java_blank_final fixtures lack a `throws` clause and so are
// cleanly refused by java-document-throws. Each Java objective lands ONLY its own shape.
public class Loader {

    int load(String path) throws IOException {
        throw new IOException(path);
    }
}
