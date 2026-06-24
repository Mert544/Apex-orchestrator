# A deliberately non-parseable module.
#
# ADVERSARIAL SHAPE: EVERY objective must refuse on source that does not parse
# (the rewriters drop a malformed splice rather than land it). No objective may
# produce a plan that rewrites this file.

def broken(:
    return "this does not parse"
