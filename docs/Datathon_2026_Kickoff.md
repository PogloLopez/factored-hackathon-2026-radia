# AI & Data Hackathon

**KICKOFF — SEPTEMBER 25**

---

## Agenda

01. **Keynote** — Israel Niezen, CEO
02. Welcome Aboard
03. Quick Overview
04. **Challenge**
05. Prizes & Closing Remarks

---

## 01. Keynote

Israel, CEO

---

## 02. Welcome Aboard

---

## 03. Overview

### Timeline

| Date | Milestone | Description |
|---|---|---|
| **SEP 01** | **Registration Opens** | Sign up and secure your spot. |
| **SEP 25** | **Challenge Launch** | The full challenge is revealed and the **10-day build begins**. |
| **OCT 5** | **Submissions Close** | Final solutions are submitted for expert evaluation. |
| **OCT 15** | **Finalists Announced** | |
| **OCT 16** | **Award Ceremony** | |

### We are here to support you! (Factored team)

- **Paul León** — Data Engineer
- **Antonio González Dumar** — Analytics Engineer
- **Brandon Rodríguez** — Data Analyst
- **Cindy Lobo** — Technical Recruiter
- **Juan Jaramillo** — Sr. Director Solutions Engineering
- **Diego Ralón** — Machine Learning Engineer
- **Luís Bertozzo** — Machine Learning Engineer
- **Diego Medina** — Marketing Manager

### By the numbers

- **750** expected participants
- **~180** teams forming

> **JOIN 750+ ENGINEERS** in a 2-week challenge to **SOLVE REAL-WORLD PROBLEMS WITH DATA AND AI**

---

## 03. Participant Briefing

**10-Day Sprint - AI-First Banking Customer Service**

### The Challenge: Build An AI-First Banking Agent

> **Don't build a chatbot, build a customer-service system**

**TASK SELECTION — One Focused Banking Workflow**
1. Account / Payment Inquiries
2. Card Support
3. Transaction Disputes
4. Credit-Product Info & Eligibility

**END-TO-END WORKING PROTOTYPE**
Build a fully functional **production-ready prototype** capable of handling complex user interactions beyond a surface-level demo.

**MULTILINGUAL SUPPORT REQUIRED**
Demonstrate robust customer service interactions in both **Spanish** and **Portuguese** to serve LATAM banking needs.

### System Goals & Behavior — What Are We Looking For?

> The system should be able to: **Understand → Decide → Act → Verify → Escalate**

**MINIMUM REQUIREMENTS**
- Maintain conversational context
- Clarify ambiguous requests
- Retrieve trusted information
- Use tools securely
- Execute appropriate workflows
- **Verify that actions actually happened**
- **Know when NOT to act**
- Hand off to a human when needed

> 💡 **Key idea: AI should not be autonomous just because it can be**

| Case | Behavior | Description |
|---|---|---|
| ✅ **Normal Case** | Automated Resolution | Handles policy-compliant automated resolution, verified account queries, and authorized self-service transactions seamlessly |
| ⚠️ **Ambiguous / Unsupported** | Clarification or Abstention | Asks clarifying questions or practices **safe policy abstention** when handling missing parameters or unsupported banking requests |
| 🔀 **Human-Required** | Safe Escalation | Executes a structured handoff to human representatives, transferring verified facts and open questions **without dumping raw transcripts** |

### Evaluation & Rigor — Prove It Works

> **Baseline → Proposed System → Held-out Evaluation**

**TECHNICAL RIGOR**
- **Data Quality & Contracts:** Strict input schema enforcement
- **Reproducible Preparation:** Deterministic pipeline execution
- **Valid Labels:** Grounded relevance judgments & ground truth
- **Leakage Prevention:** Strict train/eval set isolation
- **Appropriate Split:** Realistic held-out test distributions
- **Learned Component:** Benchmark against a baseline model

**KEY METRICS TO MEASURE**
- **Safe Automated Resolution**
- **Unsafe Outcomes**
- **Cost Efficiency**

### Technical Deliverables — Prove It Works

| Area | Requirement |
|---|---|
| **Data-Backed Baseline** | Justify workflow selection using reproducible logs |
| **Grounded AI Core** | Ground all responses in verified records |
| **Controlled Automation** | Enforce action permissions besides model prompts |
| **Data & ML Discipline** | Repeatable pipelines with strict schema contracts |
| **Measured Failures** | Stress-test held-out cases against injection |
| **Route to Operation** | Deterministic setup with audit execution logs |

### Multi-Disciplinary Evaluation — No Single Skill Is Mandatory

| Discipline | Suggested Tasks |
|---|---|
| **Artificial Intelligence** | Production backend and structured JSON handoffs |
| **Machine Learning** | LLM/RAG orchestration and **prompt injection defense** |
| **Data Engineering** | Strong ETL/ELT pipeline and **customer record isolation** |
| **Data Analysis** | Demand patterns, and **cost-per-resolution ROI** |

### Think Beyond The Hackathon — Make Your Result A Real Service

| Observability | Reliability | Security | Reproducibility |
|---|---|---|---|
| Tracing | Bounded retries | Authentication | Setup instructions |
| Execution records | Safe fallback | Access controls | Versioning |
| Monitoring | Tool failure handling | Data retention | Repeatable evaluation |

**AND BE HONEST ABOUT WHAT'S MISSING**
Capacity limits • Data limitations • Language coverage • Deployment work • Remaining risks

> ↗ **FINAL TAKEAWAY**
> **Build something that works, prove that it works, and know when it should not act.**
> **And show us what it would take to make it real.**

---

## 04. Details

### Event Logistics — Communication!

We will add you to the Hackathon community in **Slack**.

**Recommendations:**
- Keep in touch always with your team!!
- We have some preset Channels, join and explore them!
- We might create additional ones to share specific topics that may help you going through with the challenge
- We've set a technical discussions channel to get you in touch with mentors! **#technical-help**

> **If you don't have a team you can participate by yourself but bear in mind that having a team will greatly improve your results**

### Submission Details

**For your submission to be considered successful you should:**

1. Share the link to your **public\* GitHub Repository** using the following structure:
   `factored-hackathon-2026-[your team's name]`
2. Share a link to where your **tool is deployed**
3. Share a **4 - 6 Slides presentation** with details on your tool
4. A short, **mandatory video pitch** demonstrating the working solution and explaining core architectural decisions.

> **Submit your tool no matter what!!!**

**Submit all of this to: hackathon.admin@factored.ai**

### Event Logistics — Tools & Resources

**You're free to use any language and/or set of tools you deem necessary!**

Some (maybe) valuable resources:
- Microsoft Azure
- Snowflake
- AWS
- Databricks

### Evaluation Criteria

> **First and foremost our solution should work**

- Overall project rationale and documentation
- **AI Engineering:** Backend, Frontend and Deployment
- **Data Analytics:** Data Quality and Providing relevant insights from the solution
- **Data Engineering:** How are you dealing with the Extraction and Transformation of the data
- **Machine Learning:** Model selection, optimization, implementation and tracking

### Code Of Conduct

**We are an inclusive community**

**Violence and discrimination will not be tolerated.**
Remember we do have a code of conduct.

---

## 05. Prizes

| Place | Prize |
|---|---|
| 🥇 **1st** | **US$ 6,000** |
| 🥈 **2nd** | **US$ 3,000** |
| 🥉 **3rd** | **US$ 1,000** |

> **Be interviewed by our engineering & talent team at Factored!**

---

## Happy Coding!
