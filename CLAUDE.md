# CLAUDE.md

Guidance for Claude Code (and any other agent) working in this repository.

## Project

**Factored AI & Data Hackathon 2026** — team **Clozers**. Repo: `factored-hackathon-2026-clozers`.

Goal: build a working **AI-first banking customer-service system** for a simulated LATAM bank (Mexico, Colombia, Argentina). Not a chatbot — a controlled, auditable customer-service system that understands requests, grounds answers in real data, acts through tools with enforced permissions, and safely escalates to a human when it should not act on its own.

10-day sprint: challenge launched **2026-09-25**, submissions due **2026-10-05**, finalists announced **2026-10-15**, awards **2026-10-16**.

### Team (all junior)

- **Pablo López** — Data Engineer (repo owner)
- **Isabella Loaiza** — Data Scientist
- **Edwin García** — AI Engineer
- **Esteban Arias** — Fullstack Dev (most junior of the team)

Since everyone is junior, prefer explaining *why* over assuming familiarity, keep changes incremental and verifiable, and flag risky/hard-to-reverse actions before taking them.

## Obsidian `[[link]]` convention

This repo's Markdown docs use Obsidian-style `[[double bracket]]` links to connect related ideas across files (e.g. `[[LATAM_Bank_Complete_Data_Dictionary]]`, `[[Factored AI & Data Hackathon 2026]]`). When you write or edit any `.md` file here:

- Link to a related doc or concept with `[[Exact File Name Without Extension]]`.
- It's fine to create a `[[link]]` to a note that doesn't exist yet — that just marks something worth writing later, not an error.
- Don't rewrite this convention into standard Markdown links (`[text](path.md)`) — keep `[[...]]` so the vault stays consistent if/when the docs are opened in Obsidian.

## Doc index — read what's relevant to your task

All source material was transcribed from the organizers' PDFs into Markdown under `docs/`. The original PDFs live in `docs/pdf/` (gitignored — local reference only, not versioned, one of them contains credentials).

| If you need to... | Read |
|---|---|
| Understand event logistics, timeline, team, submission requirements, prizes | [[Datathon_2026_Kickoff]] |
| Understand the actual problem to solve, scope, required deliverables, evaluation rubric, data/execution boundaries | [[Factored AI & Data Hackathon 2026]] |
| Know what data is available, table names, row counts, use-case ideas at a glance | [[LATAM_Bank_Dataset_Summary]] |
| Look up exact column names, types, constraints, and foreign keys for any table | [[LATAM_Bank_Complete_Data_Dictionary]] |

Read **[[Factored AI & Data Hackathon 2026]]** first for any implementation task — it's the actual grading spec (safe automated resolution, controlled automation, evaluation evidence, what counts as an unsafe outcome, etc.). Read **[[Datathon_2026_Kickoff]]** for anything about deadlines, submission format, or event logistics. Use the two dataset docs as reference when writing data pipelines, ETL, or querying — start with the summary, drop into the complete dictionary for column-level detail.

## Data access

- Dataset is on S3, read-only, ~19M rows across 13 tables. Credentials are **not** committed — copy `.env.example` to `.env` and fill in the real values (get them from the team, not from git history).
- `docs/pdf/` and `.env` are gitignored. Never commit either. Never paste the raw credentials back into a tracked `.md` file — reference `.env` variable names instead, as [[LATAM_Bank_Complete_Data_Dictionary]] already does.

## Repo state

This is an early-stage scaffold (`main.py`, `pyproject.toml`, Python ≥3.13, no dependencies yet). Work happens on `develop`; `main` holds the initial clean baseline. No CI/deployment configured yet — check with the team before assuming a stack (Snowflake/AWS/Databricks/Azure were mentioned as optional resources, not requirements).
