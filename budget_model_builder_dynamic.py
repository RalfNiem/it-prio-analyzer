import pandas as pd
import re
import sys
import json
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict

def load_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

# --- Lade Globale Konfiguration ---
try:
    GLOBAL_CFG = load_json('configs/global.json')
except FileNotFoundError:
    print("CRITICAL ERROR: configs/global.json not found.")
    sys.exit(1)

OUT_DIR = Path(GLOBAL_CFG.get('out_dir', 'out'))
IT_DOMAINS = GLOBAL_CFG.get('it_domains', [])
VALIDATED_SUMS = GLOBAL_CFG.get('validated_sums', {})
AGGREGATE_DOMAINS = GLOBAL_CFG.get('aggregate_domains', [])
JIRA_DB_PATH = GLOBAL_CFG.get('jira_db_path')

def normalize_name(name: str) -> str:
    if pd.isna(name): return ""
    s = str(name).lower()
    s = re.sub(r'[\t\r\n]+', ' ', s)
    s = re.sub(r'[^a-z0-9 ]', '', s)
    s = re.sub(r' +', '_', s).strip('_')
    return s

def parse_smart_amount(value: object) -> float:
    if pd.isna(value) or value == '': return 0.0
    s = str(value).strip().replace('\xa0', '').replace(' ', '')
    if s == '' or any(x in s.lower() for x in ['affected', 'clarify', 'priorit', 'n.a.']):
        return 0.0
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    else:
        if '.' in s:
            parts = s.split('.')
            if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
                s = s.replace('.', '')
    try: return float(s)
    except: return 0.0

def clean_jira_links(val: object) -> str | None:
    if pd.isna(val) or not str(val).strip():
        return val
    s = str(val).strip()
    s = re.sub(r'[;,\n\r\t]+', ' ', s)
    parts = [p.strip() for p in s.split() if p.strip()]
    return ', '.join(parts) if parts else None

def find_header_row(path: Path, anchors: List[str]) -> int:
    df_preview = pd.read_csv(path, sep=';', nrows=30, header=None, dtype=str)
    for idx, row in df_preview.iterrows():
        row_str = normalize_name(" ".join(row.fillna("").tolist()))
        if all(normalize_name(a) in row_str for a in anchors[:2]):
            return idx
    return 0

def fetch_jira_titles(keys: List[str]) -> Dict[str, str]:
    """Holt die offiziellen Titel (summaries) aus der SQLite-Jira-Datenbank."""
    if not JIRA_DB_PATH or not Path(JIRA_DB_PATH).exists():
        print(f"Warning: Jira database not found at {JIRA_DB_PATH}. Skipping title enrichment.")
        return {}
    
    titles = {}
    print(f"Enriching titles from Jira database: {JIRA_DB_PATH}")
    try:
        conn = sqlite3.connect(JIRA_DB_PATH)
        cursor = conn.cursor()
        # Jira-Keys bereinigen für die Abfrage
        clean_keys = list(set([k.split(',')[0].strip() for k in keys if k and pd.notna(k)]))
        
        # Abfrage in Batches (SQLite limit)
        for i in range(0, len(clean_keys), 500):
            batch = clean_keys[i:i+500]
            placeholders = ','.join(['?'] * len(batch))
            cursor.execute(f"SELECT key, data FROM issues WHERE key IN ({placeholders})", batch)
            for row in cursor.fetchall():
                key, data_json = row
                try:
                    title = json.loads(data_json).get('title')
                    if title: titles[key] = title
                except: continue
        conn.close()
    except Exception as e:
        print(f"Error connecting to Jira DB: {e}")
    return titles

