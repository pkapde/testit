# ContractIQ — Phase 1 Document Validator

Local proof of concept for motor-insurance claim document validation. It does **not** approve or reject claims; it identifies missing, invalid, duplicate, wrong, or ambiguous documents for a human claims officer.

## What it checks

- file type and readability
- content-based document classification (never trusts the filename)
- expected-versus-detected document type
- duplicate file contents
- required-document completeness
- `VALID`, `WRONG_DOCUMENT`, `NEEDS_REVIEW`, `UNREADABLE`, and `DUPLICATE` results

The initial classifier is deterministic and explainable, using document-text indicators. It classifies text-based PDFs. A scanned/image-only PDF is returned as `NEEDS_REVIEW` with an OCR requirement; it is not treated as a wrong document. Azure Document Intelligence should replace this fallback in the production IDP pipeline.

## Run locally (PowerShell)

```powershell
$py = 'C:\Users\mital\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m pip install -r requirements.txt
& $py -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/` for a simple local upload page, or `http://127.0.0.1:8000/docs` for API documentation. The API endpoint is `POST /api/v1/claims/{claim_id}/validate`. The multipart form field `expected_documents` is optional and accepts a comma-separated list in the same order as `files`, for example `rc,policy`.

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
