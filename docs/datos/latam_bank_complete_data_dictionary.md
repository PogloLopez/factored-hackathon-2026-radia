# LATAM Bank Complete Data Dictionary

**Factored Datathon 2026**
Dataset Version 1.0.0

| Attribute | Value |
|---|---|
| **Total Records** | **~19,000,000** |
| **Tables** | **13** |
| **Countries** | Mexico, Colombia, Argentina |
| **Date Range** | June 2023 - June 2026 |
| **Currencies** | MXN, COP, ARS, USD |

Generated: September 2026

---

## Data Access Credentials

The dataset is hosted on **Amazon S3** with **read-only access** for Datathon participants.

> 🔒 **Credentials moved out of this file.** The Bucket Name, Region, Access Key ID, and Secret Access Key now live in the project's `.env` file (see `.env.example` for the required variable names). Copy `.env.example` to `.env` and fill in the real values — `.env` is gitignored and must **never** be committed or shared outside the team.

| Attribute | Value |
|---|---|
| **Bucket Name** | see `.env` → `S3_BUCKET_NAME` |
| **Region** | see `.env` → `AWS_DEFAULT_REGION` |
| **Access Key ID** | see `.env` → `AWS_ACCESS_KEY_ID` |
| **Secret Access Key** | see `.env` → `AWS_SECRET_ACCESS_KEY` |
| **Permissions** | **Read-Only** |

### AWS CLI Configuration

Load the variables from `.env` into your shell, then configure the AWS CLI, e.g.:

```
export $(grep -v '^#' .env | xargs)
aws configure set aws_access_key_id "$AWS_ACCESS_KEY_ID"
aws configure set aws_secret_access_key "$AWS_SECRET_ACCESS_KEY"
aws configure set region "$AWS_DEFAULT_REGION"
```

### Common AWS S3 Commands

**List all available data files:**
```
aws s3 ls s3://$S3_BUCKET_NAME/data/
```

**Download a specific file:**
```
aws s3 cp s3://$S3_BUCKET_NAME/data/customers.csv ./
```

**Sync entire data folder:**
```
aws s3 sync s3://$S3_BUCKET_NAME/data/ ./data/
```

> ⚠️ **Important:** These credentials provide **read-only** access to the dataset. **Do not share these credentials outside of Datathon participants**, and never commit them to git.

---

## Dataset Overview

This dataset simulates a **regional banking system** operating across three Latin American countries: **Mexico, Colombia, and Argentina**. It contains realistic banking, customer service, and digital interaction data spanning **three years** (June 17, 2023 to June 17, 2026).

The dataset includes **19,000,000 records** distributed across **13 tables**, covering customer master data, financial transactions, call center interactions, marketing campaigns, customer complaints, and digital events.

**Languages:** All text data is in **Spanish** with regional variations (Mexican, Colombian, Argentine accents).
**Currencies:** MXN, COP, ARS, USD
**Data Generation:** Synthetically generated for the Factored Datathon 2026.

### Data Quality Characteristics

This dataset **intentionally includes real-world data quality challenges**:
- **Duplicate Records:** ~2% across tables
- **Null Values:** ~5% in nullable fields
- **Late Arrivals:** Some partitioned data may arrive late
- **Schema Evolution:** Table schemas may change over time

---

## Dimension Tables

Reference data tables containing 5 dimension tables.

### Customers [DIMENSION]
**Rows:** 150,000 | **Source:** Core Banking | **Partition:** monthly_snapshot

Bank customer dimension table

