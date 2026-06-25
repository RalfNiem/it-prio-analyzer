# it-prio-analyzer

ETL-Tool, das IT-Bedarfs- und Budgetplanungsdaten aus Excel-CSV-Exporten in ein normalisiertes **Star-Schema** transformiert. Optimiert für die Analyse in ChatGPT, Power BI, Tableau oder Excel.

## Kern-Features

- **Konfigurationsgetriebene Engine:** Neue Datenquellen (z. B. Q3-Plan) können ohne Code-Änderung über JSON-Dateien hinzugefügt werden.
- **Smart Data Parsing:** Automatische Erkennung von deutschen vs. US-Zahlenformaten, Behandlung von Tausender-Trennzeichen, Umrechnung verschiedener Einheiten (€ vs. k€) pro Quelle.
- **Dynamische Header-Erkennung:** Findet Tabellen-Kopfzeilen automatisch anhand von Anker-Begriffen.
- **Stabile Business Keys:** Initiativen werden planübergreifend über `initiative_business_key` (basierend auf Jira-Key) identifiziert.
- **Normalisierte Prioritäten:** Priorisierungsstatus wird deterministisch klassifiziert (Negativ-Muster zuerst) und in `fact_initiative_period_priority` als planübergreifende Sicht materialisiert.

## Projektstruktur

```text
├── normalize_it_planning.py         # Zentrale ETL-Engine
├── validate_normalized_model.py     # Schema- und FK-Validierung der Outputs
├── configs/
│   ├── global.json                  # Domänen-Definitionen & globale Regeln
│   └── plans/
│       ├── annual_2026.json         # Konfiguration Jahres-Demandmaster
│       └── q2_plan.json             # Konfiguration Quartalsmaster Q2
├── input/                           # Quelldateien (CSV-Exporte)
├── out/                             # Normalisiertes Star-Schema (9 Dateien)
└── archive/
    └── old_budget_model_builder_dynamic.py  # Vorgänger-Skript (deprecated)
```

## Inbetriebnahme

### Voraussetzungen
- Python 3.8+
- Pandas (`pip install pandas`)

### ETL ausführen
```bash
python3 normalize_it_planning.py
```
Die Quelldateien (Q1–Q3 sowie der Jahres-Demandmaster) werden standardmäßig aus
`input/` gelesen – unabhängig vom aktuellen Arbeitsverzeichnis. Q3 wird automatisch
eingebunden, sobald `input/Quartalsmaster Q3.csv` vorhanden ist. Einzelne Pfade lassen
sich bei Bedarf via `--q1/--q2/--q3/--annual` überschreiben.

### Outputs validieren
```bash
python3 validate_normalized_model.py
```

## Das Datenmodell (9 Output-Dateien in `out/`)

### Dimensionen

| Datei | Primärschlüssel | Inhalt |
|---|---|---|
| `dim_rock.csv` | `rock_sk` | Strategische Säulen (Rocks) |
| `dim_domain.csv` | `domain_sk` | IT-Domänen/Teams (`domain_code`) + Aggregate |
| `dim_initiative.csv` | `initiative_sk` | Business-Initiativen; planübergreifend stabil via `initiative_business_key` |
| `dim_plan_item.csv` | `plan_item_sk` | Eine Zeile pro Planungsquelle × Initiative; enthält `priority_status_code`, `is_prioritized` |
| `dim_measure.csv` | `measure_sk` | Budget-Maßtypen (`measure_code`, `measure_group`) |

### Fakten

| Datei | Fremdschlüssel | Inhalt |
|---|---|---|
| `fact_budget.csv` | `plan_item_sk`, `initiative_sk`, `domain_sk`, `measure_sk` | Budgetwerte in **EUR** (`amount_eur`); Doppelzählungs-sichere Abfrage via `measure_group` |
| `fact_domain_status.csv` | `plan_item_sk`, `initiative_sk`, `domain_sk` | Qualitative Domain-Status-Texte |
| `fact_initiative_period_priority.csv` | `initiative_sk` | Planübergreifende Priorisierungssicht pro Initiative × Periode |

### Bridge

| Datei | Inhalt |
|---|---|
| `bridge_plan_item_epic.csv` | Auflösung der M:N-Beziehung Plan-Item ↔ Jira-Epic |

## Wichtige Abfrage-Regeln

### Doppelzählungs-Sperre (kritisch)
```python
# Nur Team-Budgets (Bottom-Up) — NIEMALS gemischt mit Aggregaten summieren
team_budgets = fact_budget[fact_budget['measure_group'] == 'domain_budget']

# Offizielle Aggregate (Top-Down)
aggregates = fact_budget[fact_budget['measure_group'] == 'aggregate_budget']
```

### Einheiten
- Gespeichert: **EUR** (`amount_eur`)
- Ausgabe in k€: `amount_eur / 1000`

### Priorisierung (aktiv vs. inaktiv)
```python
active = fact_initiative_period_priority[fact_initiative_period_priority['is_prioritized'] == True]
```
Negativ-Muster (`not_prioritized`, `not_affected`, `not_relevant`) werden in der ETL-Klassifikation zuerst geprüft — `prioritized` matcht nie auf "not prioritized".

### Cross-Plan-Vergleiche
Für Vergleiche zwischen `annual_2026` und `q2_plan` die Tabelle `fact_initiative_period_priority` verwenden — sie materialisiert bereits die planübergreifende Sicht über `initiative_business_key`. Kein manuelles Jira-Link-Splitten notwendig.

## Erweiterung (z. B. Q3 hinzufügen)

Kein Python-Code nötig:
1. `configs/plans/q3_plan.json` erstellen (analog zu `q2_plan.json`).
2. `normalize_it_planning.py` erneut ausführen.
3. `validate_normalized_model.py` zur Verifikation ausführen.

## Lizenz
Für den internen Gebrauch bei der Deutschen Telekom AG.
