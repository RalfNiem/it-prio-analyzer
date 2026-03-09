# Architektur-Plan: Konfigurationsgetriebener ETL-Prozess

## Objective
Umbau des starren, hardcodierten ETL-Skripts in eine generische "Data Engine", die vollständig über externe JSON-Konfigurationsdateien gesteuert wird. Dies ermöglicht das einfache Hinzufügen neuer Datenquellen (z. B. "Quartalsmaster Q3") ohne Code-Änderungen.

## Key Files & Context
- **Neues Verzeichnis:** `configs/`
- **Neues Verzeichnis:** `configs/plans/` (Hier landen die vierteljährlichen Dateien)
- **Neues Skript:** `budget_model_builder_dynamic.py` (ersetzt V2 nicht physisch, wird aber der neue Standard)

## Implementation Steps

### 1. Anlage der globalen Konfiguration (`configs/global.json`)
Diese Datei definiert das "Herz" des Datenmodells, das für alle Quartale gleich bleibt:
- Die Liste der offiziellen IT-Domänenkürzel (`SFC`, `CPQ`, etc.)
- Definition der aggregierten Domänen (`B2B_DELIVERY_TOTAL`, `B2B_DELIVERY_COE`)
- Die Logik für die berechneten Validierungs-Spalten (z.B. `B2B_COE_VALIDATED` = Summe aus SFC, CPQ...)

### 2. Anlage der Quell-Konfigurationen (`configs/plans/*.json`)
Für jede CSV-Datei wird eine separate JSON-Datei erstellt (z.B. `q2_plan.json`, `annual_2026.json`). 
Jede Datei definiert exakt:
- `plan_id` (z.B. "q2_plan")
- `period` (z.B. "2026-Q2")
- `file_path`: Pfad zur CSV.
- `unit_factor`: 1.0 (k€) oder 0.001 (€).
- `anchors`: Begriffe zur automatischen Header-Erkennung.
- `ignore_columns`: Eine Liste von normalisierten Spaltennamen, die das Skript komplett ignorieren soll. 
    - **Wichtig für Annual (Grün):** Alle grünen "Quartal-Planning"-Spalten (Q1-Q4 sowie deren Total) werden hier ignoriert, um Doppelzählungen zu vermeiden.
    - **Wichtig für Annual (Blau):** Alle blauen Spalten am rechten Rand (Non B2B Delivery etc.) werden ignoriert, sofern sie nicht im Mapping stehen.
- `mapping`: Ein Key-Value-Dictionary, das die Rohtexte auf die standardisierten internen Namen (`id_budget`, `jira_epic_link` etc.) mappt. 
    - **Wichtig für Annual (Lila):** Es werden ausschließlich die lila "IT effort estimates"-Spalten für die Domänen (SFC, CPQ, SNO, DTP, API, BAI, DCI, BIS, BAS, BOO, BDA) und die zugehörigen Aggregate ("Total Cost B2B internal" -> B2B_DELIVERY_COE) verwendet.

### 3. Entwicklung der Engine (`budget_model_builder_dynamic.py`)
Das Skript wird so umgeschrieben, dass es:
1. `global.json` einliest.
2. Das Verzeichnis `configs/plans/` nach allen `*.json` Dateien durchsucht.
3. Für jede gefundene Konfiguration die zugehörige CSV lädt, die spezifischen Filter (`ignore_columns`) und Mappings anwendet.
4. Alle geladenen DataFrames automatisch aneinanderhängt (`pd.concat`).
5. Die Dimensionstabellen und die finale Faktentabelle generiert und exportiert.

## Verification & Testing
- Ausführen von `python3 budget_model_builder_dynamic.py`
- Ausführen von `python3 verify_data.py` um sicherzustellen, dass die Ergebnisse exakt identisch mit dem hart erkämpften Stand der V2 sind.
- Simulieren eines "Q3" Durchlaufs durch einfaches Kopieren der Q2-Konfigurationsdatei.