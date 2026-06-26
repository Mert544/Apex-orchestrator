package pkg;

import java.lang.reflect.Field;

// A Java REFLECTIVE-WRITE TRAP for the soundness corpus — the second Java false-`final`
// shape (alongside java_false_final's nested-inner-class reassignment). The private
// field `secret` is NEVER the target of a syntactic assignment (`=` / `+=` / `++`):
// `read()` only reads it. A scan that trusts "every write to a private field is a
// syntactic assignment in this file" would seal it `final`. But `poke()` WRITES it
// reflectively via `java.lang.reflect.Field.setInt`, which BYPASSES the `=` surface
// entirely. Sealing `secret` `final` makes `f.setInt(this, 99)` throw
// `IllegalAccessException` / no-op at RUNTIME — a real breakage the structural
// fact-set re-parse oracle CANNOT catch (`final` is not a declared type/field/method
// fact, so the spliced file re-parses fact-identical and would wrongly pass).
//
// java-finalize-field MUST refuse the WHOLE unit here: a reflective writer can set
// ANY private field without a syntactic assignment, and a single-file parser cannot
// prove WHICH field it leaves alone. The driver refuses on the `java.lang.reflect`
// import (and on the `setAccessible`/`setInt` member-select invocations). This is the
// standing, in-repo proof that the never-reassigned scan accounts for reflection.
public class Reflective {
    private int secret = 0;

    void poke() throws Exception {
        Field f = Reflective.class.getDeclaredField("secret");
        f.setAccessible(true);
        f.setInt(this, 99);  // reflective write — NO syntactic `=` for the scan to see
    }

    int read() {
        return secret;
    }
}