| Column | Type | Description | Constraints |
|---|---|---|---|
| **customer_id** | VARCHAR(20) | Unique customer ID | **PK, NOT NULL** |
| document_number | VARCHAR(20) | Identity document number | NOT NULL, UNIQUE |
| document_type | VARCHAR(10) | Document type (DNI, CURP, CC, CE, Passport) | NOT NULL |
| first_name | VARCHAR(100) | Customer first name (in Spanish) | NOT NULL |
| last_name | VARCHAR(100) | Customer last name (in Spanish) | NOT NULL |
| date_of_birth | DATE | Date of birth | NOT NULL |
| gender | VARCHAR(1) | Gender (M, F, O) | - |
| email | VARCHAR(100) | Email address | - |
| mobile_phone | VARCHAR(20) | Mobile phone number | - |
| landline_phone | VARCHAR(20) | Landline phone number | - |
| address | VARCHAR(200) | Full address (in Spanish) | - |
| city | VARCHAR(100) | City of residence | NOT NULL |
| state | VARCHAR(100) | State/Province | NOT NULL |
| country | VARCHAR(50) | Country (Mexico, Colombia, Argentina) | NOT NULL |
| postal_code | VARCHAR(10) | Postal code | - |
| detected_accent | VARCHAR(50) | Spanish accent detected (mexican, colombian, argentine, neutral) | - |
| **segment** | VARCHAR(50) | Customer segment (Premium, Plus, Basic, Student) | NOT NULL |
| **credit_score** | INTEGER | Credit score (300-850) | - |
| estimated_monthly_income | DECIMAL(12,2) | Estimated monthly income in local currency | - |
| occupation | VARCHAR(100) | Customer occupation | - |
| marital_status | VARCHAR(20) | Marital status | - |
| education_level | VARCHAR(50) | Education level | - |
| registration_date | TIMESTAMP | Registration date as customer | NOT NULL |
| registration_branch_id | VARCHAR(20) | Branch ID where registered | FK, NOT NULL |
| **customer_status** | VARCHAR(20) | Status (Active, Inactive, Suspended, Closed) | NOT NULL |
| last_updated | TIMESTAMP | Last record update | NOT NULL |
| accepts_marketing | BOOLEAN | Accepts marketing communications | NOT NULL |

### Products [DIMENSION]
**Rows:** 400,000 | **Source:** Core Banking | **Partition:** monthly_snapshot

Active financial products of customers

| Column | Type | Description | Constraints |
|---|---|---|---|
| **product_id** | VARCHAR(20) | Unique product ID | **PK, NOT NULL** |
| **customer_id** | VARCHAR(20) | Owner customer ID | **FK, NOT NULL** |
| **product_type** | VARCHAR(50) | Product type (Checking Account, Savings Account, Credit Card, Debit Card, Personal Loan, Mortgage, Investment...) | NOT NULL |
| product_number | VARCHAR(30) | Account/card/policy number | NOT NULL, UNIQUE |
| currency | VARCHAR(3) | Currency (MXN, COP, ARS, USD) | NOT NULL |
| **current_balance** | DECIMAL(15,2) | Current balance | NOT NULL |
| credit_limit | DECIMAL(15,2) | Credit limit (for credit products) | - |
| interest_rate | DECIMAL(5,2) | Annual interest rate (%) | - |
| opening_date | DATE | Product opening date | NOT NULL |
| expiration_date | DATE | Expiration date (for term products) | - |
| opening_branch_id | VARCHAR(20) | Branch where opened | FK, NOT NULL |
| **product_status** | VARCHAR(20) | Status (Active, Blocked, Closed, Suspended) | NOT NULL |
| opening_channel | VARCHAR(30) | Opening channel (Branch, Web, App, Call Center) | NOT NULL |
| has_linked_app | BOOLEAN | Product linked to mobile app | NOT NULL |
| **days_past_due** | INTEGER | Days past due (for credits) | - |
| last_transaction_date | TIMESTAMP | Last transaction date | - |
| last_updated | TIMESTAMP | Last record update | NOT NULL |

### Branches [DIMENSION]
**Rows:** 350 | **Source:** Internal | **Partition:** full_snapshot

Physical bank branches

| Column | Type | Description | Constraints |
|---|---|---|---|
| **branch_id** | VARCHAR(20) | Unique branch ID | **PK, NOT NULL** |
| branch_code | VARCHAR(10) | Internal branch code | NOT NULL, UNIQUE |
| branch_name | VARCHAR(100) | Branch name | NOT NULL |
| branch_type | VARCHAR(30) | Type (Main, Express, Premium, Corporate) | NOT NULL |
| address | VARCHAR(200) | Full address (in Spanish) | NOT NULL |
| city | VARCHAR(100) | City | NOT NULL |
| state | VARCHAR(100) | State/Province | NOT NULL |
| country | VARCHAR(50) | Country | NOT NULL |
| postal_code | VARCHAR(10) | Postal code | - |
| geographic_zone | VARCHAR(50) | Zone (Urban, Suburban, Rural) | NOT NULL |
| phone | VARCHAR(20) | Contact phone | NOT NULL |
| email | VARCHAR(100) | Branch email | - |
| opening_time | TIME | Opening time | NOT NULL |
| closing_time | TIME | Closing time | NOT NULL |
| has_atms | BOOLEAN | Has ATMs | NOT NULL |
| atm_count | INTEGER | Number of ATMs | - |
| has_teller_windows | BOOLEAN | Has teller windows | NOT NULL |
| teller_window_count | INTEGER | Number of teller windows | - |
| latitude | DECIMAL(10,7) | Geographic latitude | - |
| longitude | DECIMAL(10,7) | Geographic longitude | - |
| branch_opening_date | DATE | Branch opening date | NOT NULL |
| branch_status | VARCHAR(20) | Status (Active, Temporarily Closed, Closed) | NOT NULL |

