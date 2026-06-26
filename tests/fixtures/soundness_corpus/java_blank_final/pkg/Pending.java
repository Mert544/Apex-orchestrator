package pkg;

// A Java BLANK-`final` TRAP for the soundness corpus — the never-assigned analogue of
// the java_false_final shape. The private field `pending` has NO initializer and is
// NEVER assigned anywhere (no constructor, no method writes it), so a never-reassigned
// scan that only looks for re-writes sees it as a finalisation candidate. But sealing
// it `final` is a COMPILE ERROR, not a runtime no-op: a blank `final` instance field
// must be definitely assigned by the end of every constructor (JLS §16), and the
// implicit default constructor assigns nothing.
//
// The parse-only Tier-A oracle cannot run definite-assignment analysis, so the
// objective MUST refuse a blank, never-assigned field — only an initializer-bearing
// (definitely-assigned) field is ever sealed. This fixture is the standing, in-repo
// proof that java-finalize-field refuses to emit a blank `final` it cannot prove
// compiles.
public class Pending {
    private String pending;

    String read() {
        return pending;
    }
}
