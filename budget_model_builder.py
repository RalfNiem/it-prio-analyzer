from __future__ import annotations

"""
IT Priority and Budget Model Builder (ETL)

This script processes IT demand and budget planning data from two source CSV files:
1. Annual Demandmaster 2026 (B2B-Demandmaster_2026.csv)
2. Quarterly Prioritization Master Q2 (Quartalsmaster_Q2.csv)

It performs data cleaning, normalization, and transformation to build a 
dimensional star schema (fact and dimension tables) suitable for 
analytical tools like Excel, Power BI, or interactive Python analysis.

Key Features:
- Normalizes unit formats (converting € to k€ for quarterly data).
- Handles complex Excel-to-CSV exports (merged headers, multiple languages).
- Fuzzy-matches domain and team columns.
- Aggregates duplicate budget entries automatically.
- Extracts semantic information (Jira keys, descriptions, clusters).

Output Files (in /out directory):
- dim_rock.csv: Strategic 'Rocks' dimension.
- dim_domain.csv: IT Domains/Teams dimension.
- dim_initiative.csv: Detailed business initiatives including Jira keys and descriptions.
- fact_plan_budget.csv: Fact table containing all budget allocations.
"""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable
import sys

import pandas as pd


# -----------------------------
# Paths
# -----------------------------
BASE_DIR = Path('.')
Q2_FILE = BASE_DIR / 'Quartalsmaster_Q2.csv'
ANNUAL_FILE = BASE_DIR / 'B2B-Demandmaster_2026.csv'
OUT_DIR = BASE_DIR / 'out'


# -----------------------------
# Config
# -----------------------------
Q2_KEEP_COLUMNS = {
    'Rocks': 'rock_name',
    'Objective\n(Strategisches Ziel)': 'objective',
    'Jira-Link\nInitiative \n(Prio-Roadmap)': 'jira_initiative_link',
    'Jira-Link\nBusiness-Epic\nfür Q2': 'jira_business_epic_q2_links',
    'Prio\nQ2': 'prio_q2',
    'Alignment-Team': 'alignment_team',
    # New semantic columns for Q2
    'JIRA Business Initiative (Beschreibung)': 'description_q2',
    'Business Epic Q2\nTitle': 'epic_title_q2',
    # Domains
    'SFC\nDOM0205 / DOM029\n(Andrej Deckl)': 'SFC',
    'CPQ\nDOM0206  / DOM030\n(Hemanth Meruga)': 'CPQ',
    'SNO\nDOM0207  / DOM031\n(Karthik Mohan)': 'SNO',
    'DTP\nDOM0208  / DOM032\n(Knut Goebel)': 'DTP',
    'API\nDOM0208  / DOM032\n(Frank Koch)': 'API',
    'BAI  \nDOM0209  / DOM033\t\n(Alexander Lukashev)': 'BAI',
    'DCI \nDOM0210  / DOM034\n(Klein, Andreas)': 'DCI',
    'BIS\nDOM0210  / DOM034\n(Sielski, Krzysztof)': 'BIS',
    'DOM0210  / DOM034\n(Heiden, Andreas)': 'BAS',
    'BOO\nDOM0210  / DOM034\n(Heiden, Andreas)': 'BOO',
    'BDA\nDOM0210  / DOM034\n(Heiden, Andreas)': 'BDA',
    'BCT \n(B2B Classic TC)\n(Roberto Wahl, Luca Jonas Christmann)': 'BCT',
    'CLO \nCustomer Logistics\n(Achim Spitz, Lisa Wiechers)': 'CLO',
    'ORCA \n(Order2Cash)\n(Matthias Graf)': 'ORCA',
    'TASS\n(Telekom Accenture)\n(Patrick Kolling)': 'TASS',
    'Summe \n(nur B2B-COEs)': 'B2B_COE_SUM',
}

ANNUAL_KEEP_COLUMNS = {
    'Rock': 'rock_name',
    'Business Initiative Cluster': 'business_initiative_cluster',
    # New semantic column for Annual
    'Business Initiative/Epic': 'description_annual',
    'Jira-LINK': 'jira_link_annual',
    'Alignment Team': 'alignment_team',
    'B2B Delivery gesamt': 'B2B_DELIVERY_TOTAL',
    'B2B Delivery COE': 'B2B_DELIVERY_COE',
    'SFC': 'SFC',
    'CPQ': 'CPQ',
    'SNO': 'SNO',
    'DTP': 'DTP',
    'API': 'API',
    'BAI': 'BAI',
    'DCI': 'DCI',
    'BIS': 'BIS',
    'BAS': 'BAS',
    'BOO': 'BOO',
    'BDA': 'BDA',
    'B2B Essentials': 'B2B_ESSENTIALS',
    'BCT': 'BCT',
    'CLO': 'CLO',
    'ORCA': 'ORCA',
    'TASS': 'TASS',
    'Non B2B Delivery': 'NON_B2B_DELIVERY',
}

