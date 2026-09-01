"""Optional in-process access to tingbok, for when the service does not answer.

inventory-md normally asks a running tingbok over HTTP.  If that fails and the
``tingbok`` package happens to be installed alongside — which it is on the
machine that also *runs* tingbok, and anywhere the ``tingbok`` extra was asked
for — the same questions can be answered in-process instead of the run
degrading to a vocabulary-less parse.

Strictly optional.  The common case is a client with no tingbok installed at
all, and that must behave exactly as it did before: :func:`get_module` returns
``None``, every caller carries on with whatever it does when tingbok is
unreachable, and nothing is logged above debug level.

Only reads are routed this way.  An EAN observation is a write to the service's
data file, and writing it into a local copy would create a divergence nobody
asked for; a failed push stays a failed push.
"""

from __future__ import annotations

import logging
from types import ModuleType

logger = logging.getLogger(__name__)

#: ``None`` before the first attempt, ``False`` once an attempt has failed.
#: Distinguishing the two keeps a missing package from being re-imported on
#: every call — the import machinery caches failures poorly and this sits on a
#: path taken once per unreachable request.
_module: ModuleType | None | bool = None


def reset() -> None:
    """Forget whether tingbok is importable.  For tests."""
    global _module
    _module = None


def get_module() -> ModuleType | None:
    """Return :mod:`tingbok.embedded`, or ``None`` if it is not installed."""
    global _module
    if _module is False:
        return None
    if _module is not None:
        return _module  # type: ignore[return-value]
    try:
        from tingbok import embedded  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — any import failure means "not available"
        logger.debug("No in-process tingbok available: %s", exc)
        _module = False
        return None
    if embedded is None:  # a test may have stubbed the module out
        _module = False
        return None
    _module = embedded
    return embedded


def call(function: str, *args, **kwargs):
    """Call *function* on the embedded tingbok, returning ``None`` if it cannot.

    Swallows failures on purpose: this is a fallback for a call that has already
    failed once, and an installed-but-unhappy tingbok (no ``vocabulary.yaml``,
    say) should leave the caller with the original error rather than a new one.
    """
    module = get_module()
    if module is None:
        return None
    try:
        return getattr(module, function)(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.debug("In-process tingbok %s() failed: %s", function, exc)
        return None
