#!/usr/bin/env python3
"""
Transform Quartalsmaster Q1/Q2 and B2B-Demandmaster_2026 into a normalized planning model.

Core outputs
------------
- dim_initiative.csv
- dim_plan_item.csv
- dim_domain.csv
- dim_rock.csv
- dim_measure.csv
- fact_budget.csv
- fact_domain_status.csv

Additional outputs for Rock / Initiative / Epic analysis
--------------------------------------------------------
- bridge_plan_item_epic.csv
- fact_initiative_period_priority.csv

Design principles
-----------------
1. Stable business entities (initiatives) are separated from period/source-specific rows.
2. Budget amounts are separated from qualitative domain status texts.
3. Annual kEUR values are converted to EUR so all budget facts use a single currency/unit.
4. All source rows get a stable traceability hash.
5. Epic assignments are explicitly normalized into a bridge table.
6. Quarterly prioritization is normalized into a dedicated initiative-period fact.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd


EMPTY_TOKENS = {"", "nan", "none", "null", "-", "–", "\xa0"}

DOMAIN_DEFS: Dict[str, Dict[str, str]] = {
    "SFC": {"name": "Salesforce Core", "group": "B2B"},
    "CPQ": {"name": "CPQ", "group": "B2B"},
    "SNO": {"name": "ServiceNow", "group": "B2B"},
    "DTP": {"name": "Digital Touchpoints", "group": "B2B"},
    "API": {"name": "API", "group": "B2B"},
    "BAI": {"name": "Business AI", "group": "B2B"},
    "DCI": {"name": "Wholesale / DCI", "group": "B2B"},
    "BIS": {"name": "B2B Essentials - BIS", "group": "B2B"},
    "BAS": {"name": "B2B Essentials - BAS", "group": "B2B"},
    "BOO": {"name": "B2B Essentials - BOO", "group": "B2B"},
    "BDA": {"name": "B2B Essentials - BDA", "group": "B2B"},
    "BCT": {"name": "B2B Classic TC", "group": "B2B+"},
    "CLO": {"name": "Customer Logistics", "group": "B2B+"},
    "ORCA": {"name": "Order2Cash", "group": "B2B+"},
    "TASS": {"name": "Telekom Accenture", "group": "B2B+"},
    "CSSE": {"name": "CSSE", "group": "Non-B2B"},
    "DATA": {"name": "Data", "group": "Non-B2B"},
    "BSS": {"name": "Business Support System", "group": "Non-B2B"},
    "DOT": {"name": "DOT", "group": "Non-B2B"},
    "CFP": {"name": "Customer Finance & Partnering", "group": "Non-B2B"},
    "FIBER": {"name": "Fiber", "group": "Non-B2B"},
    "TECH_PLATFORMS": {"name": "Technik Plattformen", "group": "Non-B2B"},
    "COPPER_OSS": {"name": "Copper OSS", "group": "Non-B2B"},
    "MAGENTA_FIELD_FORCE": {"name": "Magenta Field Force", "group": "Non-B2B"},
}

ANNUAL_DOMAIN_HEADER_MAP = {
    "SFC\n(Andrej Deckl)": "SFC",
    "CPQ\n(Hemanth Meruga)": "CPQ",
    "SNO\n(Karthik Mohan)": "SNO",
    "DTP\n(Knut Goebel)": "DTP",
    "API\n(Frank Koch)": "API",
    "BAI\n(Alexander Lukashev)": "BAI",
    "DCI\n(Klein, Andreas)": "DCI",
    "BIS\n(Sielski, Krzysztof)": "BIS",
    "BAS\n(Heiden, Andreas)": "BAS",
    "BOO\n(Heiden, Andreas)": "BOO",
    "BDA\n(Heiden, Andreas)": "BDA",
    "BCT\n(B2B Classic TC)\n(Roberto Wahl)": "BCT",
    "CLO\nCustomer Logistics\n(Achim Spitz)": "CLO",
    "ORCA\n(Order2Cash)\n(Matthias Graf)": "ORCA",
    "TASS\n(Telekom Accenture)\n(Patrick Kolling)": "TASS",
    "CSSE (Szabó,Zoltán Gyula)": "CSSE",
    "Data \n(Fabian Birchel)": "DATA",
    "Business Support System (Florian Becker)": "BSS",
    "DOT (Valentina Karaulnova)": "DOT",
    "Customer Finance & Partnering (Olaf Piepenbreier)": "CFP",
    "Fiber \n(Jens Lieser)": "FIBER",
    "Technik Plattformen (Schacht, Ronny)": "TECH_PLATFORMS",
    "Copper OSS (Florian Junglas)": "COPPER_OSS",
    "Magenta Field Force (Monika Steinmetz)": "MAGENTA_FIELD_FORCE",
}

AGGREGATE_MEASURE_MAP = {
    "Summe \n(nur B2B-COEs)": "VALIDATED_B2B_COE_SUM",
    "angemeldetes Jahresbudget": "REGISTERED_ANNUAL_BUDGET",
    "Total\nQ1-Q4\nCosts B2B\nCOE": "TOTAL_Q1_Q4_COSTS_B2B_COE",
    "Q1\nCosts B2B\nCOE": "Q1_COSTS_B2B_COE",
    "Q2\nCosts B2B\nCOE": "Q2_COSTS_B2B_COE",
    "Q3\nCosts B2B\nCOE": "Q3_COSTS_B2B_COE",
    "Q4\nCosts B2B\nCOE": "Q4_COSTS_B2B_COE",
    "Total Cost w/o ERP Trafo & Data": "TOTAL_COST_WO_ERP_TRAFO_DATA",
    "Total Cost B2B internal": "TOTAL_COST_B2B_INTERNAL",
    "Total Cost non B2B": "TOTAL_COST_NON_B2B",
    "Total w/o Data & ERP Trafo": "TOTAL_COST_WO_DATA_ERP_TRAFO",
}

MEASURE_DIM = {
    "DOMAIN_BUDGET": ("Domain Budget", "domain_budget", "EUR"),
    "VALIDATED_B2B_COE_SUM": ("Validated B2B COE Sum", "aggregate_budget", "EUR"),
    "REGISTERED_ANNUAL_BUDGET": ("Registered Annual Budget", "aggregate_budget", "EUR"),
    "TOTAL_Q1_Q4_COSTS_B2B_COE": ("Total Q1-Q4 Costs B2B COE", "aggregate_budget", "EUR"),
    "Q1_COSTS_B2B_COE": ("Q1 Costs B2B COE", "aggregate_budget", "EUR"),
    "Q2_COSTS_B2B_COE": ("Q2 Costs B2B COE", "aggregate_budget", "EUR"),
    "Q3_COSTS_B2B_COE": ("Q3 Costs B2B COE", "aggregate_budget", "EUR"),
    "Q4_COSTS_B2B_COE": ("Q4 Costs B2B COE", "aggregate_budget", "EUR"),
    "TOTAL_COST_WO_ERP_TRAFO_DATA": ("Total Cost without ERP Trafo and Data", "aggregate_budget", "EUR"),
    "TOTAL_COST_B2B_INTERNAL": ("Total Cost B2B internal", "aggregate_budget", "EUR"),
    "TOTAL_COST_NON_B2B": ("Total Cost non B2B", "aggregate_budget", "EUR"),
    "TOTAL_COST_WO_DATA_ERP_TRAFO": ("Total Cost without Data and ERP Trafo", "aggregate_budget", "EUR"),
}

ROCK_NAME_MAP = {
    "ai and data driven sales": "AI and Data Driven Sales",
    "growth beyond core": "Growth beyond core",
    "next level large enterprise": "Next Level Large Enterprise",
    "one delivery": "One Delivery",
    "onedelivery": "One Delivery",
    "one delivery (teilfinanzierung)": "One Delivery (Teilfinanzierung)",
    "onedelivery (teilfinanzierung)": "One Delivery (Teilfinanzierung)",
    "mobile boost": "Mobile Boost",
    "real selling time": "Real Selling Time",
    "simplification": "Simplification",
    "obligatory": "Obligatory",
    "erp trafo": "ERP Trafo",
    "broadband push": "Broadband Push",
    "mnc": "MNC",
    "unassigned": "Unassigned",
}

PRIORITY_PRECEDENCE = {
    "budgeted": 1,
    "implementation": 2,
    "exploration": 3,
    "prioritized_other": 4,
    "to_clarify": 5,
    "candidate_only": 6,
    "not_prioritized": 7,
    "other": 8,
    "blank": 9,
}


def clean_str(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).replace("\u00a0", " ")
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def first_non_empty(*values: object) -> str:
    for value in values:
        text = clean_str(value)
        if text and text.lower() not in EMPTY_TOKENS:
            return text
    return ""


def normalize_key(text: object) -> str:
    value = clean_str(text).lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def normalize_budget_key(value: object) -> str:
    text = clean_str(value)
    if not text or text in {"0"}:
        return ""
    return re.sub(r"\s+", "", text)


def split_jira_tokens(value: object) -> List[str]:
    text = clean_str(value)
    if not text:
        return []
    tokens = re.split(r"[,;/\n]+", text)
    cleaned = []
    for token in tokens:
        token = clean_str(token).upper()
        token = re.sub(r"\s+", "", token)
        if not token or token in {"-", "0", "N/A", "NA"}:
            continue
        if re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", token):
            cleaned.append(token)
    return sorted(set(cleaned))


def normalize_rock_name(value: object) -> str:
    text = first_non_empty(value, "Unassigned")
    key = normalize_key(text).replace("_", " ")
    return ROCK_NAME_MAP.get(key, text)


def stable_hash(parts: Iterable[object], length: int = 16) -> str:
    joined = "||".join(clean_str(p) for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:length]


def is_numeric_like(value: object) -> bool:
    text = clean_str(value)
    if not text:
        return False
    if re.search(r"[A-Za-zÄÖÜäöü]", text):
        return False
    return bool(re.fullmatch(r"[-+]?[\d\s.,]+", text))


def parse_number(value: object, multiplier: float = 1.0) -> Optional[float]:
    text = clean_str(value)
    if not text:
        return None
    text = text.replace(" ", "")
    text = text.replace("’", "").replace("'", "")
    # Strip currency symbols before letter-check so values like "95.003,00 €" parse correctly
    text = text.replace("€", "").replace("$", "").replace("£", "").strip()
    if re.search(r"[A-Za-zÄÖÜäöü]", text):
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        if re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+", text):
            text = text.replace(".", "")

    try:
        return float(text) * multiplier
    except ValueError:
        return None


def find_header_row(raw: pd.DataFrame, anchors: List[str]) -> int:
    best_row = -1
    best_score = -1
    anchors_norm = [a.lower() for a in anchors]
    for idx in range(len(raw)):
        row_values = [clean_str(v).lower() for v in raw.iloc[idx].tolist()]
        score = 0
        for anchor in anchors_norm:
            if any(anchor in value for value in row_values):
                score += 1
        if score > best_score:
            best_score = score
            best_row = idx
    if best_score <= 0:
        raise ValueError(f"Could not identify header row for anchors={anchors}")
    return best_row


def load_semicolon_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";", header=None, dtype=str, encoding="utf-8-sig", engine="python")


def slice_table(raw: pd.DataFrame, header_row: int, data_start_row: int) -> pd.DataFrame:
    header = raw.iloc[header_row].fillna("").tolist()
    df = raw.iloc[data_start_row:].copy()

    keep_cols = []
    for idx, col_name in enumerate(header):
        body_non_empty = df.iloc[:, idx].fillna("").astype(str).str.strip().ne("").any()
        if clean_str(col_name) or body_non_empty:
            keep_cols.append(idx)
    df = df.iloc[:, keep_cols].copy()
    header = [header[i] for i in keep_cols]

    seen = {}
    final_cols = []
    for col in header:
        col_clean = clean_str(col)
        base = col_clean if col_clean else "_blank"
        count = seen.get(base, 0)
        seen[base] = count + 1
        final_cols.append(base if count == 0 else f"{base}__{count+1}")

    df.columns = final_cols
    df = df.reset_index(drop=True)
    return df


def row_is_empty(row: pd.Series) -> bool:
    return all(clean_str(v) == "" for v in row.tolist())


def bool_from_x(value: object) -> Optional[bool]:
    text = clean_str(value).lower()
    if not text:
        return None
    if text == "x":
        return True
    return None


def classify_status(value: object) -> Tuple[Optional[str], Optional[bool]]:
    text = clean_str(value)
    if not text:
        return None, None
    lower = text.lower()

    if is_numeric_like(text):
        amount = parse_number(text)
        if amount == 0:
            return "numeric_zero", False
        return "numeric_estimate", True

    status_rules = [
        ("not_affected", r"not affected|nicht betroffen"),
        ("not_relevant", r"not relevant|nicht relevant|not applicable|not for dom"),
        ("finished_previous_period", r"finished in q1|abgeschlossen|done in q1"),
        ("implementation", r"implement"),
        ("exploration", r"exploration"),
        ("to_clarify", r"to clarify|zu kl[aä]r|kretisierung"),
        ("included_elsewhere", r"enthalten in|covered under|mit .*gesch[aä]tzt|estimated with|gesch[aä]tzt mit"),
        ("capacity_blocked", r"kapazit|capacity|[üu]berbuch|beschr[aä]nkter kapa|kein todo"),
        ("not_prioritized", r"not prioritzed|not prioritized|nicht priorisiert"),
    ]
    for code, pattern in status_rules:
        if re.search(pattern, lower):
            return code, code not in {"not_affected", "not_relevant", "numeric_zero", "not_prioritized"}
    return "free_text", None


def classify_priority(value: object, candidate_flag: object = None) -> Tuple[str, bool]:
    text = clean_str(value)
    lower = text.lower()
    if not text:
        if bool_from_x(candidate_flag):
            return "candidate_only", False
        return "blank", False

    if re.search(r"not prior|nicht prior", lower):
        return "not_prioritized", False
    if re.search(r"\bbudget", lower):
        return "budgeted", True
    if re.search(r"implement", lower):
        return "implementation", True
    if re.search(r"exploration", lower):
        return "exploration", True
    if re.search(r"to clarify|zu kl[aä]r|clarif", lower):
        return "to_clarify", False
    if re.search(r"prioritized|prioritised|prio", lower):
        return "prioritized_other", True

    if bool_from_x(candidate_flag):
        return "candidate_only", False
    return "other", False


def period_to_quarter_code(period: str) -> str:
    if period.endswith("-Q1"):
        return "Q1"
    if period.endswith("-Q2"):
        return "Q2"
    if period.endswith("-Q3"):
        return "Q3"
    if period.endswith("-Q4"):
        return "Q4"
    if period.endswith("-FY"):
        return "FY"
    return ""


def detect_domain_code_from_header(header: str) -> Optional[str]:
    text = clean_str(header)
    if text in ANNUAL_DOMAIN_HEADER_MAP:
        return ANNUAL_DOMAIN_HEADER_MAP[text]
    first_line = text.split("\n")[0].strip()
    short = normalize_key(first_line).upper()
    if short in DOMAIN_DEFS:
        return short
    return None


def build_source_row(
    source_plan: str,
    period: str,
    source_row_number: int,
    id_budget_raw: object,
    rock_name: object,
    objective: object,
    initiative_name_raw: object,
    jira_initiative_link: object,
    jira_epic_link: object,
    jira_epic_title: object,
    alignment_team: object,
    value_stream: object,
    business_initiative_cluster: object = "",
    priority_raw: object = "",
    candidate_flag: object = "",
    status_raw: object = "",
    outcome_raw: object = "",
    erp_trafo_raw: object = "",
    q2_stage: object = "",
    remarks: object = "",
    remarks_secondary: object = "",
    likely_involved_coes: object = "",
    reference_initiative: object = "",
    legacy_bemabu_number: object = "",
) -> Dict[str, object]:
    id_budget = normalize_budget_key(id_budget_raw)
    init_tokens = split_jira_tokens(jira_initiative_link)
    epic_tokens = split_jira_tokens(jira_epic_link)

    initiative_name = first_non_empty(initiative_name_raw, jira_epic_title)
    cluster = clean_str(business_initiative_cluster)
    rock = normalize_rock_name(rock_name)
    priority_status_code, is_prioritized = classify_priority(priority_raw, candidate_flag)

    if init_tokens:
        initiative_business_key = f"jira_init:{'|'.join(init_tokens)}"
    elif id_budget:
        initiative_business_key = f"budget:{id_budget}"
    elif initiative_name:
        initiative_business_key = f"title:{normalize_key(initiative_name)}"
    elif epic_tokens:
        initiative_business_key = f"epic:{'|'.join(epic_tokens)}"
    else:
        initiative_business_key = f"row:{source_plan}:{source_row_number}"

    source_row_hash = stable_hash(
        [
            source_plan,
            period,
            source_row_number,
            id_budget,
            rock,
            objective,
            initiative_name,
            "|".join(init_tokens),
            "|".join(epic_tokens),
            alignment_team,
            value_stream,
            cluster,
            priority_raw,
        ]
    )
    plan_item_bk = f"{source_plan}:{source_row_hash}"

    return {
        "plan_item_bk": plan_item_bk,
        "initiative_business_key": initiative_business_key,
        "source_plan": source_plan,
        "period": period,
        "quarter_code": period_to_quarter_code(period),
        "source_row_number": source_row_number,
        "source_row_hash": source_row_hash,
        "id_budget_raw": id_budget,
        "rock_name": rock,
        "objective": clean_str(objective),
        "initiative_name_raw": initiative_name,
        "business_initiative_cluster": cluster,
        "jira_initiative_link_raw": ", ".join(init_tokens),
        "jira_initiative_key_primary": init_tokens[0] if init_tokens else "",
        "jira_epic_link_raw": ", ".join(epic_tokens),
        "jira_epic_key_primary": epic_tokens[0] if epic_tokens else "",
        "jira_epic_title": clean_str(jira_epic_title),
        "alignment_team": clean_str(alignment_team),
        "value_stream": clean_str(value_stream),
        "priority_raw": clean_str(priority_raw),
        "priority_status_code": priority_status_code,
        "is_prioritized": is_prioritized,
        "candidate_flag": bool_from_x(candidate_flag),
        "status_raw": clean_str(status_raw),
        "outcome_2026_raw": clean_str(outcome_raw),
        "erp_trafo_raw": clean_str(erp_trafo_raw),
        "q2_stage": clean_str(q2_stage),
        "remarks": clean_str(remarks),
        "remarks_secondary": clean_str(remarks_secondary),
        "likely_involved_coes": clean_str(likely_involved_coes),
        "reference_initiative": clean_str(reference_initiative),
        "legacy_bemabu_number": clean_str(legacy_bemabu_number),
    }


def extract_q1(path: Path) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    raw = load_semicolon_csv(path)
    header_row = find_header_row(raw, ["Budget-Schlüssel", "Jira-Link", "Alignment-Team"])
    df = slice_table(raw, header_row=header_row, data_start_row=header_row + 1)

    row_records: List[Dict[str, object]] = []
    budget_facts: List[Dict[str, object]] = []
    status_facts: List[Dict[str, object]] = []

    domain_cols = [c for c in df.columns if detect_domain_code_from_header(c)]
    for idx, row in df.iterrows():
        if row_is_empty(row):
            continue

        source_row = build_source_row(
            source_plan="q1_plan",
            period="2026-Q1",
            source_row_number=idx + header_row + 2,
            id_budget_raw=row.get("Budget-Schlüssel"),
            rock_name=row.get("Rocks"),
            objective=row.get("Objective\n(Strategisches Ziel)"),
            initiative_name_raw=row.get("JIRA Business Initiative (Beschreibung)"),
            jira_initiative_link=row.get("Jira-Link\nInitiative"),
            jira_epic_link=row.get("Jira-Link\nBusiness-Epic\nfür Q1"),
            jira_epic_title=row.get("Business Epic Q1\nTitle"),
            alignment_team=row.get("Alignment-Team"),
            value_stream=row.get("Value Stream"),
            priority_raw=row.get("Prio\nQ1"),
            candidate_flag=row.get("Kandidat\nfür Q1 (x)"),
            remarks=row.get("Bemerkungen"),
            legacy_bemabu_number=row.get("Alte BEMABU-Nummer"),
        )
        row_records.append(source_row)

        for col in domain_cols:
            raw_value = clean_str(row.get(col))
            if not raw_value:
                continue
            domain_code = detect_domain_code_from_header(col)
            amount = parse_number(raw_value, multiplier=1.0)
            if amount is not None:
                budget_facts.append(
                    {
                        "plan_item_bk": source_row["plan_item_bk"],
                        "initiative_business_key": source_row["initiative_business_key"],
                        "source_plan": source_row["source_plan"],
                        "period": source_row["period"],
                        "domain_code": domain_code,
                        "measure_code": "DOMAIN_BUDGET",
                        "amount_eur": amount,
                        "amount_raw": raw_value,
                        "raw_column_name": clean_str(col),
                    }
                )
            else:
                status_code, involved = classify_status(raw_value)
                status_facts.append(
                    {
                        "plan_item_bk": source_row["plan_item_bk"],
                        "initiative_business_key": source_row["initiative_business_key"],
                        "source_plan": source_row["source_plan"],
                        "period": source_row["period"],
                        "domain_code": domain_code,
                        "status_code": status_code,
                        "status_text_raw": raw_value,
                        "involved_flag": involved,
                        "raw_column_name": clean_str(col),
                    }
                )
    return row_records, budget_facts, status_facts


def extract_q2(path: Path) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    raw = load_semicolon_csv(path)
    header_row = find_header_row(raw, ["Budget-Schlüssel", "Value Stream", "Q2 Stage"])
    df = slice_table(raw, header_row=header_row, data_start_row=header_row + 1)

    row_records: List[Dict[str, object]] = []
    budget_facts: List[Dict[str, object]] = []
    status_facts: List[Dict[str, object]] = []

    domain_cols = [c for c in df.columns if detect_domain_code_from_header(c)]
    for idx, row in df.iterrows():
        if row_is_empty(row):
            continue

        priority = first_non_empty(row.get("Prio\nQ2"), row.get("Prio\nQ2__2"))

        source_row = build_source_row(
            source_plan="q2_plan",
            period="2026-Q2",
            source_row_number=idx + header_row + 2,
            id_budget_raw=row.get("Budget-Schlüssel"),
            rock_name=row.get("Rocks"),
            objective=row.get("Objective\n(Strategisches Ziel)"),
            initiative_name_raw=row.get("JIRA Business Initiative (Beschreibung)"),
            jira_initiative_link=row.get("Jira-Link\nInitiative \n(Prio-Roadmap)"),
            jira_epic_link=row.get("Jira-Link\nBusiness-Epic\nfür Q2"),
            jira_epic_title=row.get("Business Epic Q2\nTitle"),
            alignment_team=row.get("Alignment-Team"),
            value_stream=row.get("Value Stream"),
            priority_raw=priority,
            q2_stage=row.get("Q2 Stage"),
            remarks=row.get("Bemerkungen"),
            remarks_secondary=row.get("Remarks (Swapnil & Indivar) - 25/02"),
            likely_involved_coes=row.get("Likely Involved CoEs"),
        )
        row_records.append(source_row)

        for col in domain_cols:
            raw_value = clean_str(row.get(col))
            if not raw_value:
                continue
            domain_code = detect_domain_code_from_header(col)
            amount = parse_number(raw_value, multiplier=1.0)
            if amount is not None:
                budget_facts.append(
                    {
                        "plan_item_bk": source_row["plan_item_bk"],
                        "initiative_business_key": source_row["initiative_business_key"],
                        "source_plan": source_row["source_plan"],
                        "period": source_row["period"],
                        "domain_code": domain_code,
                        "measure_code": "DOMAIN_BUDGET",
                        "amount_eur": amount,
                        "amount_raw": raw_value,
                        "raw_column_name": clean_str(col),
                    }
                )
            else:
                status_code, involved = classify_status(raw_value)
                status_facts.append(
                    {
                        "plan_item_bk": source_row["plan_item_bk"],
                        "initiative_business_key": source_row["initiative_business_key"],
                        "source_plan": source_row["source_plan"],
                        "period": source_row["period"],
                        "domain_code": domain_code,
                        "status_code": status_code,
                        "status_text_raw": raw_value,
                        "involved_flag": involved,
                        "raw_column_name": clean_str(col),
                    }
                )

        for col in ["Summe \n(nur B2B-COEs)", "angemeldetes Jahresbudget"]:
            raw_value = clean_str(row.get(col))
            amount = parse_number(raw_value, multiplier=1.0)
            if amount is None:
                continue
            budget_facts.append(
                {
                    "plan_item_bk": source_row["plan_item_bk"],
                    "initiative_business_key": source_row["initiative_business_key"],
                    "source_plan": source_row["source_plan"],
                    "period": source_row["period"],
                    "domain_code": "",
                    "measure_code": AGGREGATE_MEASURE_MAP[col],
                    "amount_eur": amount,
                    "amount_raw": raw_value,
                    "raw_column_name": clean_str(col),
                }
            )

    return row_records, budget_facts, status_facts


def extract_annual(path: Path) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    raw = load_semicolon_csv(path)
    header_row = find_header_row(raw, ["Budget-Schlüssel", "Business Initiative/Epic", "Alignment Team"])
    df = slice_table(raw, header_row=header_row, data_start_row=header_row + 1)

    row_records: List[Dict[str, object]] = []
    budget_facts: List[Dict[str, object]] = []
    status_facts: List[Dict[str, object]] = []

    domain_cols = [c for c in df.columns if c in ANNUAL_DOMAIN_HEADER_MAP]
    aggregate_cols = [c for c in AGGREGATE_MEASURE_MAP if c in df.columns]

    for idx, row in df.iterrows():
        if row_is_empty(row):
            continue
        # Skip rows with no identity fields — they produce useless fallback row: keys
        if not any(clean_str(row.get(c)) for c in ["Budget-Schlüssel", "Business Initiative/Epic", "Jira-LINK"]):
            continue

        source_row = build_source_row(
            source_plan="annual_2026",
            period="2026-FY",
            source_row_number=idx + header_row + 2,
            id_budget_raw=row.get("Budget-Schlüssel"),
            rock_name=row.get("Rock"),
            objective="",
            initiative_name_raw=row.get("Business Initiative/Epic"),
            jira_initiative_link=row.get("Jira-LINK"),
            jira_epic_link="",
            jira_epic_title="",
            alignment_team=row.get("Alignment Team"),
            value_stream=row.get("Value Stream"),
            business_initiative_cluster=row.get("Business Initiative Cluster"),
            priority_raw=row.get("Status"),
            status_raw=row.get("Status"),
            outcome_raw=row.get("Outcome \n2026\n"),
            erp_trafo_raw=row.get("ERP Trafo"),
            remarks=row.get("Bemerkungen"),
            remarks_secondary=row.get("Bemerkung/ alte BEMABU-Nummer"),
            reference_initiative=row.get("Reference Initiative (only to be filled up by Enrico, Dirk and Sujit)"),
            legacy_bemabu_number=row.get("Bemerkung/ alte BEMABU-Nummer"),
        )
        row_records.append(source_row)

        for col in domain_cols:
            raw_value = clean_str(row.get(col))
            amount = parse_number(raw_value, multiplier=1000.0)
            if amount is None:
                continue
            budget_facts.append(
                {
                    "plan_item_bk": source_row["plan_item_bk"],
                    "initiative_business_key": source_row["initiative_business_key"],
                    "source_plan": source_row["source_plan"],
                    "period": source_row["period"],
                    "domain_code": ANNUAL_DOMAIN_HEADER_MAP[col],
                    "measure_code": "DOMAIN_BUDGET",
                    "amount_eur": amount,
                    "amount_raw": raw_value,
                    "raw_column_name": clean_str(col),
                }
            )

        for col in aggregate_cols:
            raw_value = clean_str(row.get(col))
            amount = parse_number(raw_value, multiplier=1000.0)
            if amount is None:
                continue
            budget_facts.append(
                {
                    "plan_item_bk": source_row["plan_item_bk"],
                    "initiative_business_key": source_row["initiative_business_key"],
                    "source_plan": source_row["source_plan"],
                    "period": source_row["period"],
                    "domain_code": "",
                    "measure_code": AGGREGATE_MEASURE_MAP[col],
                    "amount_eur": amount,
                    "amount_raw": raw_value,
                    "raw_column_name": clean_str(col),
                }
            )

    return row_records, budget_facts, status_facts


def extract_q3(path: Path) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    raw = load_semicolon_csv(path)
    header_row = find_header_row(raw, ["Budget-Schlüssel", "Jira-Link", "Alignment-Team"])
    df = slice_table(raw, header_row=header_row, data_start_row=header_row + 1)

    row_records: List[Dict[str, object]] = []
    budget_facts: List[Dict[str, object]] = []
    status_facts: List[Dict[str, object]] = []

    domain_cols = [c for c in df.columns if detect_domain_code_from_header(c)]
    for idx, row in df.iterrows():
        if row_is_empty(row):
            continue

        source_row = build_source_row(
            source_plan="q3_plan",
            period="2026-Q3",
            source_row_number=idx + header_row + 2,
            id_budget_raw=row.get(" Budget-Schlüssel") or row.get("Budget-Schlüssel"),
            rock_name=row.get("Rocks"),
            objective=row.get("Objective\n(Strategisches Ziel)"),
            initiative_name_raw=row.get("JIRA Business Initiative (Beschreibung)"),
            jira_initiative_link=row.get("Jira-Link\nInitiative\n(Prio-Roadmap)"),
            jira_epic_link=row.get("Jira-Link\nBusiness-Epic\nfür Q3"),
            jira_epic_title=row.get("Business Epic Q3\nTitle"),
            alignment_team=row.get("Alignment-Team"),
            value_stream=row.get("Value Stream"),
            priority_raw=row.get("Prio\nQ3"),
            remarks=row.get("Bemerkungen"),
            reference_initiative=row.get("Predecessor BE in Q2\n(optional)"),
        )
        row_records.append(source_row)

        for col in domain_cols:
            raw_value = clean_str(row.get(col))
            if not raw_value:
                continue
            domain_code = detect_domain_code_from_header(col)
            amount = parse_number(raw_value, multiplier=1.0)
            if amount is not None:
                budget_facts.append(
                    {
                        "plan_item_bk": source_row["plan_item_bk"],
                        "initiative_business_key": source_row["initiative_business_key"],
                        "source_plan": source_row["source_plan"],
                        "period": source_row["period"],
                        "domain_code": domain_code,
                        "measure_code": "DOMAIN_BUDGET",
                        "amount_eur": amount,
                        "amount_raw": raw_value,
                        "raw_column_name": clean_str(col),
                    }
                )
            else:
                status_code, involved = classify_status(raw_value)
                status_facts.append(
                    {
                        "plan_item_bk": source_row["plan_item_bk"],
                        "initiative_business_key": source_row["initiative_business_key"],
                        "source_plan": source_row["source_plan"],
                        "period": source_row["period"],
                        "domain_code": domain_code,
                        "status_code": status_code,
                        "status_text_raw": raw_value,
                        "involved_flag": involved,
                        "raw_column_name": clean_str(col),
                    }
                )

        for col in ["Summe \n(nur B2B-COEs)", "angemeldetes Jahresbudget"]:
            raw_value = clean_str(row.get(col))
            amount = parse_number(raw_value, multiplier=1.0)
            if amount is None:
                continue
            budget_facts.append(
                {
                    "plan_item_bk": source_row["plan_item_bk"],
                    "initiative_business_key": source_row["initiative_business_key"],
                    "source_plan": source_row["source_plan"],
                    "period": source_row["period"],
                    "domain_code": "",
                    "measure_code": AGGREGATE_MEASURE_MAP[col],
                    "amount_eur": amount,
                    "amount_raw": raw_value,
                    "raw_column_name": clean_str(col),
                }
            )

    return row_records, budget_facts, status_facts


def _mode_or_first(series: pd.Series) -> str:
    cleaned = series.fillna("").astype(str).map(clean_str)
    cleaned = cleaned[cleaned != ""]
    if cleaned.empty:
        return ""
    mode = cleaned.mode()
    if not mode.empty:
        return clean_str(mode.iloc[0])
    return clean_str(cleaned.iloc[0])


def build_dimensions_and_facts(
    row_records: List[Dict[str, object]],
    budget_facts: List[Dict[str, object]],
    status_facts: List[Dict[str, object]],
) -> Dict[str, pd.DataFrame]:
    row_df = pd.DataFrame(row_records).drop_duplicates(subset=["plan_item_bk"]).copy()
    if row_df.empty:
        raise ValueError("No plan rows extracted.")

    rock_names = sorted(set(first_non_empty(r, "Unassigned") for r in row_df["rock_name"].tolist()))
    dim_rock = pd.DataFrame(
        [
            {
                "rock_sk": i + 1,
                "rock_code": normalize_key(name).upper(),
                "rock_name": name,
            }
            for i, name in enumerate(rock_names)
        ]
    )
    rock_map = dict(zip(dim_rock["rock_name"], dim_rock["rock_sk"]))

    initiative_rows = []
    for initiative_bk, grp in row_df.groupby("initiative_business_key", dropna=False):
        initiative_name = _mode_or_first(grp["initiative_name_raw"])
        cluster = _mode_or_first(grp["business_initiative_cluster"])
        budget_key = _mode_or_first(grp["id_budget_raw"])
        jira_link = _mode_or_first(grp["jira_initiative_link_raw"])
        jira_primary = _mode_or_first(grp["jira_initiative_key_primary"])
        default_rock_name = first_non_empty(_mode_or_first(grp["rock_name"]), "Unassigned")

        initiative_rows.append(
            {
                "initiative_business_key": initiative_bk,
                "id_budget_raw": budget_key,
                "initiative_name_canonical": initiative_name,
                "business_initiative_cluster": cluster,
                "jira_initiative_link_canonical": jira_link,
                "jira_initiative_key_canonical": jira_primary,
                "default_rock_sk": rock_map.get(default_rock_name),
                "default_rock_name": default_rock_name,
            }
        )

    dim_initiative = pd.DataFrame(initiative_rows).sort_values(["initiative_business_key"]).reset_index(drop=True).fillna("")
    dim_initiative.insert(0, "initiative_sk", range(1, len(dim_initiative) + 1))
    initiative_map = dict(zip(dim_initiative["initiative_business_key"], dim_initiative["initiative_sk"]))

    row_df["initiative_sk"] = row_df["initiative_business_key"].map(initiative_map).astype("Int64")
    row_df["rock_sk"] = row_df["rock_name"].map(rock_map).astype("Int64")

    dim_plan_item = row_df.sort_values(["source_plan", "source_row_number"]).reset_index(drop=True).copy().fillna("")
    dim_plan_item.insert(0, "plan_item_sk", range(1, len(dim_plan_item) + 1))
    plan_item_map = dict(zip(dim_plan_item["plan_item_bk"], dim_plan_item["plan_item_sk"]))

    domain_codes = set()
    if budget_facts:
        domain_codes.update(code for code in pd.DataFrame(budget_facts)["domain_code"].tolist() if code)
    if status_facts:
        domain_codes.update(code for code in pd.DataFrame(status_facts)["domain_code"].tolist() if code)
    dim_domain = pd.DataFrame(
        [
            {
                "domain_sk": i + 1,
                "domain_code": code,
                "domain_name": DOMAIN_DEFS.get(code, {}).get("name", code),
                "domain_group": DOMAIN_DEFS.get(code, {}).get("group", "Unknown"),
            }
            for i, code in enumerate(sorted(domain_codes))
        ]
    )
    domain_map = dict(zip(dim_domain["domain_code"], dim_domain["domain_sk"]))

    measure_codes = sorted(set(pd.DataFrame(budget_facts)["measure_code"].tolist()))
    dim_measure = pd.DataFrame(
        [
            {
                "measure_sk": i + 1,
                "measure_code": code,
                "measure_name": MEASURE_DIM[code][0],
                "measure_group": MEASURE_DIM[code][1],
                "unit": MEASURE_DIM[code][2],
            }
            for i, code in enumerate(measure_codes)
        ]
    )
    measure_map = dict(zip(dim_measure["measure_code"], dim_measure["measure_sk"]))

    fact_budget = pd.DataFrame(budget_facts).copy()
    if fact_budget.empty:
        fact_budget = pd.DataFrame(
            columns=[
                "budget_fact_sk", "plan_item_sk", "initiative_sk", "source_plan", "period", "domain_sk",
                "domain_code", "measure_sk", "measure_code", "amount_eur", "amount_raw", "raw_column_name"
            ]
        )
    else:
        fact_budget["plan_item_sk"] = fact_budget["plan_item_bk"].map(plan_item_map).astype("Int64")
        fact_budget["initiative_sk"] = fact_budget["initiative_business_key"].map(initiative_map).astype("Int64")
        fact_budget["domain_sk"] = fact_budget["domain_code"].map(domain_map).astype("Int64")
        fact_budget["measure_sk"] = fact_budget["measure_code"].map(measure_map).astype("Int64")
        fact_budget = fact_budget[
            [
                "plan_item_sk", "initiative_sk", "source_plan", "period", "domain_sk", "domain_code",
                "measure_sk", "measure_code", "amount_eur", "amount_raw", "raw_column_name"
            ]
        ].sort_values(["source_plan", "plan_item_sk", "measure_code", "domain_code"])
        fact_budget.insert(0, "budget_fact_sk", range(1, len(fact_budget) + 1))

    fact_domain_status = pd.DataFrame(status_facts).copy()
    if fact_domain_status.empty:
        fact_domain_status = pd.DataFrame(
            columns=[
                "status_fact_sk", "plan_item_sk", "initiative_sk", "source_plan", "period", "domain_sk",
                "domain_code", "status_code", "status_text_raw", "involved_flag", "raw_column_name"
            ]
        )
    else:
        fact_domain_status["plan_item_sk"] = fact_domain_status["plan_item_bk"].map(plan_item_map).astype("Int64")
        fact_domain_status["initiative_sk"] = fact_domain_status["initiative_business_key"].map(initiative_map).astype("Int64")
        fact_domain_status["domain_sk"] = fact_domain_status["domain_code"].map(domain_map).astype("Int64")
        fact_domain_status = fact_domain_status[
            [
                "plan_item_sk", "initiative_sk", "source_plan", "period", "domain_sk", "domain_code",
                "status_code", "status_text_raw", "involved_flag", "raw_column_name"
            ]
        ].sort_values(["source_plan", "plan_item_sk", "domain_code"])
        fact_domain_status.insert(0, "status_fact_sk", range(1, len(fact_domain_status) + 1))

    bridge_plan_item_epic = build_bridge_plan_item_epic(dim_plan_item)
    fact_initiative_period_priority = build_fact_initiative_period_priority(dim_plan_item, dim_initiative)

    return {
        "dim_initiative": dim_initiative,
        "dim_plan_item": dim_plan_item,
        "dim_domain": dim_domain,
        "dim_rock": dim_rock,
        "dim_measure": dim_measure,
        "fact_budget": fact_budget,
        "fact_domain_status": fact_domain_status,
        "bridge_plan_item_epic": bridge_plan_item_epic,
        "fact_initiative_period_priority": fact_initiative_period_priority,
    }


def build_bridge_plan_item_epic(dim_plan_item: pd.DataFrame) -> pd.DataFrame:
    records: List[Dict[str, object]] = []
    for _, row in dim_plan_item.iterrows():
        init_keys = split_jira_tokens(row.get("jira_initiative_link_raw"))
        epic_keys = split_jira_tokens(row.get("jira_epic_link_raw"))

        if not epic_keys:
            continue

        initiative_title = clean_str(row.get("initiative_name_raw"))
        epic_title = clean_str(row.get("jira_epic_title"))
        key_quality_parts: List[str] = []
        if not init_keys:
            key_quality_parts.append("missing_initiative_key")
        if len(init_keys) > 1:
            key_quality_parts.append("multiple_initiative_keys")
        if len(epic_keys) > 1:
            key_quality_parts.append("multiple_epic_keys")
        if not epic_title:
            key_quality_parts.append("missing_epic_title")
        key_quality_flag = "|".join(key_quality_parts) if key_quality_parts else "ok"

        primary_initiative = init_keys[0] if init_keys else ""

        # Epic-Prioritaet des Plan-Items in die Bridge uebernehmen, damit nachgelagerte
        # Auswertungen (z. B. Rock-Analyzer) die echte Quartalsprio je Epic kennen.
        # "In der Bridge" bedeutet nur "im Plan erwaehnt" - NICHT automatisch priorisiert.
        epic_priority_status_code = clean_str(row.get("priority_status_code"))
        epic_is_prioritized = bool(row.get("is_prioritized"))
        epic_priority_raw = clean_str(row.get("priority_raw"))

        for epic_key in epic_keys:
            records.append(
                {
                    "plan_item_sk": int(row["plan_item_sk"]),
                    "initiative_sk": int(row["initiative_sk"]) if str(row.get("initiative_sk")) != "<NA>" else None,
                    "rock_sk": int(row["rock_sk"]) if str(row.get("rock_sk")) != "<NA>" else None,
                    "rock_name": clean_str(row.get("rock_name")),
                    "source_plan": clean_str(row.get("source_plan")),
                    "period": clean_str(row.get("period")),
                    "quarter_code": clean_str(row.get("quarter_code")),
                    "jira_initiative_key": primary_initiative,
                    "jira_initiative_keys_all": ", ".join(init_keys),
                    "initiative_title": initiative_title,
                    "jira_epic_key": epic_key,
                    "epic_title": epic_title,
                    "is_explicit_in_plan": True,
                    "epic_is_prioritized": epic_is_prioritized,
                    "epic_priority_status_code": epic_priority_status_code,
                    "epic_priority_raw": epic_priority_raw,
                    "key_quality_flag": key_quality_flag,
                }
            )

    if not records:
        return pd.DataFrame(
            columns=[
                "plan_item_epic_sk", "plan_item_sk", "initiative_sk", "rock_sk", "rock_name", "source_plan",
                "period", "quarter_code", "jira_initiative_key", "jira_initiative_keys_all", "initiative_title",
                "jira_epic_key", "epic_title", "is_explicit_in_plan",
                "epic_is_prioritized", "epic_priority_status_code", "epic_priority_raw", "key_quality_flag"
            ]
        )

    bridge = pd.DataFrame(records).drop_duplicates(
        subset=["plan_item_sk", "jira_initiative_key", "jira_epic_key"]
    ).sort_values(["rock_name", "initiative_title", "jira_epic_key", "plan_item_sk"]).reset_index(drop=True)
    bridge.insert(0, "plan_item_epic_sk", range(1, len(bridge) + 1))
    return bridge


def build_fact_initiative_period_priority(dim_plan_item: pd.DataFrame, dim_initiative: pd.DataFrame) -> pd.DataFrame:
    if dim_plan_item.empty:
        return pd.DataFrame(
            columns=[
                "initiative_period_priority_sk", "initiative_sk", "initiative_business_key", "period", "quarter_code",
                "rock_sk", "rock_name", "jira_initiative_key", "initiative_name", "priority_status_code",
                "is_prioritized", "priority_status_codes_present", "priority_raw_values", "plan_item_count",
                "prioritized_plan_item_count", "source_plans"
            ]
        )

    init_bk_map = dict(zip(dim_initiative["initiative_sk"], dim_initiative["initiative_business_key"]))
    jira_key_map = dict(zip(dim_initiative["initiative_sk"], dim_initiative["jira_initiative_key_canonical"]))
    name_map = dict(zip(dim_initiative["initiative_sk"], dim_initiative["initiative_name_canonical"]))

    records: List[Dict[str, object]] = []
    grouped = dim_plan_item.groupby(["initiative_sk", "period"], dropna=False)
    for (initiative_sk, period), grp in grouped:
        codes = [clean_str(v) or "blank" for v in grp["priority_status_code"].tolist()]
        raw_values = sorted({clean_str(v) for v in grp["priority_raw"].tolist() if clean_str(v)})
        candidate_count = int(pd.Series(grp["is_prioritized"]).fillna(False).astype(bool).sum())

        selected_code = sorted(codes, key=lambda x: PRIORITY_PRECEDENCE.get(x, 99))[0] if codes else "blank"
        is_prioritized = selected_code in {"budgeted", "implementation", "exploration", "prioritized_other"}

        rock_name = _mode_or_first(grp["rock_name"])
        rock_sk_values = grp["rock_sk"].dropna().astype(int)
        rock_sk = int(rock_sk_values.mode().iloc[0]) if not rock_sk_values.empty else None

        source_plans = sorted({clean_str(v) for v in grp["source_plan"].tolist() if clean_str(v)})

        initiative_sk_int = int(initiative_sk) if str(initiative_sk) != "<NA>" else None
        records.append(
            {
                "initiative_sk": initiative_sk_int,
                "initiative_business_key": init_bk_map.get(initiative_sk_int, ""),
                "period": clean_str(period),
                "quarter_code": period_to_quarter_code(clean_str(period)),
                "rock_sk": rock_sk,
                "rock_name": rock_name,
                "jira_initiative_key": jira_key_map.get(initiative_sk_int, ""),
                "initiative_name": name_map.get(initiative_sk_int, ""),
                "priority_status_code": selected_code,
                "is_prioritized": is_prioritized,
                "priority_status_codes_present": " | ".join(sorted(set(codes), key=lambda x: PRIORITY_PRECEDENCE.get(x, 99))),
                "priority_raw_values": " | ".join(raw_values),
                "plan_item_count": len(grp),
                "prioritized_plan_item_count": candidate_count,
                "source_plans": " | ".join(source_plans),
            }
        )

    fact = pd.DataFrame(records).sort_values(["rock_name", "initiative_name", "period"]).reset_index(drop=True)
    fact.insert(0, "initiative_period_priority_sk", range(1, len(fact) + 1))
    return fact


def export_model(model: Dict[str, pd.DataFrame], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in model.items():
        df.to_csv(out_dir / f"{name}.csv", index=False, encoding="utf-8")

    summary_lines = ["# build_summary.txt"]
    for name, df in model.items():
        summary_lines.append(f"{name}: {len(df)}")
    (out_dir / "build_summary.txt").write_text("\n".join(summary_lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize IT planning CSV exports into a stable dimensional model.")
    parser.add_argument("--q1", type=Path, default=Path("Quartalsmaster Q1.csv"), help="Path to Quartalsmaster Q1 CSV")
    parser.add_argument("--q2", type=Path, default=Path("Quartalsmaster Q2.csv"), help="Path to Quartalsmaster Q2 CSV")
    parser.add_argument("--q3", type=Path, default=None, help="Path to Quartalsmaster Q3 CSV (optional)")
    parser.add_argument("--annual", type=Path, default=Path("B2B-Demandmaster_2026.csv"), help="Path to annual demand CSV")
    parser.add_argument("--out-dir", type=Path, default=Path("normalized_out"), help="Output directory")
    args = parser.parse_args()

    q1_rows, q1_budget, q1_status = extract_q1(args.q1)
    q2_rows, q2_budget, q2_status = extract_q2(args.q2)
    annual_rows, annual_budget, annual_status = extract_annual(args.annual)

    q3_rows, q3_budget, q3_status = [], [], []
    if args.q3 and args.q3.exists():
        q3_rows, q3_budget, q3_status = extract_q3(args.q3)
    elif args.q3:
        print(f"Warning: Q3 file not found: {args.q3}")

    model = build_dimensions_and_facts(
        row_records=q1_rows + q2_rows + q3_rows + annual_rows,
        budget_facts=q1_budget + q2_budget + q3_budget + annual_budget,
        status_facts=q1_status + q2_status + q3_status + annual_status,
    )
    export_model(model, args.out_dir)

    print(f"Wrote normalized model to: {args.out_dir.resolve()}")
    for name, df in model.items():
        print(f"{name}: {len(df)} rows")


if __name__ == "__main__":
    main()