def load_and_clean(cfg: dict) -> pd.DataFrame:
    path = cfg['file_path']
    plan_id = cfg['plan_id']
    print(f"Processing plan: {plan_id} from {path}")
    
    if not Path(path).exists():
        print(f"Warning: File {path} not found. Skipping {plan_id}.")
        return pd.DataFrame()

    header_idx = find_header_row(Path(path), cfg.get('anchors', []))
    raw_df = pd.read_csv(path, sep=';', header=header_idx, dtype=str, encoding='utf-8-sig')
    raw_df.columns = [normalize_name(c) for c in raw_df.columns]
    
    target_data = {}
    norm_domains = {normalize_name(d): d for d in IT_DOMAINS}
    ignore_list = cfg.get('ignore_columns', [])

    for raw_col in raw_df.columns:
        if raw_col in ignore_list:
            continue

        target = None
        for norm_dom, real_dom in norm_domains.items():
            if raw_col == norm_dom or raw_col.startswith(norm_dom + "_"):
                target = real_dom
                break
        
        if not target and raw_col in cfg['mapping']:
            target = cfg['mapping'][raw_col]
            
        if not target:
            for cfg_key, cfg_target in cfg['mapping'].items():
                threshold = cfg.get('fuzzy_meta_threshold', 8)
                if cfg_key in raw_col and len(cfg_key) >= threshold:
                    target = cfg_target
                    break
        
        if target:
            series = raw_df[raw_col]
            if target in IT_DOMAINS or 'COE' in target or 'TOTAL' in target:
                vals = series.map(parse_smart_amount) * cfg.get('unit_factor', 1.0)
                if target in target_data:
                    target_data[target] = target_data[target] + vals
                else:
                    target_data[target] = vals
            else:
                vals = series.map(lambda x: str(x).strip() if pd.notna(x) else x)
                if target not in target_data:
                    target_data[target] = vals
                else:
                    if target == 'prio_q2': target_data[target] = vals

    df = pd.DataFrame(target_data)
    
    # Aggregate B2B_DELIVERY_COE
    if 'B2B_DELIVERY_COE' in df.columns:
        q_cols = [c for c in df.columns if '_PART' in c]
        if q_cols:
            df['B2B_DELIVERY_COE'] = df.apply(lambda r: r[q_cols].sum() if r['B2B_DELIVERY_COE'] == 0 else r['B2B_DELIVERY_COE'], axis=1)
            df = df.drop(columns=q_cols)

    # Add Validated Sums
    for new_col_name, source_cols in VALIDATED_SUMS.items():
        available_cols = [c for c in source_cols if c in df.columns]
        if available_cols:
            df[new_col_name] = df[available_cols].sum(axis=1)

    # Add Calculated Differences (Only if sources exist in this specific plan)
    calculated_diffs = GLOBAL_CFG.get('calculated_differences', {})
    for new_col_name, formula in calculated_diffs.items():
        minuend = formula.get('minuend')
        subtrahend = formula.get('subtrahend')
        if minuend in df.columns and subtrahend in df.columns:
            # Only calculate if the minuend column actually has data (not just zeros)
            if (df[minuend] != 0).any():
                # Detect inconsistencies for warning
                inconsistent = df[df[minuend] < df[subtrahend]]
                if not inconsistent.empty:
                    print(f"⚠️  WARNING: Data inconsistency in {plan_id} for '{new_col_name}'.")
                    print(f"   The following initiatives have a smaller '{minuend}' than '{subtrahend}':")
                    for _, row in inconsistent.head(3).iterrows():
                        key = row.get('jira_initiative_link') or row.get('jira_epic_link') or "Unknown"
                        print(f"   - {key}: {row[minuend]} < {row[subtrahend]}")
                    if len(inconsistent) > 3: print(f"   ... and {len(inconsistent)-3} more.")
                
                df[new_col_name] = (df[minuend] - df[subtrahend]).clip(lower=0)

    if 'rock_name' in df.columns:
        df['rock_name'] = df['rock_name'].map(lambda x: str(x).strip() if pd.notna(x) else x)

    for link_col in ['jira_link_annual', 'jira_epic_link', 'jira_initiative_link']:
        if link_col in df.columns:
            df[link_col] = df[link_col].apply(clean_jira_links)

    id_cols = [c for c in ['jira_initiative_link', 'jira_epic_link', 'rock_name'] if c in df.columns]
    df = df.dropna(subset=id_cols, how='all')
    
    df['source_plan'] = plan_id
    df['period'] = cfg['period']
    return df

