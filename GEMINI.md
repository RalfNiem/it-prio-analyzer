# it-prio-analyzer

This project is a Python-based data processing tool (ETL) designed to transform IT demand and budget planning data from CSV formats into a structured star schema (fact and dimension tables) for analysis and visualization.

## Project Overview

- **Purpose:** Analyzes project prioritization and budget allocation (Rocks, Initiatives, Domains) within a B2B IT organization.
- **Main Technologies:** Python 3, Pandas.
- **Input Data:**
    - `Quartalsmaster_Q2.csv`: Quarterly prioritization and feasibility data.
    - `B2B-Demandmaster_2026.csv`: Annual budget planning data.
- **Output Data:** A dimensional model saved in the `out/` directory:
    - `dim_rock.csv`: Strategic "Rocks" (initiatives).
    - `dim_domain.csv`: IT Domains/Teams (e.g., Salesforce, CPQ, AI).
    - `dim_initiative.csv`: Detailed business initiatives.
    - `fact_plan_budget.csv`: Long-format fact table containing budget amounts per initiative and domain.

## Building and Running

### Prerequisites
- Python 3.8+
- Pandas (`pip install pandas`)

### Execution
Run the main script to process the data:
```bash
python budget_model_builder.py
```

### Note on Filenames
The script `budget_model_builder.py` contains hardcoded paths for input files. Ensure the following mapping if you encounter "File Not Found" errors:
- **Expected:** `B2B-Demandmaster_2026_Quartalsmaster_Q2.csv` -> **Actual:** `Quartalsmaster_Q2.csv`
- **Expected:** `B2B-Demandmaster_2026_Demandmaster_2026.csv` -> **Actual:** `B2B-Demandmaster_2026.csv`

## Development Conventions

- **Data Cleaning:** The project uses a custom `normalize_text` and `parse_amount` logic to handle German/English number formats (e.g., thousands separators and decimal commas).
- **Column Mapping:** All source column names (which often include newlines and special characters) are mapped to canonical internal names in `Q2_KEEP_COLUMNS` and `ANNUAL_KEEP_COLUMNS`.
- **Architecture:** The logic is centralized in `budget_model_builder.py`. Any changes to the input CSV structure require updates to the `header` index in `read_q2_raw`/`read_annual_raw` or the mapping dictionaries.
- **Testing:** Currently, there are no automated tests. Verification is performed by checking the output CSVs in the `out/` folder and reviewing the printed row counts.
