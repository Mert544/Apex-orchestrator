package pkg;

// A Java REASSIGNED-LOCAL TRAP for the soundness corpus — the local-variable
// analogue of the parameter trap `java_reassigned_param` (which flags a declared
// parameter reassigned in its own body). The local `running` is declared as a
// direct block statement WITH an initializer (`int running = 0;`), so it LOOKS
// never-reassigned from its declaration alone — but the method BODY reassigns it
// with a plain `=` (`running = running + 1;`) before returning. Adding `final` to
// it would be a COMPILE ERROR (`variable running might already have been assigned`
// / `cannot assign a value to final variable running`), so it is NOT a runtime
// no-op and java-final-local MUST REFUSE this local, never seal it.
//
// The objective's soundness rests on scanning the WHOLE of the local's OWN method
// body (a local's entire assignment surface is closed to its own method — no
// reflection, no other file, no other method can ever write a Java local): the
// driver's per-method scan sees the reassignment and omits `running` from
// final-local-targets, so the objective lands NOTHING here. This fixture is the
// standing, in-repo proof that the never-reassigned scan is per-method-body, not
// declaration-only.
//
// It deliberately declares NO OTHER block-statement local (only the reassigned
// `running`, so no landable local blurs this trap), NO parameter (so
// java-final-parameter also finds nothing to seal and cleanly refuses), NO private
// instance field, and NO `throws` clause — so java-finalize-field / java-document-
// throws (also swept over this fixture) find nothing and cleanly refuse. The method
// carries no Javadoc, so java-document-param / java-document-returns land a
// behaviour-identical Javadoc — expected, and disjoint from this trap (this fixture
// pins only the final-local boundary).
public class Running {

    int accumulate() {
        int running = 0;
        running = running + 1;
        return running;
    }
}
