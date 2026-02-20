# Financial & Revenue Cycle Reports

SQL queries for accounts receivable, claims, payments, charges, and denial tracking. These reports support billing operations, revenue cycle management, and financial analysis.

## Reports

| Report | Description |
|--------|-------------|
| [A/R Aging Summary](ar_aging_summary.md) | Outstanding claim balances grouped into 0–30, 31–60, 61–90, and 90+ day aging buckets |
| [A/R Detail by Patient](ar_detail_by_patient.md) | Each patient's total outstanding balance across all open claims, with last payment date |
| [A/R by Insurance Payer](ar_by_insurance_payer.md) | Outstanding receivables summarized by the insurance company responsible for each claim |
| [A/R by Provider](ar_by_provider.md) | Outstanding receivables grouped by rendering provider |
| [A/R Patient Balance by Queue](ar_patient_balance_by_queue.md) | Patient-responsibility balances broken down by claim workflow queue |
| [Cash Reconciliation](cash_reconciliation.md) | Daily collections vs. amounts posted to claims, broken down by payment method |
| [Claim Details](claim_details.md) | Claim-level detail including CPT codes, ICD-10 diagnoses, and current queue |
| [Claim Payments](claim_payments.md) | Payment amounts per claim with ERA check number references |
| [Claim Payments with Allowed Amounts](claim_payments_allowedamounts.md) | Payments split by patient vs. insurance, with allowed amounts and outstanding balances |
| [Claims Export](claims_export.md) | Comprehensive claim-level detail for export to spreadsheets or external systems |
| [Claims Status](claims_status.md) | Claims grouped by current workflow queue/status with balance breakdowns |
| [Full Chargemaster](full_chargemaster.md) | Complete fee schedule from the Charge Description Master with payer-specific overrides |
| [Monthly Charge Totals](monthly_charge_totals.md) | Rolling 12-month total charges by month of service |
| [Patient Balance](patient_balance.md) | Aggregated patient balances across all qualifying claims |
| [Payment Posting](payment_posting.md) | Every payment posting with payer, method, amounts paid/adjusted/transferred |
| [Remittance Denial Rate](remit_denial_rate.md) | Monthly denial rate based on remittance adjustment codes over a rolling 12-month period |
| [Revenue by CPT Code](revenue_by_cpt_code.md) | Revenue breakdown by procedure code — charges, payments, adjustments, and balance |
| [Revenue by Location](revenue_by_location.md) | Revenue analysis by practice location with provider and patient counts |
| [Revenue by Provider](revenue_by_provider.md) | Provider productivity — charges, payments, patient volume, and avg charge per claim |

## Key Concepts

- **patient_balance** — The computed amount the patient owes after all payments, adjustments, and transfers.
- **aggregate_coverage_balance** — The computed amount insurance still owes on a claim.
- Most reports exclude claims in the **Zero Balance** (fully resolved) and **Trash** (voided/deleted) queues.
- Each report is available as both a `.sql` file (ready to run) and a `.md` file (documented with column descriptions).
