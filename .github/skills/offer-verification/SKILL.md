---
name: offer-verification
description: "Use when building, changing, running, or reviewing checks of published offers, store URLs, price/stock/promotion verification, robots.txt compliance, rate limits, historical runs, or discrepancy reports."
---

# Verificación de ofertas publicadas

Before changing this workflow, read
[`docs/README_auditorias_calidad.md`](../../../docs/README_auditorias_calidad.md)
and inspect `retail/offer_verification.py`, its store parsers, persistence, and
tests.

## Requirements

- Verify only eligible published offers; never repair or republish a listing as
  a side effect of an audit.
- Respect each store's `robots.txt`, `Crawl-delay`, `Request-rate`, and the
  shared per-origin rate limiter. Restrict requests and redirects to registered
  store domains.
- Compare base price, card price, coupon conditions, stock, and shipping
  independently. Do not infer a missing value or compare shipping across
  different locations.
- Record verification timestamps and source outcomes. If a parser, robots
  policy, or source cannot verify a field, report it as unverified rather than
  as a match or discrepancy.
- Preserve each run and its snapshots. Report link functionality, comparable
  price denominators, absolute/relative discrepancy magnitude, and historical
  comparison windows explicitly.

## Procedure

1. Trace candidate selection, network policy, parser evidence, persistence, and
   report generation before editing.
2. Test robots denial, redirect/domain limits, rate limiting, unverifiable
   fields, discrepancy calculations, and failed persistence where relevant.
3. Run the focused offer-verification tests; do not run a production scrape or
   data-writing job without explicit authorization.
