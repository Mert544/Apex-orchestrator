"""Apex's Java support package — the bundled ``ApexJavaDriver.java`` and its thin
Python bridge :mod:`app.execution.java.java_tool`.

The Java sibling of :mod:`app.execution.js`: a single checked-in driver (run as a
JDK source-file launcher, ``java ApexJavaDriver.java <subcommand> <file>``) plus the
one Python module that knows the ``java`` invocation. Parse-only, offline, zero
third-party jars — the parser is the JDK's OWN Compiler Tree API.
"""