DOMAIN_META = [
    ('SFC', 'DOM0205/DOM029', 'Salesforce', 'B2B_COE'),
    ('CPQ', 'DOM0206/DOM030', 'CPQ', 'B2B_COE'),
    ('SNO', 'DOM0207/DOM031', 'Service Now', 'B2B_COE'),
    ('DTP', 'DOM0208/DOM032', 'Touchpoints', 'B2B_COE'),
    ('API', 'DOM0208/DOM032', 'API', 'B2B_COE'),
    ('BAI', 'DOM0209/DOM033', 'AI', 'B2B_COE'),
    ('DCI', 'DOM0210/DOM034', 'Wholesale / DCI', 'B2B_COE'),
    ('BIS', 'DOM0210/DOM034', 'B2B Essentials BIS', 'B2B_COE'),
    ('BAS', 'DOM0210/DOM034', 'B2B Essentials BAS', 'B2B_COE'),
    ('BOO', 'DOM0210/DOM034', 'B2B Essentials BOO', 'B2B_COE'),
    ('BDA', 'DOM0210/DOM034', 'B2B Essentials BDA', 'B2B_COE'),
    ('B2B_ESSENTIALS', 'DOM0210/DOM034', 'B2B Essentials Group', 'B2B_COE'),
    ('BCT', 'DOM020', 'B2B Classic TC', 'B2B_COE'),
    ('CLO', 'DOM020', 'Customer Logistics', 'B2B_COE'),
    ('ORCA', 'DOM020', 'Order2Cash', 'B2B_COE'),
    ('TASS', 'DOM020', 'Telekom Accenture', 'B2B_COE'),
    ('B2B_COE_SUM', None, 'Summe nur B2B-COEs', 'AGGREGATE'),
    ('B2B_DELIVERY_TOTAL', None, 'B2B Delivery gesamt', 'AGGREGATE'),
    ('B2B_DELIVERY_COE', None, 'B2B Delivery COE', 'AGGREGATE'),
    ('NON_B2B_DELIVERY', None, 'Non B2B Delivery', 'AGGREGATE'),
]

DOMAIN_COLUMNS = [
    'SFC', 'CPQ', 'SNO', 'DTP', 'API', 'BAI', 'DCI', 'BIS', 'BAS', 'BOO', 'BDA',
    'B2B_ESSENTIALS', 'BCT', 'CLO', 'ORCA', 'TASS',
]

AGGREGATE_COLUMNS = [
    'B2B_COE_SUM', 'B2B_DELIVERY_TOTAL', 'B2B_DELIVERY_COE', 'NON_B2B_DELIVERY',
]


# -----------------------------
# Helpers
# -----------------------------
def normalize_text(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).replace('\xa0', ' ').replace('\t', ' ')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r' +', ' ', text).strip()
    return text or None


def parse_amount(value: object) -> float | None:
    if pd.isna(value):
        return None

    text = str(value).strip().replace('\xa0', '').replace('\t', '')
    if text == '':
        return None

    lower = text.lower()
    if lower in {'not affected', 'to clarify', 'prioritized q2', 'not prioritized', 'n.a.', '-'}:
        return None
    if 'kostenschätzung' in lower:
        return None

    try:
        return float(text)
    except ValueError:
        pass

    if re.fullmatch(r'[0-9.]+', text):
        return float(text.replace('.', ''))
    
    if re.fullmatch(r'[0-9.,]+', text):
        if text.rfind('.') > text.rfind(','):
            return float(text.replace(',', ''))
        else:
            text = text.replace('.', '').replace(',', '.')
            return float(text)

    return None


def read_q2_raw(path: Path) -> pd.DataFrame:
    print(f"Reading Q2 data from {path} (Header row 6)...")
    return pd.read_csv(path, sep=';', header=5, dtype=str, encoding='utf-8-sig')


def read_annual_raw(path: Path) -> pd.DataFrame:
    print(f"Reading Annual data from {path} (Header row 8)...")
    return pd.read_csv(path, sep=';', header=7, dtype=str, encoding='utf-8-sig')


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalize_text(str(c)) for c in df.columns]
    return df


