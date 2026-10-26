# 0007 — Raw facts in the profile, rules read by the model, arithmetic in code

**Status:** accepted · 2026-10-26

## Context
Eligibility rules vary by tender: turnover averaged over 3 or 5 years, in each year, in any
one year, best 3 of 5; periods ending on a stated date or the last completed financial year.
A single "annual turnover" number can't answer these, and per-tender code would never end.

## Decision
1. **Profiles hold raw facts.** Turnover is stored per Indian financial year
   (`company_profiles.turnover_by_year`), read from uploaded **CA turnover certificates**
   (`company_documents`) or typed by the user, plus the incorporation date (from Udyam).
   Certificate figures are kept only if their quote is found in the certificate text.
2. **The model extracts the rule, not the answer.** For a turnover criterion it calls
   `check_turnover(aggregation, years, best_k, amount, period_end)` with the rule as written.
3. **Code decides** (`core/agent/turnover.py`): picks the financial years, compares them with
   the incorporation date, finds missing years, computes, compares. Outcomes:
   met / not_met / missing_data (unclear + "upload a CA turnover certificate for FY …") /
   company_too_young (not_met unless an exemption applies).
4. New rule *types* are added to the tool when real tenders need them; new tenders never need
   code changes.

## Related changes
- Matching no longer excludes tenders by value ÷ turnover ratio; the eligibility check applies
  each tender's own rule.
- Corrigenda always trigger re-checks for matched orgs (no keyword guessing).
- Planning includes every clause of the sections where eligibility hits were found.

## Next candidates for the same pattern
Similar-work experience (projects with value, date, type), net worth / solvency certificates,
certification validity on the bid date.
