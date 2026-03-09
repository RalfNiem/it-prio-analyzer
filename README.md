# it-prio-analyzer 🚀

Ein hochentwickeltes ETL-Tool (Extract, Transform, Load), das IT-Bedarfs- und Budgetplanungsdaten aus komplexen Excel-CSV-Exporten in ein sauberes, relationales **Star-Schema** transformiert. Optimiert für die Analyse in Power BI, Tableau oder Excel.

## 🌟 Kern-Features

- **Konfigurationsgetriebene Engine:** Neue Datenquellen (z. B. Q3-Plan) können ohne Code-Änderung über einfache JSON-Dateien hinzugefügt werden.
- **Smart Data Parsing:**
    - Automatische Erkennung von deutschen vs. US-Zahlenformaten (Komma vs. Punkt).
    - Korrekte Behandlung von Tausender-Trennzeichen (verhindert den 1000er-Fehler).
    - Umrechnung verschiedener Einheiten (€ vs. k€) pro Quelle.
- **Dynamische Header-Erkennung:** Findet die Tabellen-Kopfzeile automatisch anhand von Anker-Begriffen, unabhängig von Leerzeilen im Export.
- **Jira-Integration:** Reichert Initiativen automatisch mit offiziellen Titeln aus einer lokalen Jira-SQLite-Datenbank an.
- **Automatisierte Bereinigung:** 
    - Verwandelt unstrukturierte Jira-Link-Listen in saubere, kommagetrennte Strings.
    - Aggregiert Duplikate und berechnet komplexe Validierungs-Summen (Differenzen/Summen) on-the-fly.

## 🏗️ Projektstruktur

```text
├── budget_model_builder_dynamic.py  # Die zentrale ETL-Engine
├── configs/                         # Gesamte Steuerungslogik
│   ├── global.json                  # Domänen, Jira-DB Pfad & Globale Regeln
│   └── plans/                       # Quell-spezifische Konfigurationen
│       ├── q2_plan.json             # Regeln für den Quartalsmaster Q2
│       └── annual_2026.json         # Regeln für den Jahres-Demandmaster
├── out/                             # Das fertige Datenmodell (Star-Schema)
├── docs/                            # Technische Dokumentation & Architektur
├── verify_data.py                   # Test-Suite zur Validierung der Datenqualität
└── *.csv                            # Quelldateien (Eingabe)
```

## 🚀 Inbetriebnahme

### Voraussetzungen
- Python 3.8+
- Pandas (`pip install pandas`)

### ETL-Prozess ausführen
Das Skript liest automatisch alle Konfigurationen im Ordner `configs/plans/` ein und verarbeitet die zugehörigen CSV-Dateien:
```bash
python3 budget_model_builder_dynamic.py
```

### Daten validieren
Um sicherzustellen, dass die Konvertierung (insb. Tausenderpunkte und Aggregate) korrekt erfolgt ist:
```bash
python3 verify_data.py
```

## 📂 Das Datenmodell (Output)

Die Dateien im Ordner `out/` bilden ein klassisches Star-Schema:

1.  **`dim_rock.csv`**: Die oberste strategische Ebene (Rocks).
2.  **`dim_domain.csv`**: Die IT-Domänen und Teams (SFC, CPQ, etc.) sowie künstliche Aggregate.
3.  **`dim_initiative.csv`**: Alle Business-Initiativen mit harmonisierten Namen, offiziellen Jira-Titeln und bereinigten Link-Listen.
4.  **`fact_plan_budget.csv`**: Die zentrale Faktentabelle mit allen Budgetwerten, verknüpft über IDs mit den Dimensionen.

## 🛠️ Erweiterung (z. B. Q3 hinzufügen)

Um eine neue Datei hinzuzufügen, muss **kein Python-Code** angepasst werden:
1. Erstelle eine neue Datei `configs/plans/q3_plan.json`.
2. Definiere darin den `file_path`, die `period` und das Spalten-Mapping (analog zu `q2_plan.json`).
3. Starte die Engine erneut.

## 📜 Lizenz
Dieses Projekt ist für den internen Gebrauch bei der Deutschen Telekom AG optimiert.
