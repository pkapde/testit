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
    return """<!doctype html><html><head><title>ContractIQ Validator</title>
    <style>body{font-family:system-ui;max-width:720px;margin:48px auto;padding:0 20px}label{display:block;margin-top:18px;font-weight:600}input,select,button{font:inherit;padding:9px;margin-top:6px}button{background:#1167b1;color:white;border:0;border-radius:5px;cursor:pointer}pre{background:#f4f4f4;padding:16px;white-space:pre-wrap}</style>
    </head><body><h1>ContractIQ Document Validator</h1><p>Upload a motor-claim document to test Phase 1 locally.</p>
    <form id=validator><label>Claim ID <input id=claimId value=CLM-001 required></label>
    <label>Expected document type (optional)<select id=expected><option value=''>Detect automatically</option><option value=rc>Registration Certificate (RC)</option><option value=policy>Insurance Policy</option><option value=driving_licence>Driving Licence</option><option value=claim_form>Claim Form</option><option value=fir>FIR / Police Report</option><option value=garage_estimate>Garage Estimate</option><option value=repair_invoice>Repair Invoice</option></select></label>
    <label>Documents <input id=files type=file multiple accept='.txt,.pdf,.jpg,.jpeg,.png' required></label><button>Validate documents</button></form><pre id=result>Result will appear here.</pre>
    <script>document.querySelector('#validator').addEventListener('submit',async event=>{event.preventDefault();const selected=[...files.files];const form=new FormData();selected.forEach(file=>form.append('files',file));if(expected.value)form.append('expected_documents',selected.map(()=>expected.value).join(','));const response=await fetch('/api/v1/claims/'+encodeURIComponent(claimId.value)+'/validate',{method:'POST',body:form});result.textContent=JSON.stringify(await response.json(),null,2)});</script>
    </body></html>"""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
