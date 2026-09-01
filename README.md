# ContractIQ — Phase 1 Document Validator

Local proof of concept for motor-insurance claim document validation. It does **not** approve or reject claims; it identifies missing, invalid, duplicate, wrong, or ambiguous documents for a human claims officer.

## What it checks

- file type and readability
- content-based document classification (never trusts the filename)
- expected-versus-detected document type
- duplicate file contents
- required-document completeness
- `VALID`, `WRONG_DOCUMENT`, `NEEDS_REVIEW`, `UNREADABLE`, and `DUPLICATE` results

The classifier is hybrid and explainable. It uses deterministic document-text indicators first. For an image, or for an ambiguous text result, it can call a configured Azure OpenAI vision-capable deployment and require structured JSON output. A low-confidence or unavailable-AI result is routed to `NEEDS_REVIEW`; it is never treated as a valid document by guessing. Azure Document Intelligence provides OCR for scanned PDFs and images in the production IDP pipeline.

## Azure OpenAI fallback for images and ambiguous documents

Copy `.env.example` to `.env` and configure a vision-capable Azure OpenAI deployment:

```text
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=local-development-key-only
AZURE_OPENAI_DEPLOYMENT=your-vision-deployment
AZURE_OPENAI_API_VERSION=2024-10-21
```

When these values are present, Azure OpenAI is used in two controlled places: vision classification for images/ambiguous documents, and schema-constrained field extraction for each readable, classified document. The API response exposes `extraction_method_by_document`: `DETERMINISTIC_PLUS_AZURE_OPENAI` means the model supplied a missing validated field, while `DETERMINISTIC_VERIFIED_BY_AZURE_OPENAI` means it returned successfully but the deterministic extractor already had every usable value. Model output never overwrites a deterministic value and date, amount, registration, and name values are normalised before cross-document validation.

When these values are absent, the application remains fully functional with deterministic classification and extraction. Images and ambiguous documents safely go to manual review. In production, store the key in Azure Key Vault and set `AZURE_OPENAI_API_KEY_SECRET_NAME` rather than providing the key as an environment variable.

## Run locally (PowerShell)

```powershell
$py = 'C:\Users\mital\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m pip install -r requirements.txt
& $py -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/` for a simple local upload page, or `http://127.0.0.1:8000/docs` for API documentation. The API endpoint is `POST /api/v1/claims/{claim_id}/validate`. The multipart form field `expected_documents` is optional and accepts a comma-separated list in the same order as `files`, for example `rc,policy`.

### ClaimShield UI integration

The dedicated Agent 1 UI endpoint is `POST /api/v1/claims/{claim_id}/classification-completeness`. It accepts `multipart/form-data` with a `files` field and optional `expected_documents`, and returns file validation, document classification, duplicate detection, and required-document completeness.

The ClaimShield frontend calls this endpoint during each upload. On submission it sends all selected files to `POST /api/v1/claims/{claim_id}/triage`, which executes Phase 1 plus Phase 2 extraction and consistency routing. Set `VITE_CONTRACTIQ_API_URL=http://127.0.0.1:8001` in the frontend `.env`, and set `CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000` in this backend's `.env` for local development.

## Project layout

```text
app/
  api/v1/routes/      HTTP endpoints and API versioning
  core/               configuration and logging
  schemas/            request/response contracts
  services/           validation and classification business logic
  main.py             application composition
tests/                isolated service tests
```

## Azure and PostgreSQL integration

`POST /api/v1/claims/{claim_id}/ingest` is the production integration route. It uploads original bytes to Azure Blob Storage, performs validation/triage, and writes claim/document/audit metadata to PostgreSQL. Populate the Azure and `DATABASE_URL` values in `.env` before calling it. Do not store source document bytes in PostgreSQL.

## Orchestration and observability

The triage route runs through LangGraph: `validate -> triage -> document verification | claims officer | ready for extraction`. LangSmith tracing is disabled by default. Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, and `LANGSMITH_PROJECT` to emit a sanitized run trace; document bytes and extracted PII are never sent to the trace.

## Phase 2 extraction and cross-document triage

`POST /api/v1/claims/{claim_id}/triage` extracts core structured fields from a valid package: claim and FIR numbers, vehicle registration, owner/claimant name, RC chassis and engine numbers, policy period and IDV, driving-licence validity, and garage estimate/invoice details.

It routes a complete package to `CLAIMS_OFFICER` when it detects any of the following explainable inconsistencies:

- vehicle registration, person name, accident date, or garage-name mismatch;
- accident date outside the policy period;
- driving licence expired on the accident date; or
- invoice/estimate variance greater than `ESTIMATE_INVOICE_VARIANCE_THRESHOLD` (default: 20%).

These are review flags only. They never automatically approve or reject a claim.

It also requires core fields from the mandatory claim form, RC, policy, driving licence, and garage estimate. A missing core field, invalid policy date order, or non-positive estimate is returned in `field_validation_issues` and routed to `DOCUMENT_VERIFICATION`.

When Azure OpenAI is configured, the Cross-Document Validation Agent also makes a schema-constrained semantic review call using extracted fields only (not raw document bytes). It can flag abbreviated-name, claimant/owner, or accident-narrative ambiguities in `agentic_findings`. `INCONSISTENT` and `NEEDS_REVIEW` findings route to `CLAIMS_OFFICER`; the model cannot approve, reject, or override deterministic identifier/date/amount checks.

## Human Review #1 lifecycle

The durable production route (`POST /api/v1/claims/{claim_id}/ingest`) creates a PostgreSQL `review_tasks` record when triage routes a package to `DOCUMENT_VERIFICATION`. Review tasks include the reason, validation evidence, reviewer decision, timestamp, and audit events.

- `GET /api/v1/claims/{claim_id}/reviews` lists tasks for a claim.
- `POST /api/v1/claims/reviews/{task_id}/decision` records `VERIFIED`, `REQUEST_REUPLOAD`, `REJECT_DOCUMENT`, `ESCALATE_FRAUD`, or `OVERRIDE`.

The decision changes the persisted claim state to `READY_FOR_EXTRACTION`, `WAITING_FOR_UPLOAD`, `DOCUMENT_REJECTED`, or `FRAUD_REVIEW`. In production, authentication must supply the reviewer identity; the current local API accepts `reviewer_id` only to exercise the workflow.

## Production secrets and identity

In production, deploy the app with an Azure Managed Identity. Grant it Blob Data Contributor for the claim-document container and Key Vault Secrets User for only the required vault. Configure `AZURE_KEY_VAULT_URL`, `AZURE_STORAGE_ACCOUNT_URL`, and named secret references such as `LANGSMITH_API_KEY_SECRET_NAME`. Local `.env` values remain supported for development only. Never commit a key or connection string.

For production, configure authentication/authorization, a managed object store, malware scanning, Azure OCR/Document Intelligence, a database-backed audit trail, secret management, rate limits, observability, and CI/CD before deployment.

## Test

```powershell
& $py -m pytest -q
```

## Synthetic PDF test pack

Generate eight clearly labelled synthetic PDFs (claim form, RC, policy, driving licence, FIR, garage estimate, repair invoice, and accident-photo placeholder):

```powershell
& $py scripts/generate_synthetic_claim_pack.py
```

The generated files are saved under `sample_data/motor_claim_clm_demo_001/`. They contain no real personal, vehicle, policy, or financial data. Upload them through the local page and select the matching expected document type for each file.

## Supported document types

Claim form, Registration Certificate (RC), insurance policy, driving licence, FIR/police report, garage estimate, repair invoice, and accident photos.
