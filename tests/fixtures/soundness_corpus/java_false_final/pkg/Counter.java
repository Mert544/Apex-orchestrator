package pkg;

// A Java FALSE-`final` TRAP for the soundness corpus — the Java analogue of the
// Python provenance_trap / the JS jsdoc_contradiction shape. The private field
// `counter` LOOKS never-reassigned to a naive analyser that only scans the
// enclosing class's OWN methods (`read()` merely reads it) — but the nested inner
// class `Worker` REASSIGNS it. Adding `final` here would be a COMPILE ERROR
// (`cannot assign a value to final variable counter`), so it is NOT a runtime
// no-op and java-finalize-field MUST REFUSE this field, never seal it.
//
// The objective's soundness rests on scanning the WHOLE file's assignment surface
// (a private field cannot be written from outside its file): the driver's
// whole-file TreeScanner sees the inner-class reassignment and omits `counter` from
// final-targets, so the objective lands NOTHING here. This fixture is the standing,
// in-repo proof that the never-reassigned scan is whole-file, not method-local.
public class Counter {
    private int counter = 0;

    class Worker {
        void bump() {
            counter = counter + 1;  // reassignment HIDDEN in a nested inner class
        }
    }

    int read() {
        return counter;
    }
}