### Service Agents [DIMENSION]
**Rows:** 1,200 | **Source:** Internal | **Partition:** monthly_snapshot

Customer service agents

| Column | Type | Description | Constraints |
|---|---|---|---|
| **agent_id** | VARCHAR(20) | Unique agent ID | **PK, NOT NULL** |
| employee_code | VARCHAR(15) | Employee code | NOT NULL, UNIQUE |
| first_name | VARCHAR(100) | Agent first name (in Spanish) | NOT NULL |
| last_name | VARCHAR(100) | Agent last name (in Spanish) | NOT NULL |
| email | VARCHAR(100) | Corporate email | NOT NULL |
| phone | VARCHAR(20) | Contact phone | - |
| native_accent | VARCHAR(50) | Native Spanish accent (mexican, colombian, argentine) | NOT NULL |
| country_of_origin | VARCHAR(50) | Country of origin | NOT NULL |
| assigned_branch_id | VARCHAR(20) | Assigned branch | FK |
| agent_type | VARCHAR(30) | Type (Phone, In-Person, Digital, Hybrid) | NOT NULL |
| experience_level | VARCHAR(20) | Level (Junior, Mid-Senior, Senior, Specialist) | NOT NULL |
| languages | VARCHAR(100) | Languages spoken | NOT NULL |
| specialty | VARCHAR(100) | Specialty | - |
| hire_date | DATE | Hire date | NOT NULL |
| **avg_csat** | DECIMAL(3,2) | Average CSAT score (1-5) | - |
| total_monthly_interactions | INTEGER | Total interactions in last month | - |
| agent_status | VARCHAR(20) | Status (Active, Vacation, Leave, Inactive) | NOT NULL |
| work_shift | VARCHAR(20) | Shift (Morning, Afternoon, Night, Rotating) | NOT NULL |

### Marketing Campaigns [DIMENSION]
**Rows:** 200 | **Source:** Internal | **Partition:** full_snapshot

Bank marketing campaigns

| Column | Type | Description | Constraints |
|---|---|---|---|
| **campaign_id** | VARCHAR(20) | Unique campaign ID | **PK, NOT NULL** |
| campaign_name | VARCHAR(150) | Campaign name | NOT NULL |
| description | TEXT | Campaign description | - |
| campaign_type | VARCHAR(50) | Type (Email, SMS, Push, WhatsApp, Voice, Mix) | NOT NULL |
| campaign_objective | VARCHAR(100) | Objective (Acquisition, Retention, Cross-sell, Up-sell, Reactivation) | NOT NULL |
| promoted_product | VARCHAR(50) | Promoted product | - |
| target_segment | VARCHAR(50) | Target segment | - |
| target_country | VARCHAR(50) | Target country | - |
| start_date | DATE | Start date | NOT NULL |
| end_date | DATE | End date | NOT NULL |
| budget | DECIMAL(12,2) | Assigned budget | - |
| campaign_status | VARCHAR(20) | Status (Planned, Active, Paused, Completed) | NOT NULL |
| expected_conversion_rate | DECIMAL(5,2) | Expected conversion rate (%) | - |

---

## Fact Tables

Transactional and event data tables containing 7 fact tables.

### Transactions [FACT]
**Rows:** 5,000,000 | **Source:** Core Banking | **Partition:** daily

Daily financial transactions