def build_model():
    OUT_DIR.mkdir(exist_ok=True)
    plan_files = list(Path('configs/plans').glob('*.json'))
    if not plan_files:
        print("No plan configurations found in configs/plans/")
        return

    all_dfs = []
    for plan_file in plan_files:
        cfg = load_json(str(plan_file))
        df = load_and_clean(cfg)
        if not df.empty: all_dfs.append(df)
            
    if not all_dfs:
        print("No data extracted.")
        return

    # --- DIM_DOMAIN ---
    dim_domain = pd.DataFrame([{'domain_id': i+1, 'domain_name': d, 'domain_short': d} for i, d in enumerate(IT_DOMAINS)])
    if AGGREGATE_DOMAINS:
        dim_domain = pd.concat([dim_domain, pd.DataFrame(AGGREGATE_DOMAINS)], ignore_index=True)

    # --- DIM_ROCK ---
    all_rocks = pd.concat([df[['rock_name']] for df in all_dfs if 'rock_name' in df.columns])
    rocks_names = all_rocks.dropna().drop_duplicates().sort_values('rock_name')
    dim_rock = rocks_names.reset_index(drop=True)
    dim_rock.index += 1
    dim_rock.index.name = 'rock_id'
    dim_rock = dim_rock.reset_index()
    dim_rock = pd.concat([pd.DataFrame([{'rock_id': 0, 'rock_name': 'Unassigned'}]), dim_rock], ignore_index=True)

    # --- DIM_INITIATIVE & ID MAPPING ---
    def get_id_key(r):
        if pd.notna(r.get('jira_epic_link')) and str(r['jira_epic_link']).strip(): return str(r['jira_epic_link']).strip().split(',')[0]
        if pd.notna(r.get('jira_initiative_link')) and str(r['jira_initiative_link']).strip(): return str(r['jira_initiative_link']).strip().split(',')[0]
        return f"rock_{r.get('rock_name', 'none')}_{hash(str(r))}"

    init_dfs = []
    all_seen_links = set()
    for df in all_dfs:
        temp = df.copy()
        temp['id_key'] = temp.apply(get_id_key, axis=1)
        init_dfs.append(temp)
        all_seen_links.update(temp['id_key'].tolist())
        
    master_df = pd.concat(init_dfs, ignore_index=True)
    
    # 1. ENRICH WITH JIRA TITLES
    jira_titles = fetch_jira_titles(list(all_seen_links))
    
    def get_best_name(r):
        key = r['id_key']
        # 1. Try Jira DB
        if key in jira_titles: return jira_titles[key]
        # 2. Try Annual Description
        if pd.notna(r.get('description_annual')): return r['description_annual']
        # 3. Try Q2 Title
        if pd.notna(r.get('jira_initiative_title')): return r['jira_initiative_title']
        return key

    master_df['initiative_name'] = master_df.apply(get_best_name, axis=1)

    all_keys = master_df[['id_key']].drop_duplicates().reset_index(drop=True)
    all_keys['initiative_id'] = all_keys.index + 1
    master_df = master_df.merge(all_keys, on='id_key', how='left')
    
    dim_init_cols = [c for c in master_df.columns if c not in IT_DOMAINS and c not in dim_domain['domain_short'].values and c != 'id_key']
    dim_initiative = master_df[dim_init_cols].copy()

    # --- FACT_PLAN_BUDGET ---
    def melt_it(df):
        budget_cols = [c for c in df.columns if c in dim_domain['domain_short'].values]
        id_vars = [c for c in df.columns if c in ['initiative_id', 'rock_name', 'alignment_team', 'source_plan', 'period']]
        m = df.melt(id_vars=id_vars, value_vars=budget_cols, var_name='domain_short', value_name='amount')
        m['amount'] = pd.to_numeric(m['amount'], errors='coerce').fillna(0)
        m = m[m['amount'] > 0].copy()
        m['measure_type'] = m['domain_short'].map(lambda x: 'domain_budget' if x in IT_DOMAINS else 'aggregate')
        return m

    facts = [melt_it(df) for df in [master_df[master_df['source_plan'] == p_id] for p_id in master_df['source_plan'].unique()]]
    fact = pd.concat(facts, ignore_index=True)
    fact = fact.merge(dim_rock, on='rock_name', how='left')
    fact['rock_id'] = fact['rock_id'].fillna(0).astype(int)
    fact = fact.merge(dim_domain[['domain_id', 'domain_short']], on='domain_short', how='left')

    # --- EXPORT ---
    dim_rock.to_csv(OUT_DIR / 'dim_rock.csv', index=False)
    dim_domain.to_csv(OUT_DIR / 'dim_domain.csv', index=False)
    dim_initiative.to_csv(OUT_DIR / 'dim_initiative.csv', index=False)
    cols = ['source_plan', 'period', 'rock_id', 'initiative_id', 'domain_id', 'alignment_team', 'domain_short', 'measure_type', 'amount']
    fact[cols].to_csv(OUT_DIR / 'fact_plan_budget.csv', index=False)
    
    print(f"\nEngine execution complete. Extracted {len(fact)} valid budget facts.")

if __name__ == '__main__':
    build_model()
