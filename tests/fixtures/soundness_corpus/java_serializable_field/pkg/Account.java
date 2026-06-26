package pkg;

import java.io.Serializable;

// A Java SERIALIZABLE-FIELD TRAP for the soundness corpus — the deserialization
// sibling of java_reflective_field. The private field `id` is NEVER the target of a
// syntactic assignment in this file (`read()` only reads it; the initializer is the
// only `=`), so a scan trusting "every write is syntactic" would seal it `final`.
// But this class `implements Serializable`: Java's object deserializer
// (`ObjectInputStream.readObject` -> `defaultReadObject`) sets `id` REFLECTIVELY from
// the stream, BYPASSING the `=` surface. Sealing `id` `final` breaks that
// round-trip at RUNTIME (the deserialized value cannot be assigned to a `final`
// field) — a real breakage the structural fact-set re-parse oracle CANNOT catch
// (`final` is not a declared type/field/method fact).
//
// java-finalize-field MUST refuse the WHOLE unit here: a deserializer can set ANY
// private field of a Serializable class, and a single-file parser cannot prove which
// the stream leaves alone. The driver refuses on the `implements Serializable`
// clause. This is the standing, in-repo proof that the never-reassigned scan accounts
// for deserialization.
public class Account implements Serializable {
    private int id = 0;

    int read() {
        return id;
    }
}
