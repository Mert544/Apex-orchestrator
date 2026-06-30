package pkg;

// A Java CONTENT-FREE-RETURN TRAP for the soundness corpus — the standing, in-repo proof
// that java-document-returns REFUSES the shape with nothing meaningful to return.
//
// The method `flush` returns `void`, so a `@return` line documenting it would be
// content-free AND wrong — there is no value to return. The constructor `Sink()` has no
// return type at all (`MethodTree.getReturnType()` is null). java-document-returns
// documents ONLY a method with a DECLARED non-void return type, so it MUST REFUSE both and
// land NOTHING here (the direct analogue of the Python document-returns refusing a
// `None`/`NoReturn` head, and java-document-param refusing a zero-parameter method). This
// fixture is therefore a `_SHAPE_MUST_REFUSE` trap, NOT a landable.
//
// It deliberately declares NO private instance field, NO parameter, and NO `throws`
// clause, so java-finalize-field (no field to finalise), java-document-param (no
// parameter), and java-document-throws (no throws clause) — all also swept over this
// fixture — find nothing and cleanly REFUSE too. No Java objective lands anything here.
public class Sink {

    public Sink() {
    }

    public void flush() {
        return;
    }
}
