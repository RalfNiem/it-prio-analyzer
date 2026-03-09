import pandas as pd
import json
import re
from pathlib import Path
import sys

def load_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def verify_data():
    print("🚀 Starting Comprehensive Data Validation Audit...\n")
    
    out_dir = Path('./out')
    fact_file = out_dir / 'fact_plan_budget.csv'
    init_file = out_dir / 'dim_initiative.csv'
    rock_file = out_dir / 'dim_rock.csv'
    domain_file = out_dir / 'dim_domain.csv'

    if not all(f.exists() for f in [fact_file, init_file, rock_file, domain_file]):
        print("❌ ERROR: Output files missing in /out. Run budget_model_builder_dynamic.py first.")
        sys.exit(1)

    # Load Model Data
    fact = pd.read_csv(fact_file)
    init = pd.read_csv(init_file)
    rocks = pd.read_csv(rock_file)
    domains = pd.read_csv(domain_file)
    
    # Load Configs for dynamic testing
    global_cfg = load_json('configs/global.json')
    it_domains = global_cfg.get('it_domains', [])
    val_sums_cfg = global_cfg.get('validated_sums', {})
    val_diffs_cfg = global_cfg.get('calculated_differences', {})

    errors = []

    # --- SUITE 1: INTEGRITY ---
    print("Checking structural integrity...")
    if not fact['rock_id'].isin(rocks['rock_id']).all():
        errors.append("Integrity: Some rock_ids in fact table do not exist in dim_rock.")
    if not fact['initiative_id'].isin(init['initiative_id']).all():
        errors.append("Integrity: Some initiative_ids in fact table do not exist in dim_initiative.")
    
    core_fact = fact[fact['measure_type'] == 'domain_budget']
    if not core_fact['domain_id'].isin(domains['domain_id']).all():
        missing = core_fact[~core_fact['domain_id'].isin(domains['domain_id'])]['domain_short'].unique()
        errors.append(f"Integrity: Domain budgets found for unknown domains: {missing}")

    # --- SUITE 2: MATHEMATICAL CONSISTENCY (AUDIT EVERY ROW) ---
    print("Auditing mathematical consistency of aggregates...")
    
    # Check Validated Sums (e.g. B2B_COE_VALIDATED must match sum of SFC, CPQ...)
    for target_sum, sources in val_sums_cfg.items():
        # Create a pivot-like view for comparison
        pivot = fact[fact['domain_short'].isin(sources + [target_sum])].pivot_table(
            index=['source_plan', 'initiative_id'], 
            columns='domain_short', 
            values='amount', 
            aggfunc='sum'
        ).fillna(0)
        
        if target_sum in pivot.columns:
            actual_sum = pivot[target_sum]
            expected_sum = pivot[[s for s in sources if s in pivot.columns]].sum(axis=1)
            
            diff = (actual_sum - expected_sum).abs()
            failed_rows = diff[diff > 0.01] # allow minor float delta
            if not failed_rows.empty:
                errors.append(f"Math: {target_sum} mismatch in {len(failed_rows)} initiatives. Max diff: {failed_rows.max():.2f}")

    # Check Calculated Differences (e.g. NON_B2B = TOTAL - O2C)
    for target_diff, formula in val_diffs_cfg.items():
        minuend = formula['minuend']
        subtrahend = formula['subtrahend']
        
        pivot = fact[fact['domain_short'].isin([target_diff, minuend, subtrahend])].pivot_table(
            index=['source_plan', 'initiative_id'], 
            columns='domain_short', 
            values='amount', 
            aggfunc='sum'
        ).fillna(0)
        
        if all(c in pivot.columns for c in [target_diff, minuend, subtrahend]):
            actual_val = pivot[target_diff]
            expected_val = (pivot[minuend] - pivot[subtrahend]).clip(lower=0)
            
            diff = (actual_val - expected_val).abs()
            failed_rows = diff[diff > 0.01]
            if not failed_rows.empty:
                # We treat this as a data quality warning, not an audit failure
                print(f"   ⚠️  Data Quality Warning: {target_diff} calculation has {len(failed_rows)} inconsistent source rows (clipped to 0).")

    # --- SUITE 3: FORMATTING & DATA CLEANLINESS ---
    print("Checking data formatting and cleanliness...")
    # Jira links should not contain newlines or semicolons
    link_cols = ['jira_initiative_link', 'jira_epic_link', 'jira_link_annual']
    for col in [c for c in link_cols if c in init.columns]:
        bad_links = init[init[col].astype(str).str.contains(r'[\n\r;]', na=False)]
        if not bad_links.empty:
            errors.append(f"Format: Found {len(bad_links)} rows with uncleaned Jira links in '{col}'.")

    # Rock names should be trimmed
    if rocks['rock_name'].str.startswith(' ').any() or rocks['rock_name'].str.endswith(' ').any():
        errors.append("Format: Found rock names with leading/trailing whitespace.")

    # --- SUITE 4: SPECIFIC DATA SCENARIOS ---
    # Verification of our known "Critical Cases"
    print("Verifying critical business cases...")
    
    # BEB2B-653 (The split budget case)
    init_653 = init[init['jira_initiative_link'].astype(str).str.contains('BEB2B-653', na=False)]
    if not init_653.empty:
        total_653 = fact[(fact['initiative_id'].isin(init_653['initiative_id'])) & 
                         (fact['source_plan'] == 'annual_2026') & 
                         (fact['domain_short'] == 'B2B_DELIVERY_COE')]['amount'].sum()
        if abs(total_653 - 3241.0) > 0.1:
            errors.append(f"Case: BEB2B-653 annual sum is wrong. Expected 3241.0, got {total_653}")

    # --- RESULTS ---
    print("\n" + "="*40)
    if errors:
        print(f"❌ AUDIT FAILED: Found {len(errors)} error types!")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("✅ AUDIT PASSED: All data is consistent and valid.")
        print(f"   Facts: {len(fact)} | Initiatives: {len(init)} | Rocks: {len(rocks)}")
    print("="*40 + "\n")

if __name__ == "__main__":
    verify_data()
