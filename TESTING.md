# ContractIQ Backend Testing Guide

This guide verifies the implemented backend workflow from document intake through Claims Adjuster review. It is safe to use with the synthetic document pack included in this repository.

## 1. Prerequisites

Run the commands from the repository root in PowerShell.

```powershell
$py = 'C:\Users\mital\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`. For a local deterministic test, leave Azure, Blob Storage, and PostgreSQL values empty. Do not add real keys to a committed file.

## 2. Start the API

```powershell
& $py -m uvicorn app.main:app --reload --port 8001
```

Verify the health endpoint at `http://127.0.0.1:8001/health`. It must return:

```json
{"status":"ok"}
```

Open Swagger UI at `http://127.0.0.1:8001/docs`.

## 3. Test the Complete Automated Workflow

In Swagger, open `POST /api/v1/claims/{claim_id}/triage`, select **Try it out**, and use `CLM-DEMO-001` as the claim ID.

Upload these files from `sample_data/motor_claim_clm_demo_001/`:

- `01_claim_form.pdf`
- `02_registration_certificate_rc.pdf`
- `03_insurance_policy.pdf`
- `04_driving_licence.pdf`
- `05_fir_police_report.pdf`
- `06_garage_estimate.pdf`
- `07_repair_invoice.pdf`
- `08_accident_photos_placeholder.pdf`

Do not upload `05_fir_police_report - Copy.pdf`; it is an intentional duplicate test file.

Click **Execute**. A successful request returns HTTP `200` and includes these response sections:

- `validation` — document classification, duplicates, readability, and completeness.
- `extracted_fields` — structured fields used for checks.
- `cross_document_issues` and `agentic_findings` — deterministic and LLM-assisted review evidence.
- `fraud_risk_level` and `fraud_findings` — explainable risk indicators.
- `coverage_decision` and `coverage_findings` — policy-rule assessment.
- `assessment` and `settlement_recommendation` — Claims Adjuster decision-support material.
- `routing_queue` and `routing_reason` — reason the claim is routed to the single Claims Adjuster.

The local route runs the following LangGraph sequence:

```text
Validation -> Triage/Extraction -> Fraud -> Coverage -> Assessment -> Settlement Recommendation -> Claims Adjuster Review
```

`NEEDS_REVIEW` or `CLAIMS_OFFICER` is a safe valid outcome. This POC never auto-approves or auto-rejects a claim.

## 4. Test Individual APIs

| Goal | Swagger route |
| --- | --- |
| Classification and completeness only | `POST /api/v1/claims/{claim_id}/classification-completeness` |
| UI classification endpoint | `POST /api/v1/claims/classification` |
| Complete automated workflow | `POST /api/v1/claims/{claim_id}/triage` |
| Policy wording enquiry | `POST /api/v1/policy/enquiry` |

## 5. Test Azure Blob Storage and PostgreSQL

Configure these values in the local `.env` file:

```text
AZURE_STORAGE_CONNECTION_STRING=<storage-connection-string>
AZURE_STORAGE_CONTAINER=claim-documents
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<database>
```

Restart the API. In Swagger, call `POST /api/v1/claims/{claim_id}/ingest` with the same eight files. This route uploads original documents to Blob Storage, runs the workflow, and writes claim metadata, audit events, and one Claims Adjuster task to PostgreSQL.

Verify the task with:

```text
GET /api/v1/claims/CLM-DEMO-001/reviews
```

Use the returned `task_id` to resolve the task through `POST /api/v1/claims/reviews/{task_id}/decision`:

```json
{
  "action": "APPROVE_FOR_SETTLEMENT",
  "reviewer_id": "adjuster.demo",
  "comment": "Demo review completed after checking automated evidence."
}
```

## 6. Test Azure OpenAI and Document Intelligence

Add the Azure configuration only to `.env`:

```text
AZURE_OPENAI_ENDPOINT=https://<resource-name>.openai.azure.com
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_DEPLOYMENT=<deployment-name>
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<resource-name>.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=<key>
```

Restart the API and run the triage test again. The response can show Azure-enhanced extraction methods and LLM-assisted findings. A provider failure must safely fall back to deterministic processing and must never mark a claim approved.

## 7. Run Automated Tests

```powershell
& $py -m pytest -q
```

Before raising a pull request or demoing the build, confirm that all tests pass, `/health` returns HTTP `200`, `/triage` returns HTTP `200`, and `/ingest` creates both Blob objects and a PostgreSQL review task when cloud services are configured.
