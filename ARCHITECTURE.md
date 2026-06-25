# Architektur: Konfigurationsgetriebener ETL-Prozess

## Übersicht

Die ETL-Engine `normalize_it_planning.py` liest IT-Planungs-CSV-Exporte ein, normalisiert sie in ein Star-Schema und schreibt 9 Output-Dateien nach `out/`. Das Modell ist vollständig über JSON-Konfigurationen in `configs/` steuerbar — neue Planstände (z. B. Q3) erfordern keine Code-Änderungen.

## Konfigurationsstruktur

### `configs/global.json`
Definiert das domänenübergreifende Modell-Gerüst:
- Liste der IT-Domänenkürzel (`SFC`, `CPQ`, `SNO`, etc.)
- Aggregat-Definitionen
- Globale Regeln

### `configs/plans/*.json`
Eine Datei pro Planungsquelle. Pflichtfelder:
- `plan_id` — interner Bezeichner (z. B. `"q2_plan"`)
- `period` — Zeitraum (z. B. `"2026-Q2"`)
- `file_path` — Pfad zur CSV-Quelldatei
- `unit_factor` — Umrechnungsfaktor: `1000.0` wenn Quelle in k€, `1.0` wenn bereits in EUR
- `anchors` — Begriffe für automatische Header-Erkennung
- `ignore_columns` — Spalten, die ignoriert werden (z. B. grüne Quartalsplanungs-Spalten im Annual-Plan zur Vermeidung von Doppelzählungen)
- `mapping` — Mapping von Rohspaltenbezeichnungen auf interne Feldnamen

## Das normalisierte Datenmodell (9 Output-Dateien)

### Dimensionstabellen

#### `dim_rock.csv`
| Spalte | Beschreibung |
|---|---|
| `rock_sk` | Surrogatschlüssel |
| `rock_code` | Normalisierter Code |
| `rock_name` | Strategische Säule (z. B. "Simplification", "AI and Data Driven Sales") |

#### `dim_domain.csv`
| Spalte | Beschreibung |
|---|---|
| `domain_sk` | Surrogatschlüssel |
| `domain_code` | Kürzel (z. B. `SFC`, `CPQ`); Aggregate haben eigene Codes |
| `domain_name` | Vollname |
| `domain_group` | Gruppe (`B2B`, `B2B+`, `Non-B2B`) |

#### `dim_initiative.csv`
| Spalte | Beschreibung |
|---|---|
| `initiative_sk` | Surrogatschlüssel |
| `initiative_business_key` | Planübergreifend stabiler Key (primär `jira_init:<key>`) |
| `initiative_name_canonical` | Harmonisierter Name |
| `jira_initiative_link_canonical` | Bereinigte, komma-getrennte Jira-Keys |
| `jira_initiative_key_canonical` | Erster/primärer Jira-Key |
| `default_rock_sk` / `default_rock_name` | Häufigster Rock über alle Planstände |

#### `dim_plan_item.csv`
Eine Zeile pro Quelldaten-Zeile (Source × Initiative × Periode).

| Spalte | Beschreibung |
|---|---|
| `plan_item_sk` | Surrogatschlüssel |
| `plan_item_bk` | Business Key (stabil über ETL-Läufe) |
| `initiative_business_key` | FK zu `dim_initiative` |
| `source_plan` | Planquelle (`annual_2026`, `q2_plan`) |
| `period` | Zeitraum (z. B. `2026-FY`, `2026-Q2`) |
| `quarter_code` | `FY`, `Q1`–`Q4` |
| `priority_status_code` | Normalisierter Status (`prioritized_other`, `not_prioritized`, `to_clarify`, …) |
| `is_prioritized` | Boolean — aktiv priorisiert |
| `initiative_sk` / `rock_sk` | FKs zu Dimensionen |

#### `dim_measure.csv`
| Spalte | Beschreibung |
|---|---|
| `measure_sk` | Surrogatschlüssel |
| `measure_code` | `DOMAIN_BUDGET`, `VALIDATED_B2B_COE_SUM`, `TOTAL_Q1_Q4_COSTS_B2B_COE`, … |
| `measure_group` | `domain_budget` (Team-Ebene) oder `aggregate_budget` (Aggregat) |
| `unit` | Immer `EUR` |

### Faktentabellen

