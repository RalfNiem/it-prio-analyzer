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

# --- Globale Konfiguration ---
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

# Ranking für die Datenqualität (niedrigere Zahl = höhere Priorität)
PLAN_PRIORITY = {
    'q1_plan': 1,
    'q2_plan': 1,
    'annual_2026': 2
}

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
    # Ersetzt Trenner durch Leerzeichen für konsistente Listen
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
    if not JIRA_DB_PATH or not Path(JIRA_DB_PATH).exists():
        return {}

    titles = {}
    try:
        conn = sqlite3.connect(JIRA_DB_PATH)
        cursor = conn.cursor()
        clean_keys = list(set([k.strip() for k in keys if k and pd.notna(k)]))

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
    if not Path(path).exists(): return pd.DataFrame()

    header_idx = find_header_row(Path(path), cfg.get('anchors', []))
    raw_df = pd.read_csv(path, sep=';', header=header_idx, dtype=str, encoding='utf-8-sig')
    raw_df.columns = [normalize_name(c) for c in raw_df.columns]

    target_data = {}
    norm_domains = {normalize_name(d): d for d in IT_DOMAINS}
    ignore_list = cfg.get('ignore_columns', [])

    for raw_col in raw_df.columns:
        if raw_col in ignore_list: continue

        target = None
        for norm_dom, real_dom in norm_domains.items():
            if raw_col == norm_dom or raw_col.startswith(norm_dom + "_"):
                target = real_dom
                break

        if not target and raw_col in cfg['mapping']:
            target = cfg['mapping'][raw_col]

        if target:
            series = raw_df[raw_col]
            if target in IT_DOMAINS or 'COE' in target or 'TOTAL' in target:
                if cfg.get('is_status_plan'):
                    vals = series.map(lambda x: str(x).strip() if pd.notna(x) else "")
                    target_data[target] = target_data[target] + " | " + vals if target in target_data else vals
                else:
                    vals = series.map(parse_smart_amount) * cfg.get('unit_factor', 1.0)
                    target_data[target] = target_data[target] + vals if target in target_data else vals
            else:
                vals = series.map(lambda x: str(x).strip() if pd.notna(x) else x)
                target_data[target] = vals

    df = pd.DataFrame(target_data)

    # Links säubern
    for link_col in ['jira_epic_link', 'jira_initiative_link']:
        if link_col in df.columns:
            df[link_col] = df[link_col].apply(clean_jira_links)

    # Multi-Epic Explode: Jedes Epic erhält eine eigene Zeile
    if 'jira_epic_link' in df.columns:
        df['jira_epic_link'] = df['jira_epic_link'].str.split(', ')
        df = df.explode('jira_epic_link').reset_index(drop=True)

    df['source_plan'] = plan_id
    df['period'] = cfg['period']
    return df

def build_model():
    OUT_DIR.mkdir(exist_ok=True)
    plan_files = list(Path('configs/plans').glob('*.json'))
    all_dfs = [load_and_clean(load_json(str(f))) for f in plan_files]
    all_dfs = [df for df in all_dfs if not df.empty]

    if not all_dfs: return

    master_df = pd.concat(all_dfs, ignore_index=True)

    # ID-Key generieren
    def get_id_key(r):
        if pd.notna(r.get('jira_epic_link')): return str(r['jira_epic_link'])
        if pd.notna(r.get('jira_initiative_link')): return str(r['jira_initiative_link']).split(',')[0]
        return f"rock_{normalize_name(r.get('rock_name', 'none'))}"

    master_df['id_key'] = master_df.apply(get_id_key, axis=1)
    jira_titles = fetch_jira_titles(master_df['id_key'].unique().tolist())

    master_df['initiative_name'] = master_df.apply(
        lambda r: jira_titles.get(r['id_key'], r.get('jira_initiative_title', r['id_key'])), axis=1
    )

    # --- Korrigierte Status-Logik (Präzise Budget-Erkennung) ---
    def get_derived_status(row, target_plan):
        if row.get('source_plan') != target_plan: return None
        vals = [str(row[d]) for d in IT_DOMAINS if d in row and pd.notna(row[d])]
        s_str = " ".join(vals).lower()
        if not s_str.strip() or any(x in s_str for x in ['nan', 'n.a.', 'not prioritized']): return None

        if any(x in s_str for x in ['kapazität', 'capacity', 'gap']): return 'Capacity Gap'
        if 'implement' in s_str: return 'Implementation'
        if 'explor' in s_str: return 'Exploration'

        # Strenge numerische Prüfung
        for v in vals:
            try:
                if float(v.replace('.', '').replace(',', '.')) > 0: return 'Budgeted'
            except: continue
        return " / ".join(vals)[:50]

    master_df['status_q1'] = master_df.apply(lambda r: get_derived_status(r, 'q1_plan'), axis=1)
    master_df['status_q2_derived'] = master_df.apply(lambda r: get_derived_status(r, 'q2_plan'), axis=1)

    # --- Korrigierte Priorisierungs-Logik (Schutz vor Inversion) ---
    def get_prio(row, q_key, status_key, target_plan):
        if row.get('source_plan') != target_plan: return None
        base = str(row.get(q_key, '')).lower()
        if 'not prioritized' in base: return 'not prioritized' # Manuelles Veto

        status = row.get(status_key)
        if status == 'Capacity Gap': return 'not prioritized (capacity gap)'
        if status in ['Exploration', 'Implementation', 'Budgeted']: return f'prioritized ({status})'
        if 'prioritized' in base: return 'prioritized'
        return row.get(q_key)

    master_df['prio_q1'] = master_df.apply(lambda r: get_prio(r, 'prio_q1', 'status_q1', 'q1_plan'), axis=1)
    master_df['prio_q2'] = master_df.apply(lambda r: get_prio(r, 'prio_q2', 'status_q2_derived', 'q2_plan'), axis=1)

    # --- Frankenstein-Fix: Ranking-basierte Aggregation ---
    # 1. Ranking-Spalte zum master_df hinzufügen
    master_df['plan_rank'] = master_df['source_plan'].map(lambda x: PLAN_PRIORITY.get(x, 99))

    # 2. Initiative-IDs vergeben
    all_keys = pd.DataFrame({'id_key': master_df['id_key'].unique()})
    all_keys['initiative_id'] = range(1, len(all_keys) + 1)
    master_df = master_df.merge(all_keys, on='id_key')

    # 3. Sortierung auf dem VOLLE master_df (bevor wir Spalten filtern!)
    master_df = master_df.sort_values(by=['initiative_id', 'plan_rank'])

    # 4. Filter für dim_initiative definieren (hier lassen wir plan_rank NOCH DRIN)
    dim_init_cols = [c for c in master_df.columns if c not in IT_DOMAINS and c != 'id_key']
    dim_initiative = master_df[dim_init_cols].copy()

    # 5. Aggregation: Nimm die erste Zeile pro Initiative (dank Sortierung die beste Quelle)
    dim_initiative = dim_initiative.groupby('initiative_id').first().reset_index()

    # 6. Jetzt erst die Hilfsspalte plan_rank entfernen
    if 'plan_rank' in dim_initiative.columns:
        dim_initiative = dim_initiative.drop(columns=['plan_rank'])

    # Fact-Tabelle und Export
    dim_initiative.to_csv(OUT_DIR / 'dim_initiative.csv', index=False)
    print(f"Modell erfolgreich erstellt. {len(dim_initiative)} Initiativen exportiert.")

if __name__ == '__main__':
    build_model()
