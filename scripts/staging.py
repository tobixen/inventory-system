"""Canonical staging-file schema, shared by every consumer.

A reviewed shopping staging file is **flat single-shop**: one file per shop
visit, with top-level ``session`` (date), ``shop``, ``currency`` and ``items``.
This is what ``shop_import.py`` emits and what ``ledger.py`` / ``tingbok_push.py``
consume.

An earlier design wrapped several shops in a top-level ``shops:`` list. That is
retired — a shopping trip spanning two shops is two independent staging files.
Feeding the old layout to a flat consumer used to import 0 rows *silently*
(docs/shopping-pipeline-issues-2026-06-07.md, issue 1), so consumers now reject
it loudly via :func:`require_flat`.

Per-item money/quantity fields (each entry of ``items:``):

* ``price``      — the **unit price in the line's ``unit``**. For ``pcs`` it is
  the price of one piece; for a weighed line (``unit: kg``) it is the per-kg
  price, *not* the price paid for the line.
* ``qty``        — quantity in the same ``unit`` (e.g. ``1.768`` for 1.768 kg).
* ``line_total`` — the **net** amount actually charged for the line, as printed
  on the receipt. **This is authoritative** and should be trusted over
  ``price * qty``: for weighed goods ``price * qty`` re-derives the total from
  rounded inputs and can be off by a cent. ``shop_import`` always emits
  ``line_total``; consumers fall back to ``round(price * qty, 2)`` only when it
  is missing.

Per-item discount fields — present **only on a discounted line**, absent
otherwise (so hand-transcribed and undiscounted receipts stay clean; a consumer
must treat their absence as "no discount", never as zero):

* ``line_total_gross`` — the pre-discount line amount.
* ``line_discount``    — ``line_total_gross - line_total`` (the saving).
* ``price_net``        — the net per-unit price (``line_total / qty``); this is
  what the Open Prices publisher posts as the paid price, with
  ``line_total_gross`` supplied as ``--discount EAN=GROSS``.
* ``discounts``        — a list (a line can carry several discounts of different
  kinds — e.g. a Lidl Plus coupon *and* a short-expiry markdown), each
  ``{amount, type, openprices_type, label[, percent]}``. ``type`` is the raw kind
  (``lidlplus_coupon`` / ``markdown``); ``openprices_type`` is the mapped Open
  Prices ``discount_type`` (``LOYALTY_PROGRAM`` / ``EXPIRES_SOON`` / ``SALE``).

Top-level money fields: ``receipt_total`` is the **net** charged total;
``receipt_total_gross`` and ``receipt_discount_total`` surface the pre-discount
total and the saving so a reviewer sees both.

Per-item routing flags:

* ``to_tingbok`` — set ``true`` to push a price/receipt-name observation to
  tingbok, ``false`` to skip (e.g. no barcode, by-weight produce). Must be set
  **explicitly** during the review step; ``shop_import`` emits ``null`` as a
  deliberate reminder. ``tingbok_push.py`` skips items where this is falsy and
  warns loudly if *every* item was skipped (which usually means the flag was
  never filled in).
"""

from __future__ import annotations

from typing import Any


def require_flat(staging: Any) -> dict[str, Any]:
    """Validate the canonical flat single-shop schema; return it unchanged.

    Raises ``ValueError`` if *staging* is not a mapping or still carries the
    retired multi-shop ``shops:`` wrapper.
    """
    if not isinstance(staging, dict):
        raise ValueError("staging must be a mapping (flat single-shop schema)")
    if "shops" in staging:
        raise ValueError(
            "multi-shop 'shops:' staging is no longer supported; split the trip into one flat file per shop visit"
        )
    return staging
