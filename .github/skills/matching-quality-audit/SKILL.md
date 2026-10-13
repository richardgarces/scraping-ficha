---
name: matching-quality-audit
description: "Use when implementing, changing, running, or reviewing product-matching audits, stratified samples, human labels, reviewer agreement, Cohen's kappa, arbitration, or CSV exports."
---

# Auditoría de calidad del matching

Use this workflow for matching-quality work in the retail catalog. Read
[`docs/README_auditorias_calidad.md`](../../../docs/README_auditorias_calidad.md)
and inspect `retail/matching_audit.py`,
`retail/web/matching_audit_api.py`, and their tests before changing behavior.

## Requirements

- Reuse the current sample contract: at most 300 searches and up to three
  product comparisons per search. Preserve category × store × frequency
  stratification, proportional allocation, and the saved random seed.
- Preserve the four labels (`exact`, `variant`, `not_equivalent`, `uncertain`),
  two independent reviewers, optional notes, and third-person arbitration.
- Keep the audit disabled by default and enforce the administrative role and
  enablement setting in every API route as well as the UI.
- Calculate exact-match precision only over conclusive final labels. Calculate
  nominal Cohen's kappa for stable reviewer pairs; do not replace an undefined
  value with a fabricated score.
- Keep run and review history; exports must preserve the recorded snapshots and
  reviewer/arbitration results.

## Procedure

1. Trace the current persistence, route authorization, and UI flow before edits.
2. Add focused tests for sampling boundaries, reviewer independence,
   disagreement arbitration, permissions, metrics, and CSV shape as applicable.
3. Run the relevant audit tests and report the sample definition and metric
   denominators when summarizing results.
