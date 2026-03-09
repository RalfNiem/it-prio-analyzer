# it-prio-analyzer

A data processing (ETL) tool designed to transform IT demand and budget planning data into a structured star schema for deep analysis and visualization.

## Overview

This project was developed to bridge the gap between high-level annual planning ("Top-Down") and concrete quarterly project execution ("Bottom-Up"). It automates the extraction and cleaning of planning data from CSV exports, allowing for interactive analysis of budget allocations across strategic "Rocks", Business Initiatives, and IT Domains.

## Key Features

- **Data Normalization:** Converts varying budget units (Euro to kEuro) and handles multiple thousands/decimal separators.
- **Dimensional Modeling:** Produces clean CSV outputs (`fact_plan_budget.csv`, `dim_initiative.csv`, etc.) for use in Excel, Power BI, or Python.
- **Semantic Mapping:** Links Jira keys and project descriptions between annual and quarterly planning masters.
- **Robust Processing:** Fuzzy-matching for complex/merged Excel-to-CSV headers and automatic aggregation of duplicate budget entries.

## Project Structure

- `budget_model_builder.py`: The main Python script (ETL process).
- `GEMINI.md`: Contextual documentation for AI-assisted development.
- `out/`: Contains the generated dimensional star schema files.

## Getting Started

### Prerequisites
- Python 3.8+
- Pandas

### Installation
1. Clone the repository.
2. Ensure you have the input files (`Quartalsmaster_Q2.csv` and `B2B-Demandmaster_2026.csv`) in the root directory.
3. Run the analysis:
   ```bash
   python budget_model_builder.py
   ```

## Output Schema
The tool generates four main tables in the `out/` folder:
1. **dim_rock:** Strategic initiatives (Rocks).
2. **dim_domain:** IT Domain teams (e.g., Salesforce, Service Now, AI).
3. **dim_initiative:** Detailed initiatives with descriptions and Jira keys.
4. **fact_plan_budget:** Fact table with all budget values, plan sources (annual vs. quarterly), and time periods.

## License
MIT
