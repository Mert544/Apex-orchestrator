"""The submodule whose ``public_fn`` the package ``__init__`` re-exports."""


def public_fn():
    """The package's public entry point, surfaced as ``pkg.public_fn``."""
    return 42