| Column | Type | Description | Constraints |
|---|---|---|---|
| **transaction_id** | VARCHAR(30) | Unique transaction ID | **PK, NOT NULL** |
| transaction_date | TIMESTAMP | Transaction date and time | NOT NULL |
| process_date | DATE | Process date (partition key) | NOT NULL |
| **product_id** | VARCHAR(20) | Product ID | FK, NOT NULL |
| **customer_id** | VARCHAR(20) | Customer ID | FK, NOT NULL |
| **transaction_type** | VARCHAR(50) | Type (Deposit, Withdrawal, Transfer, Payment, Purchase, Adjustment) | NOT NULL |
| transaction_category | VARCHAR(50) | Category (Food, Transport, Services, Entertainment, Health, Other) | - |
| **amount** | DECIMAL(15,2) | Transaction amount | NOT NULL |
| currency | VARCHAR(3) | Currency | NOT NULL |
| amount_usd | DECIMAL(15,2) | Amount converted to USD | - |
| channel | VARCHAR(30) | Channel (ATM, Branch, Web, App, POS, Transfer) | NOT NULL |
| branch_id | VARCHAR(20) | Branch ID (if applicable) | FK |
| merchant_name | VARCHAR(150) | Merchant name (for purchases) | - |
| merchant_category | VARCHAR(50) | MCC merchant category | - |
| transaction_country | VARCHAR(50) | Country where transaction occurred | NOT NULL |
| transaction_city | VARCHAR(100) | City where transaction occurred | - |
| **transaction_status** | VARCHAR(20) | Status (Approved, Declined, Pending, Reversed) | NOT NULL |
| response_code | VARCHAR(10) | System response code | - |
| **is_fraud** | BOOLEAN | Marked as fraud | NOT NULL |
| **fraud_score** | DECIMAL(5,2) | Fraud risk score (0-100) | - |
| latitude | DECIMAL(10,7) | Transaction latitude | - |
| longitude | DECIMAL(10,7) | Transaction longitude | - |

### Call Center Interactions [FACT]
**Rows:** 800,000 | **Source:** Contact Center | **Partition:** daily

Call center interactions with customers

| Column | Type | Description | Constraints |
|---|---|---|---|
| **interaction_id** | VARCHAR(30) | Unique interaction ID | **PK, NOT NULL** |
| interaction_date | TIMESTAMP | Interaction date and time | NOT NULL |
| process_date | DATE | Process date (partition key) | NOT NULL |
| **customer_id** | VARCHAR(20) | Customer ID | FK, NOT NULL |
| agent_id | VARCHAR(20) | Agent ID who attended | FK |
| interaction_type | VARCHAR(30) | Type (Inbound Call, Outbound Call, Chat, Email, Video) | NOT NULL |
| channel | VARCHAR(30) | Channel (Phone, Web Chat, WhatsApp, Email, App) | NOT NULL |
| **contact_reason** | VARCHAR(100) | Main contact reason | NOT NULL |
| **reason_category** | VARCHAR(50) | Category (Transactional, Product, Technical, Commercial, Complaint) | NOT NULL |
| duration_seconds | INTEGER | Duration in seconds | - |
| wait_time_seconds | INTEGER | Wait time before service | - |
| **was_resolved** | BOOLEAN | Resolved on first call (FCR) | - |
| requires_followup | BOOLEAN | Requires follow-up | NOT NULL |
| **detected_sentiment** | VARCHAR(20) | Sentiment (Positive, Neutral, Negative, Very Negative) | - |
| sentiment_score | DECIMAL(3,2) | Sentiment score (-1 to 1) | - |
| customer_detected_accent | VARCHAR(50) | Customer's detected accent | - |
| agent_used_accent | VARCHAR(50) | Accent used by agent in response | - |
| **was_escalated** | BOOLEAN | Was escalated to supervisor | NOT NULL |
| mentioned_products | VARCHAR(200) | Product IDs mentioned (comma-separated) | - |
| has_transcript | BOOLEAN | Has transcript available | NOT NULL |
| has_recording | BOOLEAN | Has audio recording | NOT NULL |

### Call Transcripts [FACT]
**Rows:** 200,000 | **Source:** Contact Center | **Partition:** daily

Call center call transcripts

