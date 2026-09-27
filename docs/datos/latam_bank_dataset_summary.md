# LATAM Bank Dataset

**Factored Datathon 2026**
Dataset Version 1.0.0

| Attribute | Value |
|---|---|
| **Total Records** | **~19 Million** |
| **Tables** | **13** |
| **Countries** | Mexico, Colombia, Argentina |
| **Date Range** | June 2023 - June 2026 |

Generated: July 2026

---

## Executive Summary

This dataset simulates a comprehensive **regional banking system** operating across three Latin American countries: **Mexico, Colombia, and Argentina**. It contains realistic banking, customer service, and digital interaction data spanning **three years** (June 2023 to June 2026).

The dataset includes **19,000,000 records** distributed across **13 tables**, covering everything from customer master data to transaction details, call center interactions, marketing campaigns, and customer complaints.

This is a **synthetically generated dataset** created specifically for the Factored Datathon 2026, with realistic Spanish names, addresses, and regional accent characteristics. **The dataset intentionally includes data quality challenges (duplicates, nulls, late arrivals) to simulate real-world scenarios.**

### Key Characteristics

| Attribute | Value |
|---|---|
| **Total Records** | 19,000,000 rows |
| **Total Tables** | 13 |
| **Countries** | Mexico, Colombia, Argentina |
| **Date Range** | 2023-06-17 to 2026-06-17 |
| **Currencies** | MXN, COP, ARS, USD |
| **Languages** | Spanish (Mexican, Colombian, Argentine accents) |

### Data Quality Challenges

This dataset **intentionally includes real-world data quality challenges** to provide a realistic data engineering experience:

| Challenge | Rate | Description |
|---|---|---|
| **Duplicate Records** | **~2%** | Realistic duplicate entries across tables |
| **Null Values** | **~5%** | Missing data in non-mandatory fields |
| **Late Arrivals** | Yes | Partitioned data may arrive late |
| **Schema Evolution** | Yes | Table schemas may evolve over time |

---

## Tables Overview

### Dimension Tables

| Table Name | Rows | Description |
|---|---|---|
| customers | 150,000 | Bank customer dimension table |
| products | 400,000 | Active financial products of customers |
| branches | 350 | Physical bank branches |
| service_agents | 1,200 | Customer service agents |
| marketing_campaigns | 200 | Bank marketing campaigns |

### Fact Tables

| Table Name | Rows | Description |
|---|---|---|
| transactions | **5,000,000** | Daily financial transactions |
| call_center_interactions | 800,000 | Call center interactions with customers |
| call_transcripts | 200,000 | Call center call transcripts |
| satisfaction_surveys | 250,000 | Post-interaction satisfaction surveys (CSAT, NPS) |
| **digital_events** | **10,000,000** | Digital channel interaction events (mobile app, web) |
| complaints | 80,000 | Complaints and claims system (PQR) |
| campaign_sends | 2,000,000 | Individual marketing campaign sends |

### Reference Tables

| Table Name | Rows | Description |
|---|---|---|
| daily_exchange_rates | 3,000 | Daily exchange rates for currency conversion |

---

## Potential Use Cases

### Customer Analytics
- Customer segmentation and clustering
- **Churn prediction models**
- Customer lifetime value (CLV) analysis
- Cross-sell and up-sell opportunity identification

### Contact Center Optimization
- **First Call Resolution (FCR) improvement**
- Agent performance analysis and benchmarking
- Sentiment trend analysis
- Accent-based routing optimization

### Fraud Detection
- **Transaction fraud detection models**
- Anomaly detection in spending patterns
- Geographic risk modeling

### Marketing Analytics
- Campaign effectiveness measurement
- Channel attribution modeling
- Personalization and targeting models
- A/B testing analysis

### NLP / Text Analytics
- Topic modeling on call transcripts
- **Intent classification**
- Entity extraction from customer interactions
- Multilingual accent detection and classification

### Product Analytics
- Product adoption and usage analysis
- Digital engagement funnel optimization
- Feature usage analysis

---

## Important Notes

- **Spanish Language Data:** All text data (customer names, addresses, transcripts, descriptions) is in Spanish with regional variations.
- **Accent Detection:** The dataset includes accent detection fields (Mexican, Colombian, Argentine) enabling dialect-aware customer service analysis.
- **Multi-Currency Support:** All transactions include both local currency (MXN/COP/ARS) and USD conversion using daily exchange rates.
- **Date Partitioning:** Large fact tables are partitioned by date (year/month/day) for efficient processing and querying.
- **Referential Integrity:** Foreign key relationships are maintained across tables, though a small percentage of orphaned records may exist for testing.
- **Synthetic Data:** This is completely synthetic data generated for educational purposes. No real customer information is included.
- **Data Dictionary:** For detailed schema information including column descriptions, data types, and constraints, please refer to the complete **DATA_DICTIONARY.md** file.

For questions or support regarding this dataset, please contact the Factored Datathon team.

Dataset Version 1.0.0 | Generated July 2026
