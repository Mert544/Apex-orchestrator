"""Golden snapshot of discover_structured at base HEAD. Auto-generated."""

GOLDEN = [[],
 [],
 [{'key': 'assoc:debt>untested',
   'text': 'on this codebase, 100% of `debt` modules are also `untested` (2 module(s)) — a '
           'discovered association, not a coded rule.',
   'kind': 'association',
   'confidence': 1.0,
   'support': 2}],
 [{'key': 'assoc:single-author>high-churn',
   'text': 'on this codebase, 100% of `single-author` modules are also `high-churn` (2 module(s)) '
           '— a discovered association, not a coded rule.',
   'kind': 'association',
   'confidence': 1.0,
   'support': 2}],
 [{'key': 'confluence:app/hot.py',
   'text': '`app/hot.py` is a confluence — 4 distinct signals at once (debt, fragile, security, '
           'untested); no single lens names it.',
   'kind': 'confluence',
   'confidence': 0.8,
   'support': 4}],
 [{'key': 'assoc:fragile>security',
   'text': 'on this codebase, 100% of `fragile` modules are also `security` (3 module(s)) — a '
           'discovered association, not a coded rule.',
   'kind': 'association',
   'confidence': 1.0,
   'support': 3},
  {'key': 'assoc:fragile>untested',
   'text': 'on this codebase, 100% of `fragile` modules are also `untested` (3 module(s)) — a '
           'discovered association, not a coded rule.',
   'kind': 'association',
   'confidence': 1.0,
   'support': 3},
  {'key': 'assoc:security>untested',
   'text': 'on this codebase, 100% of `security` modules are also `untested` (3 module(s)) — a '
           'discovered association, not a coded rule.',
   'kind': 'association',
   'confidence': 1.0,
   'support': 3},
  {'key': 'triple:fragile&security>untested',
   'text': 'higher-order rule: modules that are both `fragile` and `security` are 100% also '
           '`untested` (3 module(s)).',
   'kind': 'triple',
   'confidence': 1.0,
   'support': 3},
  {'key': 'triple:fragile&untested>security',
   'text': 'higher-order rule: modules that are both `fragile` and `untested` are 100% also '
           '`security` (3 module(s)).',
   'kind': 'triple',
   'confidence': 1.0,
   'support': 3}],
 [{'key': 'assoc:co-change>untested',
   'text': 'on this codebase, 100% of `co-change` modules are also `untested` (4 module(s)) — a '
           'discovered association, not a coded rule.',
   'kind': 'association',
   'confidence': 1.0,
   'support': 4},
  {'key': 'assoc:fragile>untested',
   'text': 'on this codebase, 100% of `fragile` modules are also `untested` (4 module(s)) — a '
           'discovered association, not a coded rule.',
   'kind': 'association',
   'confidence': 1.0,
   'support': 4},
  {'key': 'assoc:debt>fragile',
   'text': 'on this codebase, 100% of `debt` modules are also `fragile` (3 module(s)) — a '
           'discovered association, not a coded rule.',
   'kind': 'association',
   'confidence': 1.0,
   'support': 3},
  {'key': 'assoc:debt>untested',
   'text': 'on this codebase, 100% of `debt` modules are also `untested` (3 module(s)) — a '
           'discovered association, not a coded rule.',
   'kind': 'association',
   'confidence': 1.0,
   'support': 3},
  {'key': 'triple:co-change&fragile>security',
   'text': 'higher-order rule: modules that are both `co-change` and `fragile` are 100% also '
           '`security` (3 module(s)).',
   'kind': 'triple',
   'confidence': 1.0,
   'support': 3},
  {'key': 'triple:co-change&fragile>untested',
   'text': 'higher-order rule: modules that are both `co-change` and `fragile` are 100% also '
           '`untested` (3 module(s)).',
   'kind': 'triple',
   'confidence': 1.0,
   'support': 3},
  {'key': 'confluence:m1',
   'text': '`m1` is a confluence — 11 distinct signals at once (co-change, correctness-bug, '
           'critical-untested, debt, fragile, high-churn, mutable-defaults, security, '
           'sensitive-path, single-author, untested); no single lens names it.',
   'kind': 'confluence',
   'confidence': 0.579,
   'support': 11},
  {'key': 'confluence:m2',
   'text': '`m2` is a confluence — 11 distinct signals at once (co-change, complex-function, '
           'complexity, correctness-bug, critical-untested, fragile, high-churn, security, '
           'shallow-tests, symbol-hub, untested); no single lens names it.',
   'kind': 'confluence',
   'confidence': 0.579,
   'support': 11}],
 [{'key': 'assoc:debt>untested',
   'text': 'on this codebase, 100% of `debt` modules are also `untested` (2 module(s)) — a '
           'discovered association, not a coded rule.',
   'kind': 'association',
   'confidence': 1.0,
   'support': 2}],
 [{'key': 'assoc:debt>untested',
   'text': 'on this codebase, 100% of `debt` modules are also `untested` (2 module(s)) — a '
           'discovered association, not a coded rule.',
   'kind': 'association',
   'confidence': 1.0,
   'support': 2}]]
