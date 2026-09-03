from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.infrastructure.postgres import initialize_database
    initialize_database()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", description="Motor claim document validator", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(api_router)


def custom_openapi() -> dict:
    """Make multi-file fields render as file pickers in Swagger UI."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    for component in schema.get("components", {}).get("schemas", {}).values():
        files = component.get("properties", {}).get("files")
        items = files.get("items", {}) if files else {}
        if items.get("contentMediaType"):
            items["format"] = "binary"
            items.pop("contentMediaType", None)
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def test_page() -> str:
    return """<!doctype html><html><head><title>ContractIQ Validator & Gemini Classifier</title>
    <style>body{font-family:system-ui;max-width:800px;margin:48px auto;padding:0 20px}label{display:block;margin-top:18px;font-weight:600}input,select,button{font:inherit;padding:9px;margin-top:6px}button{background:#1167b1;color:white;border:0;border-radius:5px;cursor:pointer}pre{background:#f4f4f4;padding:16px;white-space:pre-wrap;border-radius:5px}hr{margin:36px 0;border:0;border-top:1px solid #ccc}</style>
    </head><body><h1>ContractIQ Document Validator & Gemini Classifier</h1>
    <p><strong>API Documentation:</strong> <a href="/docs" target="_blank">Interactive Swagger UI (/docs)</a> | <a href="/redoc" target="_blank">ReDoc (/redoc)</a></p>
    <section><h2>Gemini AI Document Classifier (POST /api/v1/claims/classification)</h2>
    <form id=geminiClassifier><label>Category Type <select id=categoryType required>
    <option value=survey_report>Survey Report Motor Insurance</option>
    <option value=repair_invoice>Repair Invoice</option>
    <option value=repair_estimate>Repair Estimate Details</option>
    <option value=insurance_policy>Insurance Policy</option>
    <option value=claim_form>Claim Form</option>
    <option value=registration_certificate>Registration Certificate (RC)</option>
    <option value=driving_licence>Driver Licence</option>
    <option value=accident_photos>Car Pic Four Side</option>
    </select></label>
    <label>Upload Document / Image(s) <input id=classifyFiles type=file multiple accept='.pdf,.jpg,.jpeg,.png,.webp,.txt' required></label>
    <button type=submit>Classify with Gemini</button></form>
    <pre id=classifyResult>Classification result will appear here.</pre></section>
    <hr>
    <section><h2>Claim Package Validator (Phase 1)</h2>
    <form id=validator><label>Claim ID <input id=claimId value=CLM-001 required></label>
    <label>Expected document type (optional)<select id=expected><option value=''>Detect automatically</option><option value=rc>Registration Certificate (RC)</option><option value=policy>Insurance Policy</option><option value=driving_licence>Driving Licence</option><option value=claim_form>Claim Form</option><option value=fir>FIR / Police Report</option><option value=garage_estimate>Garage Estimate</option><option value=repair_invoice>Repair Invoice</option></select></label>
    <label>Documents <input id=files type=file multiple accept='.txt,.pdf,.jpg,.jpeg,.png' required></label><button>Validate documents</button></form>
    <pre id=result>Result will appear here.</pre></section>
    <script>
    document.querySelector('#geminiClassifier').addEventListener('submit',async event=>{
        event.preventDefault();
        const selected=[...classifyFiles.files];
        const form=new FormData();
        form.append('category_type',categoryType.value);
        selected.forEach(file=>form.append('files',file));
        classifyResult.textContent='Classifying with Gemini AI...';
        const response=await fetch('/api/v1/claims/classification',{method:'POST',body:form});
        classifyResult.textContent=JSON.stringify(await response.json(),null,2);
    });
    document.querySelector('#validator').addEventListener('submit',async event=>{
        event.preventDefault();
        const selected=[...files.files];
        const form=new FormData();
        selected.forEach(file=>form.append('files',file));
        if(expected.value)form.append('expected_documents',selected.map(()=>expected.value).join(','));
        const response=await fetch('/api/v1/claims/'+encodeURIComponent(claimId.value)+'/validate',{method:'POST',body:form});
        result.textContent=JSON.stringify(await response.json(),null,2);
    });
    </script>
    </body></html>"""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
