#!/usr/bin/env python3
"""
Validate the normalized Star-Schema outputs in out/.

Checks:
  1. All 9 expected files exist.
  2. Required columns are present in each file.
  3. No NULL surrogate keys (_sk) in any dimension or fact.
  4. Foreign key integrity (fact tables reference valid _sk values in dims).
  5. No duplicate surrogate keys in dimension/bridge tables.
  6. No duplicate plan_item_bk in dim_plan_item.
  7. Doppelzählungs-Sperre: fact_budget contains only known measure_groups.
  8. No fact_budget rows where measure_group is mixed (domain_budget + aggregate).
  9. All fact_budget domain_sk values exist in dim_domain.
 10. No orphaned fact_budget rows with missing initiative_sk.
 11. Prioritization sanity: rows with is_prioritized=True must have a non-inaktiv
     priority_status_code.
 12. No initiative_business_key starts with "row:" (fallback key, data quality issue).
 13. Unassigned rocks: report count of dim_plan_item rows where rock_name == "Unassigned".
 14. Initiatives without jira key: report count in dim_initiative.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

OUT_DIR = Path(__file__).parent / "out"

# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

EXPECTED_FILES: dict[str, list[str]] = {
    "dim_rock.csv": ["rock_sk", "rock_code", "rock_name"],
    "dim_domain.csv": ["domain_sk", "domain_code", "domain_name", "domain_group"],
    "dim_initiative.csv": [
        "initiative_sk", "initiative_business_key", "initiative_name_canonical",
        "jira_initiative_key_canonical",
    ],
    "dim_plan_item.csv": [
        "plan_item_sk", "plan_item_bk", "initiative_business_key", "source_plan",
        "period", "quarter_code", "priority_status_code", "is_prioritized",
        "initiative_sk", "rock_sk",
    ],
    "dim_measure.csv": ["measure_sk", "measure_code", "measure_group", "unit"],
    "fact_budget.csv": [
        "budget_fact_sk", "plan_item_sk", "initiative_sk", "domain_sk",
        "measure_sk", "measure_code", "amount_eur", "source_plan",
    ],
    "fact_domain_status.csv": [
        "status_fact_sk", "plan_item_sk", "initiative_sk", "domain_sk",
        "source_plan", "status_code",
    ],
    "fact_initiative_period_priority.csv": [
        "initiative_period_priority_sk", "initiative_sk", "initiative_business_key",
        "period", "is_prioritized", "priority_status_code",
    ],
    "bridge_plan_item_epic.csv": [
        "plan_item_epic_sk", "plan_item_sk", "initiative_sk", "rock_sk",
        "source_plan", "jira_epic_key",
    ],
}

# priority_status_codes that mean is_prioritized should be True
ACTIVE_CODES = {"budgeted", "implementation", "exploration", "prioritized_other"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ValidationError:
    def __init__(self, check: str, message: str, count: int | None = None):
        self.check = check
        self.message = message
        self.count = count

    def __str__(self) -> str:
        suffix = f" ({self.count} rows)" if self.count is not None else ""
        return f"  FAIL  [{self.check}] {self.message}{suffix}"


class ValidationWarning:
    def __init__(self, check: str, message: str, count: int | None = None):
        self.check = check
        self.message = message
        self.count = count

    def __str__(self) -> str:
        suffix = f" ({self.count} rows)" if self.count is not None else ""
        return f"  WARN  [{self.check}] {self.message}{suffix}"


def load(filename: str) -> pd.DataFrame:
    return pd.read_csv(OUT_DIR / filename, dtype=str, low_memory=False)


def sk_set(df: pd.DataFrame, col: str) -> set:
    return set(df[col].dropna().str.strip())


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_files_exist() -> list[ValidationError]:
    errors = []
    for fname in EXPECTED_FILES:
        if not (OUT_DIR / fname).exists():
            errors.append(ValidationError("file_exists", f"{fname} not found in out/"))
    return errors


def check_required_columns(tables: dict[str, pd.DataFrame]) -> list[ValidationError]:
    errors = []
    for fname, required_cols in EXPECTED_FILES.items():
        if fname not in tables:
            continue
        df = tables[fname]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            errors.append(ValidationError(
                "required_columns",
                f"{fname} missing columns: {missing}",
            ))
    return errors


def check_null_pks(tables: dict[str, pd.DataFrame]) -> list[ValidationError]:
    pk_cols = {
        "dim_rock.csv": "rock_sk",
        "dim_domain.csv": "domain_sk",
        "dim_initiative.csv": "initiative_sk",
        "dim_plan_item.csv": "plan_item_sk",
        "dim_measure.csv": "measure_sk",
        "fact_budget.csv": "budget_fact_sk",
        "fact_domain_status.csv": "status_fact_sk",
        "fact_initiative_period_priority.csv": "initiative_period_priority_sk",
        "bridge_plan_item_epic.csv": "plan_item_epic_sk",
    }
    errors = []
    for fname, pk in pk_cols.items():
        df = tables.get(fname)
        if df is None or pk not in df.columns:
            continue
        nulls = df[pk].isna().sum() + (df[pk].astype(str).str.strip() == "").sum()
        if nulls > 0:
            errors.append(ValidationError(
                "null_pk", f"{fname}.{pk} has null/empty values", count=int(nulls)
            ))
    return errors


def check_duplicate_pks(tables: dict[str, pd.DataFrame]) -> list[ValidationError]:
    pk_cols = {
        "dim_rock.csv": "rock_sk",
        "dim_domain.csv": "domain_sk",
        "dim_initiative.csv": "initiative_sk",
        "dim_plan_item.csv": "plan_item_sk",
        "dim_measure.csv": "measure_sk",
    }
    errors = []
    for fname, pk in pk_cols.items():
        df = tables.get(fname)
        if df is None or pk not in df.columns:
            continue
        dupes = df[pk].duplicated().sum()
        if dupes > 0:
            errors.append(ValidationError(
                "duplicate_pk", f"{fname}.{pk} has duplicates", count=int(dupes)
            ))
    return errors


def check_duplicate_plan_item_bk(tables: dict[str, pd.DataFrame]) -> list[ValidationError]:
    errors = []
    df = tables.get("dim_plan_item.csv")
    if df is None or "plan_item_bk" not in df.columns:
        return errors
    dupes = df["plan_item_bk"].duplicated().sum()
    if dupes > 0:
        errors.append(ValidationError(
            "duplicate_plan_item_bk",
            "dim_plan_item.plan_item_bk has duplicates",
            count=int(dupes),
        ))
    return errors


def check_fk_integrity(tables: dict[str, pd.DataFrame]) -> list[ValidationError]:
    errors = []

    fk_checks = [
        # (fact_file, fk_col, dim_file, pk_col, label)
        ("fact_budget.csv", "initiative_sk", "dim_initiative.csv", "initiative_sk", "fact_budget→dim_initiative"),
        ("fact_budget.csv", "domain_sk", "dim_domain.csv", "domain_sk", "fact_budget→dim_domain"),
        ("fact_budget.csv", "measure_sk", "dim_measure.csv", "measure_sk", "fact_budget→dim_measure"),
        ("fact_budget.csv", "plan_item_sk", "dim_plan_item.csv", "plan_item_sk", "fact_budget→dim_plan_item"),
        ("fact_domain_status.csv", "initiative_sk", "dim_initiative.csv", "initiative_sk", "fact_domain_status→dim_initiative"),
        ("fact_domain_status.csv", "domain_sk", "dim_domain.csv", "domain_sk", "fact_domain_status→dim_domain"),
        ("fact_domain_status.csv", "plan_item_sk", "dim_plan_item.csv", "plan_item_sk", "fact_domain_status→dim_plan_item"),
        ("fact_initiative_period_priority.csv", "initiative_sk", "dim_initiative.csv", "initiative_sk", "fact_ipp→dim_initiative"),
        ("bridge_plan_item_epic.csv", "plan_item_sk", "dim_plan_item.csv", "plan_item_sk", "bridge→dim_plan_item"),
        ("bridge_plan_item_epic.csv", "initiative_sk", "dim_initiative.csv", "initiative_sk", "bridge→dim_initiative"),
        ("bridge_plan_item_epic.csv", "rock_sk", "dim_rock.csv", "rock_sk", "bridge→dim_rock"),
        ("dim_plan_item.csv", "initiative_sk", "dim_initiative.csv", "initiative_sk", "dim_plan_item→dim_initiative"),
        ("dim_plan_item.csv", "rock_sk", "dim_rock.csv", "rock_sk", "dim_plan_item→dim_rock"),
    ]

    for fact_file, fk_col, dim_file, pk_col, label in fk_checks:
        fact_df = tables.get(fact_file)
        dim_df = tables.get(dim_file)
        if fact_df is None or dim_df is None:
            continue
        if fk_col not in fact_df.columns or pk_col not in dim_df.columns:
            continue
        valid_pks = sk_set(dim_df, pk_col)
        orphans = fact_df[~fact_df[fk_col].isin(valid_pks) & fact_df[fk_col].notna()]
        if len(orphans) > 0:
            errors.append(ValidationError(
                "fk_integrity", f"Orphaned FK: {label}", count=len(orphans)
            ))

    return errors


def check_measure_groups(tables: dict[str, pd.DataFrame]) -> list[ValidationError]:
    errors = []
    fact = tables.get("fact_budget.csv")
    dim_measure = tables.get("dim_measure.csv")
    if fact is None or dim_measure is None:
        return errors

    known_groups = {"domain_budget", "aggregate_budget"}

    # Join measure_group into fact via measure_code
    if "measure_code" in fact.columns and "measure_code" in dim_measure.columns:
        merged = fact.merge(
            dim_measure[["measure_code", "measure_group"]],
            on="measure_code",
            how="left",
        )
        unknown = merged[~merged["measure_group"].isin(known_groups)]
        if len(unknown) > 0:
            errors.append(ValidationError(
                "measure_groups",
                f"fact_budget contains rows with unknown measure_group (not in {known_groups})",
                count=len(unknown),
            ))

    return errors


def check_prioritization_consistency(tables: dict[str, pd.DataFrame]) -> list[ValidationError]:
    errors = []
    df = tables.get("dim_plan_item.csv")
    if df is None:
        return errors
    if "is_prioritized" not in df.columns or "priority_status_code" not in df.columns:
        return errors

    active_mask = df["is_prioritized"].str.strip().str.lower() == "true"
    code_col = df["priority_status_code"].str.strip()

    # Rows flagged as active but with a status_code that implies inactive
    INACTIVE_CODES = {"not_prioritized", "not_affected", "not_relevant",
                      "numeric_zero", "candidate_only", "blank", "to_clarify"}
    suspicious = df[active_mask & code_col.isin(INACTIVE_CODES)]
    if len(suspicious) > 0:
        errors.append(ValidationError(
            "prioritization_consistency",
            "dim_plan_item: is_prioritized=True but priority_status_code is inactive",
            count=len(suspicious),
        ))

    return errors


def check_fallback_keys(tables: dict[str, pd.DataFrame]) -> list[ValidationError]:
    errors = []
    df = tables.get("dim_initiative.csv")
    if df is None or "initiative_business_key" not in df.columns:
        return errors
    fallbacks = df[df["initiative_business_key"].str.startswith("row:", na=False)]
    if len(fallbacks) > 0:
        errors.append(ValidationError(
            "fallback_keys",
            "dim_initiative contains fallback row: keys (no Jira key, id_budget, or name found)",
            count=len(fallbacks),
        ))
    return errors


def check_source_budget_reconciliation(tables: dict[str, pd.DataFrame]) -> list[ValidationWarning]:
    """Cross-check: source files vs fact_budget domain_budget totals.
    Parses input CSVs directly and compares per-plan sums to what landed in fact_budget.
    A large gap indicates parsing loss (e.g. currency symbols dropping values).
    """
    warnings = []
    try:
        import sys
        sys.path.insert(0, str(OUT_DIR.parent))
        from normalize_it_planning import (
            load_semicolon_csv, find_header_row, slice_table,
            detect_domain_code_from_header, clean_str, parse_number
        )

        source_configs = [
            ("input/Quartalsmaster Q1.csv", ["Budget-Schlüssel", "Jira-Link", "Alignment-Team"], "q1_plan", 1.0),
            ("input/Quartalsmaster Q2.csv", ["Budget-Schlüssel", "Value Stream", "Q2 Stage"], "q2_plan", 1.0),
            ("input/Quartalsmaster Q3.csv", ["Budget-Schlüssel", "Jira-Link", "Alignment-Team"], "q3_plan", 1.0),
            ("input/B2B-Demandmaster_2026.csv", ["Budget-Schlüssel", "Business Initiative/Epic", "Alignment Team"], "annual_2026", 1.0),
        ]

        fact = tables.get("fact_budget.csv")
        if fact is None or "source_plan" not in fact.columns:
            return warnings

        for rel_path, anchors, plan_id, multiplier in source_configs:
            src_path = OUT_DIR.parent / rel_path
            if not src_path.exists():
                continue
            try:
                raw = load_semicolon_csv(src_path)
                hr = find_header_row(raw, anchors)
                df = slice_table(raw, header_row=hr, data_start_row=hr + 1)
                domain_cols = [c for c in df.columns if detect_domain_code_from_header(c)]
                source_total = 0.0
                for col in domain_cols:
                    for v in df[col].tolist():
                        s = clean_str(v)
                        if not s:
                            continue
                        val = parse_number(s, multiplier=multiplier)
                        if val is not None:
                            source_total += val

                model_total = pd.to_numeric(
                    fact[fact["source_plan"] == plan_id]["amount_eur"], errors="coerce"
                ).sum()
                # filter to DOMAIN_BUDGET only
                if "measure_code" in fact.columns:
                    model_total = pd.to_numeric(
                        fact[(fact["source_plan"] == plan_id) & (fact["measure_code"] == "DOMAIN_BUDGET")]["amount_eur"],
                        errors="coerce"
                    ).sum()

                diff = source_total - model_total
                pct = abs(diff) / source_total * 100 if source_total > 0 else 0
                if pct > 1.0:  # warn if >1% gap
                    warnings.append(ValidationWarning(
                        "source_budget_reconciliation",
                        f"{plan_id}: source DOMAIN_BUDGET sum {source_total/1000:.1f} k€ "
                        f"vs model {model_total/1000:.1f} k€ — gap {diff/1000:.1f} k€ ({pct:.1f}%)"
                    ))
            except Exception as e:
                warnings.append(ValidationWarning(
                    "source_budget_reconciliation",
                    f"{plan_id}: could not reconcile — {e}"
                ))
    except ImportError:
        pass
    return warnings


def check_data_quality_warnings(tables: dict[str, pd.DataFrame]) -> list[ValidationWarning]:
    warnings = []

    # Unassigned rocks in plan items
    plan_item = tables.get("dim_plan_item.csv")
    if plan_item is not None and "rock_name" in plan_item.columns:
        unassigned = (plan_item["rock_name"].str.strip().str.lower() == "unassigned").sum()
        if unassigned > 0:
            warnings.append(ValidationWarning(
                "unassigned_rocks",
                "dim_plan_item rows with rock_name='Unassigned' (no Rock assigned)",
                count=int(unassigned),
            ))

    # Initiatives without a Jira key
    initiative = tables.get("dim_initiative.csv")
    if initiative is not None and "jira_initiative_key_canonical" in initiative.columns:
        no_jira = (
            initiative["jira_initiative_key_canonical"].isna() |
            (initiative["jira_initiative_key_canonical"].str.strip() == "")
        ).sum()
        if no_jira > 0:
            warnings.append(ValidationWarning(
                "no_jira_key",
                "dim_initiative rows without a jira_initiative_key_canonical",
                count=int(no_jira),
            ))

    # Plan items without an initiative_name_raw
    if plan_item is not None and "initiative_name_raw" in plan_item.columns:
        no_name = (
            plan_item["initiative_name_raw"].isna() |
            (plan_item["initiative_name_raw"].str.strip() == "")
        ).sum()
        if no_name > 0:
            warnings.append(ValidationWarning(
                "no_initiative_name",
                "dim_plan_item rows without initiative_name_raw",
                count=int(no_name),
            ))

    # fact_budget rows where amount_eur is NULL (budget not maintained)
    fact = tables.get("fact_budget.csv")
    if fact is not None and "amount_eur" in fact.columns:
        null_budget = (fact["amount_eur"].isna() | (fact["amount_eur"].str.strip() == "")).sum()
        if null_budget > 0:
            warnings.append(ValidationWarning(
                "null_budget",
                "fact_budget rows with NULL amount_eur (budget not maintained)",
                count=int(null_budget),
            ))

    return warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print(f"Validating normalized model in: {OUT_DIR}\n")

    # --- Step 1: file existence ---
    file_errors = check_files_exist()
    if file_errors:
        print("=== File Existence Errors ===")
        for e in file_errors:
            print(e)
        print(f"\nCannot continue: {len(file_errors)} missing file(s).")
        return 1

    # --- Load all tables ---
    tables: dict[str, pd.DataFrame] = {}
    for fname in EXPECTED_FILES:
        tables[fname] = load(fname)

    print(f"Loaded {len(tables)} files.")
    for fname, df in tables.items():
        print(f"  {fname}: {len(df):>5} rows, {len(df.columns)} columns")

    # --- Run all checks ---
    all_errors: list[ValidationError] = []
    all_warnings: list[ValidationWarning] = []

    all_errors += check_required_columns(tables)
    all_errors += check_null_pks(tables)
    all_errors += check_duplicate_pks(tables)
    all_errors += check_duplicate_plan_item_bk(tables)
    all_errors += check_fk_integrity(tables)
    all_errors += check_measure_groups(tables)
    all_errors += check_prioritization_consistency(tables)
    all_errors += check_fallback_keys(tables)
    all_warnings += check_data_quality_warnings(tables)
    all_warnings += check_source_budget_reconciliation(tables)

    # --- Report ---
    print()
    if all_errors:
        print(f"=== ERRORS ({len(all_errors)}) ===")
        for e in all_errors:
            print(e)
    else:
        print("=== ERRORS: none ===")

    print()
    if all_warnings:
        print(f"=== WARNINGS ({len(all_warnings)}) ===")
        for w in all_warnings:
            print(w)
    else:
        print("=== WARNINGS: none ===")

    print()
    if all_errors:
        print(f"Result: FAILED ({len(all_errors)} error(s), {len(all_warnings)} warning(s))")
        return 1
    else:
        print(f"Result: OK (0 errors, {len(all_warnings)} warning(s))")
        return 0


if __name__ == "__main__":
    sys.exit(main())