#### `fact_budget.csv` — zentrale Budget-Faktentabelle
| Spalte | Beschreibung |
|---|---|
| `budget_fact_sk` | Surrogatschlüssel |
| `plan_item_sk` | FK zu `dim_plan_item` |
| `initiative_sk` | FK zu `dim_initiative` |
| `domain_sk` / `domain_code` | FK zu `dim_domain` |
| `measure_sk` / `measure_code` | FK zu `dim_measure` |
| `amount_eur` | Budgetwert in **EUR** (nicht k€!) |
| `source_plan` / `period` | Planquelle und Zeitraum |

#### `fact_domain_status.csv`
Qualitative Domain-Status-Texte (z. B. "to clarify", "finished in Q1") pro Initiative × Domain.

| Spalte | Beschreibung |
|---|---|
| `status_code` | Normalisierter Status-Code |
| `status_text_raw` | Originaltext aus der Quelle |
| `involved_flag` | Boolean — Domain ist beteiligt |

#### `fact_initiative_period_priority.csv`
Planübergreifende Priorisierungssicht. Eine Zeile pro Initiative × Periode.

| Spalte | Beschreibung |
|---|---|
| `initiative_sk` | FK zu `dim_initiative` |
| `period` / `quarter_code` | Zeitraum |
| `priority_status_code` | Aggregierter Status (höchste Priorität gewinnt) |
| `is_prioritized` | Boolean |
| `priority_raw_values` | Alle Rohwerte aus allen Plan-Items dieser Periode |
| `source_plans` | Welche Pläne diese Periode abdecken |

### Bridge-Tabelle

#### `bridge_plan_item_epic.csv`
Löst die M:N-Beziehung zwischen Plan-Items und Jira-Epics auf.

## Rechen-Regeln

### Doppelzählungs-Sperre
`fact_budget.csv` enthält sowohl Team-Budgets als auch Aggregate. **Niemals beide gleichzeitig summieren.**

```python
# Bottom-Up (Team-Ebene, präzise)
domain_budgets = fact_budget[fact_budget['measure_group'] == 'domain_budget']

# Top-Down (Offizielle Aggregate)
aggregates = fact_budget[fact_budget['measure_group'] == 'aggregate_budget']
```

### Einheiten
- Gespeichert: **EUR** (`amount_eur`)
- Ausgabe in k€: `amount_eur / 1000` (auf eine Nachkommastelle runden)
- Der Annual-Demandmaster (`B2B-Demandmaster_2026.csv`) liegt bereits in **vollen EUR** vor (`unit_factor=1.0`); Quellen in k€ werden beim ETL-Import mit `unit_factor=1000.0` nach EUR konvertiert

### Priorisierungs-Klassifikation
Die Funktion `classify_priority()` in `normalize_it_planning.py` prüft Negativ-Muster **zuerst**:
1. `not prior` / `nicht prior` → `not_prioritized` (inaktiv)
2. `budget` → `budgeted` (aktiv)
3. `implement` → `implementation` (aktiv)
4. `exploration` → `exploration` (aktiv)
5. `to clarify` → `to_clarify` (inaktiv für Budget-Summen)
6. `prioritized` / `prioritised` → `prioritized_other` (aktiv)

Damit matcht `"not prioritized"` **nicht** fälschlich auf Muster 6.

### Cross-Plan-Vergleiche
Für Vergleiche `annual_2026` vs. `q2_plan` **primär `fact_initiative_period_priority` verwenden** — sie materialisiert die planübergreifende Sicht bereits über `initiative_business_key`. Manuelles Jira-Link-Splitten ist nicht notwendig.

Falls doch direkt auf `dim_initiative` zugegriffen wird: `jira_initiative_key_canonical` enthält den normalisierten ersten Key.

### Zeit-Einheiten
- `annual_2026` → Jahresbudget
- `q2_plan` → Quartalsbudget
- Direkter Abzug (`2026 - Q2`) ist fachlich falsch. Korrekt: Verhältnisbildung (`Q2 / Jahr`) oder Hochrechnung (`Q2 * 4`).

## ETL ausführen & validieren

```bash
# ETL
python3 normalize_it_planning.py

# Schema- und FK-Validierung
python3 validate_normalized_model.py

# Neuen Planstand hinzufügen (kein Code nötig)
# 1. configs/plans/q3_plan.json erstellen (analog q2_plan.json)
# 2. normalize_it_planning.py erneut ausführen
# 3. validate_normalized_model.py zur Verifikation ausführen
```