def select_and_rename(df: pd.DataFrame, mapping: dict[str, str], source_name: str) -> pd.DataFrame:
    norm_mapping = {normalize_text(k): v for k, v in mapping.items()}
    
    new_cols = {}
    found_any = False
    for col in df.columns:
        for k_norm, v in norm_mapping.items():
            if k_norm in col: # Fuzzy match
                new_cols[col] = v
                found_any = True
                break
    
    out = df.rename(columns=new_cols)
    keep = [c for c in out.columns if c in norm_mapping.values()]
    return out[keep]


def clean_common_fields(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # First, parse amounts
    for col in [c for c in df.columns if c in DOMAIN_COLUMNS + AGGREGATE_COLUMNS]:
        df[col] = df[col].map(parse_amount)
    
    # If we have duplicate column names (e.g. from fuzzy matching), sum them up
    if df.columns.duplicated().any():
        df = df.groupby(lambda x: x, axis=1).sum()
        
    # Then clean text fields
    for col in [c for c in df.columns if c not in DOMAIN_COLUMNS + AGGREGATE_COLUMNS]:
        df[col] = df[col].map(normalize_text)
        
    return df


def drop_empty_business_rows(df: pd.DataFrame, key_columns: Iterable[str]) -> pd.DataFrame:
    mask = pd.Series(False, index=df.index)
    for col in key_columns:
        if col in df.columns:
            mask = mask | df[col].notna()
    return df.loc[mask].copy()


def make_dim_rock(q2_df: pd.DataFrame, annual_df: pd.DataFrame) -> pd.DataFrame:
    rocks_q2 = q2_df[['rock_name']].dropna() if 'rock_name' in q2_df.columns else pd.DataFrame(columns=['rock_name'])
    rocks_ann = annual_df[['rock_name']].dropna() if 'rock_name' in annual_df.columns else pd.DataFrame(columns=['rock_name'])
    
    rocks = pd.concat([rocks_q2, rocks_ann], ignore_index=True).drop_duplicates().sort_values('rock_name')
    rocks['rock_id'] = range(1, len(rocks) + 1)
    return rocks[['rock_id', 'rock_name']]


def make_dim_domain() -> pd.DataFrame:
    rows = []
    for idx, (short, code, display, group) in enumerate(DOMAIN_META, start=1):
        rows.append({
            'domain_id': idx,
            'domain_short': short,
            'domain_code': code,
            'domain_display_name': display,
            'domain_group': group,
            'is_core_comparable': short in DOMAIN_COLUMNS,
        })
    return pd.DataFrame(rows)


def make_dim_initiative(q2_df: pd.DataFrame, annual_df: pd.DataFrame, dim_rock: pd.DataFrame) -> pd.DataFrame:
    # Q2 part with new description columns
    q2_needed = ['rock_name', 'objective', 'jira_initiative_link', 'jira_business_epic_q2_links', 'prio_q2', 'description_q2', 'epic_title_q2']
    q2_cols = [c for c in q2_needed if c in q2_df.columns]
    q2_part = q2_df[q2_cols].copy()
    
    # Ensure all columns exist for concatenation
    all_init_cols = ['rock_name', 'objective', 'jira_initiative_link', 'jira_business_epic_q2_links', 'prio_q2', 
                    'description_q2', 'epic_title_q2', 'business_initiative_cluster', 'description_annual', 'jira_link_annual']
    
    for c in all_init_cols:
        if c not in q2_part.columns: q2_part[c] = None

    # Annual part with new description column
    ann_needed = ['rock_name', 'business_initiative_cluster', 'description_annual', 'jira_link_annual']
    ann_cols = [c for c in ann_needed if c in annual_df.columns]
    annual_part = annual_df[ann_cols].copy()
    
    for c in all_init_cols:
        if c not in annual_part.columns: annual_part[c] = None

    initiatives = pd.concat([q2_part, annual_part], ignore_index=True)
    initiatives = initiatives.merge(dim_rock, on='rock_name', how='left')
    initiatives = initiatives.drop_duplicates().reset_index(drop=True)
    initiatives.insert(0, 'initiative_id', range(1, len(initiatives) + 1))
    
    final_cols = ['initiative_id', 'rock_id'] + all_init_cols
    return initiatives[final_cols]


def attach_initiative_id(df: pd.DataFrame, dim_initiative: pd.DataFrame, source_plan: str) -> pd.DataFrame:
    if source_plan == 'q2_plan':
        keys = ['rock_name', 'objective', 'jira_initiative_link', 'jira_business_epic_q2_links', 'prio_q2', 'description_q2', 'epic_title_q2']
    else:
        keys = ['rock_name', 'business_initiative_cluster', 'description_annual', 'jira_link_annual']

    valid_keys = [k for k in keys if k in df.columns and k in dim_initiative.columns]
    if not valid_keys:
        print(f"WARNING: No valid keys found for {source_plan} ID attachment.")
        df['initiative_id'] = None
        return df
        
    cols = ['initiative_id'] + valid_keys
    dim_subset = dim_initiative[cols].drop_duplicates(subset=valid_keys)
    return df.merge(dim_subset, on=valid_keys, how='left')


def melt_fact(
    df: pd.DataFrame,
    dim_rock: pd.DataFrame,
    dim_domain: pd.DataFrame,
    source_plan: str,
    period: str,
) -> pd.DataFrame:
    id_vars = [c for c in df.columns if c not in DOMAIN_COLUMNS + AGGREGATE_COLUMNS]
    value_vars = [c for c in DOMAIN_COLUMNS + AGGREGATE_COLUMNS if c in df.columns]
    
    if not value_vars:
        return pd.DataFrame()

    long_df = df.melt(
        id_vars=id_vars,
        value_vars=value_vars,
        var_name='domain_short',
        value_name='amount',
    )
    long_df = long_df[long_df['amount'].notna() & (long_df['amount'] != 0)].copy()
    
    # Harmonize units: Q2 is in €, Annual is in k€ -> convert Q2 to k€
    if source_plan == 'q2_plan':
        long_df['amount'] = long_df['amount'] / 1000.0

    long_df['source_plan'] = source_plan
    long_df['period'] = period
    long_df['measure_type'] = long_df['domain_short'].map(
        lambda x: 'domain_budget' if x in DOMAIN_COLUMNS else x.lower()
    )
    
    if 'rock_name' in long_df.columns:
        long_df = long_df.merge(dim_rock, on='rock_name', how='left')
    
    long_df = long_df.merge(dim_domain[['domain_id', 'domain_short']], on='domain_short', how='left')

    keep = [
        'source_plan', 'period', 'rock_id', 'initiative_id', 'domain_id',
        'alignment_team', 'domain_short', 'measure_type', 'amount'
    ]
    keep = [c for c in keep if c in long_df.columns]
    return long_df[keep].sort_values(['source_plan', 'rock_id', 'domain_id']).reset_index(drop=True)


def build_model(q2_path: Path, annual_path: Path, out_dir: Path) -> None:
    if not q2_path.exists() or not annual_path.exists():
        print("ERROR: Input files missing.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    q2_raw = standardize_columns(read_q2_raw(q2_path))
    annual_raw = standardize_columns(read_annual_raw(annual_path))

    q2 = select_and_rename(q2_raw, Q2_KEEP_COLUMNS, 'q2')
    annual = select_and_rename(annual_raw, ANNUAL_KEEP_COLUMNS, 'annual')

    q2 = clean_common_fields(q2)
    annual = clean_common_fields(annual)

    q2 = drop_empty_business_rows(q2, ['rock_name', 'objective'])
    annual = drop_empty_business_rows(annual, ['rock_name', 'business_initiative_cluster'])

    dim_rock = make_dim_rock(q2, annual)
    dim_domain = make_dim_domain()
    dim_initiative = make_dim_initiative(q2, annual, dim_rock)

    q2 = attach_initiative_id(q2, dim_initiative, 'q2_plan')
    annual = attach_initiative_id(annual, dim_initiative, 'annual_2026')

    fact_q2 = melt_fact(q2, dim_rock, dim_domain, 'q2_plan', '2026-Q2')
    fact_annual = melt_fact(annual, dim_rock, dim_domain, 'annual_2026', '2026')
    fact = pd.concat([fact_q2, fact_annual], ignore_index=True)

    dim_rock.to_csv(out_dir / 'dim_rock.csv', index=False)
    dim_domain.to_csv(out_dir / 'dim_domain.csv', index=False)
    dim_initiative.to_csv(out_dir / 'dim_initiative.csv', index=False)
    fact.to_csv(out_dir / 'fact_plan_budget.csv', index=False)

    print(f'\nFinished processing. Output in {out_dir}')
    print(f'Row counts: Rocks: {len(dim_rock)}, Initiatives: {len(dim_initiative)}, Budget records: {len(fact)}')


if __name__ == '__main__':
    build_model(Q2_FILE, ANNUAL_FILE, OUT_DIR)