| Column | Type | Description | Constraints |
|---|---|---|---|
| **transcript_id** | VARCHAR(30) | Unique transcript ID | **PK, NOT NULL** |
| interaction_id | VARCHAR(30) | Related interaction ID | FK, NOT NULL |
| process_date | DATE | Process date (partition key) | NOT NULL |
| customer_id | VARCHAR(20) | Customer ID | FK, NOT NULL |
| agent_id | VARCHAR(20) | Agent ID | FK, NOT NULL |
| **full_text** | TEXT | Full call transcript (in Spanish) | NOT NULL |
| customer_text | TEXT | Only what customer said (in Spanish) | - |
| agent_text | TEXT | Only what agent said (in Spanish) | - |
| detected_language | VARCHAR(10) | Main language detected | NOT NULL |
| detected_accent | VARCHAR(50) | Detected accent | - |
| accent_confidence | DECIMAL(3,2) | Accent detection confidence (0-1) | - |
| detected_keywords | VARCHAR(500) | Identified keywords | - |
| mentioned_entities | TEXT | Extracted entities (JSON) | - |
| **detected_intents** | VARCHAR(300) | Identified intents | - |
| main_topics | VARCHAR(300) | Main conversation topics | - |
| transcription_model | VARCHAR(50) | Model used (Whisper, Google STT, etc.) | NOT NULL |
| audio_quality | VARCHAR(20) | Audio quality (High, Medium, Low) | - |
| duration_seconds | INTEGER | Call duration | NOT NULL |

### Satisfaction Surveys [FACT]
**Rows:** 250,000 | **Source:** Contact Center | **Partition:** daily

Post-interaction satisfaction surveys (CSAT, NPS)

| Column | Type | Description | Constraints |
|---|---|---|---|
| **survey_id** | VARCHAR(30) | Unique survey ID | **PK, NOT NULL** |
| survey_date | TIMESTAMP | Response date and time | NOT NULL |
| process_date | DATE | Process date (partition key) | NOT NULL |
| interaction_id | VARCHAR(30) | Evaluated interaction ID | FK |
| customer_id | VARCHAR(20) | Customer ID | FK, NOT NULL |
| agent_id | VARCHAR(20) | Evaluated agent ID | FK |
| **survey_type** | VARCHAR(20) | Type (CSAT, NPS, CES) | NOT NULL |
| send_channel | VARCHAR(30) | Send channel (Email, SMS, IVR, App, Web) | NOT NULL |
| **main_score** | INTEGER | Main score (1-5 for CSAT, 0-10 for NPS) | NOT NULL |
| nps_category | VARCHAR(20) | NPS category (Promoter, Passive, Detractor) | - |
| question_1_text | TEXT | Question 1 text | - |
| question_1_response | INTEGER | Question 1 response (1-5) | - |
| question_2_text | TEXT | Question 2 text | - |
| question_2_response | INTEGER | Question 2 response (1-5) | - |
| question_3_text | TEXT | Question 3 text | - |
| question_3_response | INTEGER | Question 3 response (1-5) | - |
| open_comments | TEXT | Customer comments (in Spanish) | - |
| comment_sentiment | VARCHAR(20) | Comment sentiment | - |
| response_time_hours | DECIMAL(8,2) | Hours between interaction and response | - |
| campaign_response_rate | DECIMAL(5,2) | Campaign response rate (%) | - |

### Digital Events [FACT]
**Rows:** 10,000,000 | **Source:** Digital Banking | **Partition:** daily

Digital channel interaction events (mobile app, web)

| Column | Type | Description | Constraints |
|---|---|---|---|
| **event_id** | VARCHAR(30) | Unique event ID | **PK, NOT NULL** |
| event_date | TIMESTAMP | Event date and time | NOT NULL |
| process_date | DATE | Process date (partition key) | NOT NULL |
| customer_id | VARCHAR(20) | Customer ID | FK |
| session_id | VARCHAR(50) | User session ID | NOT NULL |
| **event_type** | VARCHAR(50) | Type (PageView, Click, FormSubmit, Login, Logout, Error, Purchase) | NOT NULL |
| event_category | VARCHAR(50) | Category (Navigation, Transaction, Authentication, Product) | NOT NULL |
| channel | VARCHAR(30) | Channel (Android App, iOS App, Desktop Web, Mobile Web) | NOT NULL |
| platform | VARCHAR(30) | Platform (Android, iOS, Windows, MacOS, Linux) | - |
| browser | VARCHAR(50) | Browser used | - |
| app_version | VARCHAR(20) | App version | - |
| page_url | VARCHAR(300) | Page URL | - |
| page_title | VARCHAR(200) | Page title | - |
| action | VARCHAR(100) | Action performed | - |
| element_id | VARCHAR(100) | Interacted element ID | - |
| product_id | VARCHAR(20) | Related product ID | FK |
| event_value | DECIMAL(15,2) | Event monetary value (if applicable) | - |
| duration_seconds | INTEGER | Event duration | - |
| ip_address | VARCHAR(45) | User IP address | - |
| ip_country | VARCHAR(50) | Country detected by IP | - |
| ip_city | VARCHAR(100) | City detected by IP | - |
| is_mobile | BOOLEAN | Event from mobile device | NOT NULL |
| referrer | VARCHAR(300) | Referrer URL | - |
| utm_source | VARCHAR(100) | UTM source | - |
| utm_medium | VARCHAR(100) | UTM medium | - |
| utm_campaign | VARCHAR(100) | UTM campaign | - |

