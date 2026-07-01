package pkg;

// A Java REASSIGNED-PARAMETER TRAP for the soundness corpus — the parameter-level
// analogue of the field trap `java_false_final` (which flags an inner-class-hidden
// field reassignment). BOTH declared parameters LOOK never-reassigned from their
// declaration alone — but the method BODY reassigns each of them (`total = total +
// delta;` then `delta = 0;`) before returning. Adding `final` to either would be a
// COMPILE ERROR (`final parameter ... may not be assigned`), so neither is a
// runtime no-op and java-final-parameter MUST REFUSE this whole method's
// parameters, never seal one. (BOTH params are reassigned deliberately — a
// partially-landable method would blur this trap with the java_undocumented_params
// LANDABLE shape, which also declares an `add(int a, int b)`-style method.)
//
// The objective's soundness rests on scanning the WHOLE of the parameter's OWN
// method body (a parameter's entire assignment surface is closed to its own method
// — no reflection, no other file, no other method can ever write a Java local): the
// driver's per-method scan sees each reassignment and omits both `total` and
// `delta` from final-param-targets, so the objective lands NOTHING here.
//
// It deliberately declares no private instance field and no `throws` clause, so
// java-finalize-field / java-document-throws (also swept over this fixture) find
// nothing and cleanly refuse; the method carries no Javadoc, so java-document-param
// / java-document-returns land a behaviour-identical Javadoc — expected, and
// disjoint from this trap (this fixture pins only the final-parameter boundary).
public class Accumulator {

    int accumulate(int total, int delta) {
        total = total + delta;
        delta = 0;
        return total;
    }
}