### Complaints [FACT]
**Rows:** 80,000 | **Source:** PQR | **Partition:** daily

Complaints and claims system (PQR)

| Column | Type | Description | Constraints |
|---|---|---|---|
| **complaint_id** | VARCHAR(30) | Unique complaint/claim ID | **PK, NOT NULL** |
| creation_date | TIMESTAMP | Complaint creation date | NOT NULL |
| process_date | DATE | Process date (partition key) | NOT NULL |
| customer_id | VARCHAR(20) | Customer ID | FK, NOT NULL |
| **case_type** | VARCHAR(30) | Type (Complaint, Claim, Request, Suggestion) | NOT NULL |
| **category** | VARCHAR(100) | Case category | NOT NULL |
| subcategory | VARCHAR(100) | Subcategory | - |
| reception_channel | VARCHAR(30) | Channel (Call Center, Email, Web, App, Branch, Regulator) | NOT NULL |
| affected_product_id | VARCHAR(20) | Affected product ID | FK |
| related_branch_id | VARCHAR(20) | Related branch ID | FK |
| origin_interaction_id | VARCHAR(30) | Originating interaction ID | FK |
| description | TEXT | Case description (in Spanish) | NOT NULL |
| claimed_amount | DECIMAL(15,2) | Claimed amount (if applicable) | - |
| currency | VARCHAR(3) | Claimed amount currency | - |
| **priority** | VARCHAR(20) | Priority (Low, Medium, High, Critical) | NOT NULL |
| **status** | VARCHAR(30) | Status (Open, In Process, Escalated, Resolved, Closed, Rejected) | NOT NULL |
| assigned_agent_id | VARCHAR(20) | Assigned agent ID | FK |
| assignment_date | TIMESTAMP | Assignment date | - |
| first_response_date | TIMESTAMP | First response date | - |
| resolution_date | TIMESTAMP | Resolution date | - |
| closing_date | TIMESTAMP | Closing date | - |
| **sla_breached** | BOOLEAN | SLA breached | NOT NULL |
| resolution_days | INTEGER | Days to resolution | - |
| resolution | TEXT | Resolution description (in Spanish) | - |
| compensation_granted | DECIMAL(15,2) | Compensation amount granted | - |
| resolution_satisfaction | INTEGER | Resolution satisfaction score (1-5) | - |
| **is_repeat_complainer** | BOOLEAN | Customer with previous complaints in last 90 days | NOT NULL |

### Campaign Sends [FACT]
**Rows:** 2,000,000 | **Source:** Internal | **Partition:** daily

Individual marketing campaign sends

| Column | Type | Description | Constraints |
|---|---|---|---|
| **send_id** | VARCHAR(30) | Unique send ID | **PK, NOT NULL** |
| send_date | TIMESTAMP | Send date and time | NOT NULL |
| process_date | DATE | Process date (partition key) | NOT NULL |
| campaign_id | VARCHAR(20) | Campaign ID | FK, NOT NULL |
| customer_id | VARCHAR(20) | Recipient customer ID | FK, NOT NULL |
| send_channel | VARCHAR(30) | Channel (Email, SMS, Push, WhatsApp, Voice) | NOT NULL |
| template_used | VARCHAR(100) | Template used | - |
| subject | VARCHAR(200) | Message subject | - |
| send_status | VARCHAR(20) | Status (Sent, Failed, Bounced, Blocked) | NOT NULL |
| was_delivered | BOOLEAN | Was delivered successfully | NOT NULL |
| was_opened | BOOLEAN | Was opened/read | - |
| open_date | TIMESTAMP | Open date | - |
| was_clicked | BOOLEAN | Clicked on any link | - |
| click_date | TIMESTAMP | First click date | - |
| click_count | INTEGER | Total click count | - |
| **had_conversion** | BOOLEAN | Converted (completed desired action) | NOT NULL |
| conversion_date | TIMESTAMP | Conversion date | - |
| conversion_value | DECIMAL(15,2) | Conversion monetary value | - |
| open_device | VARCHAR(30) | Device used to open | - |
| open_country | VARCHAR(50) | Country where opened | - |
| failure_reason | VARCHAR(200) | Failure reason (if applicable) | - |
| send_cost | DECIMAL(10,4) | Individual send cost | - |

---

## Reference Tables

Reference data for lookups and conversions.

### Daily Exchange Rates [REFERENCE]
**Rows:** 3,000 | **Source:** Reference | **Partition:** daily

Daily exchange rates for currency conversion

| Column | Type | Description | Constraints |
|---|---|---|---|
| **date** | DATE | Exchange rate date | **PK, NOT NULL** |
| **source_currency** | VARCHAR(3) | Source currency | **PK, NOT NULL** |
| **target_currency** | VARCHAR(3) | Target currency | **PK, NOT NULL** |
| exchange_rate | DECIMAL(12,6) | Exchange rate | NOT NULL |
| buy_rate | DECIMAL(12,6) | Bank buy rate | - |
| sell_rate | DECIMAL(12,6) | Bank sell rate | - |
| source | VARCHAR(50) | Exchange rate source | - |

---

## Foreign Key Relationships

The following foreign key relationships exist between tables:

**customers**
- products.customer_id → customers.customer_id
- transactions.customer_id → customers.customer_id
- call_center_interactions.customer_id → customers.customer_id
- call_transcripts.customer_id → customers.customer_id
- satisfaction_surveys.customer_id → customers.customer_id
- digital_events.customer_id → customers.customer_id
- complaints.customer_id → customers.customer_id
- campaign_sends.customer_id → customers.customer_id

**branches**
- customers.registration_branch_id → branches.branch_id
- products.opening_branch_id → branches.branch_id
- service_agents.assigned_branch_id → branches.branch_id
- transactions.branch_id → branches.branch_id
- complaints.related_branch_id → branches.branch_id

**service_agents**
- call_center_interactions.agent_id → service_agents.agent_id
- call_transcripts.agent_id → service_agents.agent_id
- satisfaction_surveys.agent_id → service_agents.agent_id
- complaints.assigned_agent_id → service_agents.agent_id

**products**
- transactions.product_id → products.product_id
- digital_events.product_id → products.product_id
- complaints.affected_product_id → products.product_id

**marketing_campaigns**
- campaign_sends.campaign_id → marketing_campaigns.campaign_id

**call_center_interactions**
- call_transcripts.interaction_id → call_center_interactions.interaction_id
- satisfaction_surveys.interaction_id → call_center_interactions.interaction_id
- complaints.origin_interaction_id → call_center_interactions.interaction_id

---

## Potential Use Cases

### Customer Analytics
- Customer segmentation and clustering
- **Churn prediction models**
- Customer lifetime value (CLV) analysis
- Cross-sell and up-sell opportunity identification

### Contact Center Optimization
- **First Call Resolution (FCR) improvement**
- Agent performance analysis
- Sentiment trend analysis
- Accent-based routing optimization

### Fraud Detection
- **Transaction fraud detection models**
- Anomaly detection in spending patterns
- Geographic risk modeling

### Marketing Analytics
- Campaign effectiveness measurement
- Channel attribution modeling
- Personalization models
- A/B testing analysis

### NLP / Text Analytics
- Topic modeling on call transcripts
- **Intent classification**
- Entity extraction
- Multilingual accent detection

---

## Important Notes

- **Spanish Language Data:** All text data is in Spanish with regional variations.
- **Accent Detection:** Dataset includes Mexican, Colombian, and Argentine accent fields.
- **Multi-Currency:** Transactions include local currency and USD conversion.
- **Date Partitioning:** Large fact tables partitioned by year/month/day.
- **Synthetic Data:** Completely synthetic - no real customer information.
- **Referential Integrity:** FK relationships maintained (small % of orphans for testing).

Factored Datathon 2026
Dataset Version 1.0.0
For questions, contact the Factored Datathon team
