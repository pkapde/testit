"""Create the ContractIQ Phase 1 implementation guide PDF."""
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

OUTPUT = Path("output/pdf/contractiq_phase_1_document_validator_guide.pdf")
NAVY = colors.HexColor("#17365D")
BLUE = colors.HexColor("#1F6FB2")
PALE = colors.HexColor("#F3F7FB")
GREEN = colors.HexColor("#D9EAD3")
AMBER = colors.HexColor("#FCE5CD")
RED = colors.HexColor("#F4CCCC")


def build_styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=27, leading=33, textColor=NAVY, spaceAfter=8),
        "subtitle": ParagraphStyle("subtitle", parent=styles["BodyText"], fontSize=13, leading=19, textColor=colors.HexColor("#4E6173")),
        "h1": ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=19, leading=24, textColor=NAVY, spaceBefore=10, spaceAfter=9),
        "h2": ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=BLUE, spaceBefore=10, spaceAfter=5),
        "body": ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=15, spaceAfter=6),
        "small": ParagraphStyle("small", parent=styles["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#4E6173")),
        "table_header": ParagraphStyle("table_header", parent=styles["BodyText"], fontSize=8.5, leading=11, textColor=colors.white),
        "code": ParagraphStyle("code", parent=styles["Code"], fontName="Courier", fontSize=8.4, leading=12, backColor=colors.HexColor("#F1F3F5"), borderPadding=7, spaceBefore=4, spaceAfter=8),
        "center": ParagraphStyle("center", parent=styles["BodyText"], alignment=TA_CENTER, fontSize=10, leading=14),
    }


def p(text, style):
    return Paragraph(text, style)


def table(rows, widths, header=True, fill=PALE):
    rendered = [[p(cell, ST["body"] if row else ST["table_header"]) for cell in record] for row, record in enumerate(rows)]
    t = Table(rendered, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C4D3E2")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]
    if header:
        commands += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("BACKGROUND", (0, 1), (-1, -1), fill)]
    t.setStyle(TableStyle(commands))
    return t


def bullet(text):
    return p("- " + text, ST["body"])


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#C4D3E2"))
    canvas.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#4E6173"))
    canvas.drawString(18 * mm, 9 * mm, "ContractIQ - Phase 1 Document Validator Guide")
    canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def flow_diagram():
    labels = ["1. Upload", "2. File checks", "3. Text extraction", "4. Classification", "5. Validate", "6. Claim result"]
    blocks = [[p(label, ST["center"])] for label in labels]
    row = []
    for index, item in enumerate(blocks):
        row.append(item[0])
        if index < len(blocks) - 1:
            row.append(p("->", ST["center"]))
    t = Table([row], colWidths=[23 * mm, 7 * mm, 23 * mm, 7 * mm, 27 * mm, 7 * mm, 26 * mm, 7 * mm, 23 * mm, 7 * mm, 28 * mm])
    style = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("BACKGROUND", (0, 0), (0, 0), PALE), ("BACKGROUND", (2, 0), (2, 0), PALE), ("BACKGROUND", (4, 0), (4, 0), PALE), ("BACKGROUND", (6, 0), (6, 0), PALE), ("BACKGROUND", (8, 0), (8, 0), PALE), ("BACKGROUND", (10, 0), (10, 0), PALE), ("BOX", (0, 0), (0, 0), 0.5, BLUE), ("BOX", (2, 0), (2, 0), 0.5, BLUE), ("BOX", (4, 0), (4, 0), 0.5, BLUE), ("BOX", (6, 0), (6, 0), 0.5, BLUE), ("BOX", (8, 0), (8, 0), 0.5, BLUE), ("BOX", (10, 0), (10, 0), 0.5, BLUE), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]
    t.setStyle(TableStyle(style))
    return t


def guide():
    story = []
    story += [Spacer(1, 36 * mm), p("ContractIQ", ST["title"]), p("Phase 1: Motor Claim Document Validator", ST["title"]), Spacer(1, 5 * mm), p("A practical end-to-end guide: from a customer upload to an auditable validation outcome.", ST["subtitle"]), Spacer(1, 16 * mm)]
    story += [table([["Phase 1 objective", "Validate a claim document package before downstream extraction or claim assessment."], ["Decision boundary", "The system never approves or rejects an insurance claim. It gives a reviewable document-validation outcome."], ["Current implementation", "FastAPI service, deterministic content classifier, PDF text extraction, duplicate/missing checks, and structured JSON output."]], [45 * mm, 125 * mm]), Spacer(1, 12 * mm), p("Audience: business users, claims teams, developers, and reviewers", ST["small"]), PageBreak()]

    story += [p("1. What Phase 1 solves", ST["h1"]), p("Motor-claim packages arrive as PDFs, scans, and images. Before an insurer can extract values or assess coverage, it must know whether the right documents were received and whether each upload appears to be the document it claims to be.", ST["body"]), p("Phase 1 is the intake gate. It turns a set of uploaded files into a consistent, machine-readable validation result that a claims officer can understand and act on.", ST["body"]), p("Business questions answered", ST["h2"])]
    story += [bullet("Which files were submitted for this claim?"), bullet("Are the files supported, non-empty, within the configured size limit, and readable?"), bullet("Which document type does the content indicate: RC, policy, licence, claim form, FIR, estimate, invoice, or accident-photo record?"), bullet("Does the detected type match the document type expected for that upload?"), bullet("Are any file contents duplicates? Which required documents are missing?"), bullet("Should the package proceed, be corrected, or be sent for human review?")]
    story += [p("Out of scope in Phase 1", ST["h2"]), table([["Not performed", "Why it is deferred"], ["Claim approval/rejection", "A human claim officer remains the decision-maker."], ["Field extraction", "Vehicle number, policy dates, invoice totals, and names are Phase 2 extraction work."], ["Cross-document comparison", "Matching the vehicle number across RC, policy, and invoice is Phase 3."], ["OCR for scans", "Requires an IDP/OCR provider such as Azure Document Intelligence."]], [67 * mm, 103 * mm]), PageBreak()]

    story += [p("2. End-to-end upload flow", ST["h1"]), flow_diagram(), Spacer(1, 10 * mm), p("Step 1 - Upload", ST["h2"]), p("A user opens the local ContractIQ page, enters a claim ID, chooses one or more supported files, and optionally selects the expected document type. The browser sends a multipart request to the versioned API endpoint:", ST["body"]), p("POST /api/v1/claims/{claim_id}/validate", ST["code"]), p("Supported types are .txt, .pdf, .jpg, .jpeg, and .png. The configured default file-size limit is 10 MB. The file name is displayed in the outcome but is not used to decide the document type.", ST["body"]), p("Step 2 - API intake", ST["h2"]), p("The FastAPI route checks that expected-document values, when supplied, line up with the number of files. It reads each upload into an IncomingFile object containing the original name, bytes, and optional expected type. The route delegates to the validation service; it does not embed business rules itself.", ST["body"]), p("Step 3 - Claim-level processing", ST["h2"]), p("The validation service processes every file, builds individual file results, checks required-document coverage, and derives a claim-level status. The result is returned as JSON to the browser and is ready for storage or later audit integration.", ST["body"]), PageBreak()]

    story += [p("3. File validation and readability", ST["h1"]), table([["Check", "Current behaviour", "Why it matters"], ["Allowed extension", "Accepts TXT, PDF, JPG, JPEG, PNG; rejects other extensions.", "Prevents unsupported files entering downstream processing."], ["Empty file", "Returns UNREADABLE.", "Avoids treating an empty upload as a document."], ["Size limit", "Returns UNREADABLE when over MAX_UPLOAD_SIZE_BYTES.", "Controls resource use and reduces abuse risk."], ["PDF readability", "Uses pypdf to open a PDF and extract its embedded text.", "Digital PDFs can be classified from their content."], ["Image / scan", "Returns NEEDS_REVIEW with an OCR-required message.", "No OCR engine is currently connected."], ["Exact duplicate", "SHA-256 hash identifies identical file bytes.", "Avoids double-counting the same upload."]], [38 * mm, 72 * mm, 60 * mm]), Spacer(1, 8 * mm), p("Why an image can be readable to a person but not to Phase 1", ST["h2"]), p("A JPG, PNG, or scanned PDF often contains pixels rather than selectable text. The current service deliberately does not guess from the file name. It routes these files for review because genuine content classification needs OCR first. This is expected behaviour, not a claim decision.", ST["body"]), p("Production next step", ST["h2"]), p("Connect Azure Document Intelligence or another approved OCR/IDP provider. Its extracted text becomes the input to the same classifier and validation rules. This keeps the business workflow stable while improving coverage for scans and photos.", ST["body"]), PageBreak()]

    story += [p("4. How document classification works", ST["h1"]), p("Phase 1 uses a deterministic, explainable content classifier. It lowercases the extracted text, normalizes repeated spaces and line breaks, and searches for document-specific indicators. It never decides solely from a filename such as RC.pdf.", ST["body"]), table([["Document type", "Examples of content indicators"], ["Registration Certificate (RC)", "Certificate of Registration, Registration No, Regn No, Chassis Number, Engine Number, Vehicle Class"], ["Insurance policy", "Certificate of Insurance, Policy Schedule, Policy Number, Policyholder, Period of Insurance, Own Damage"], ["Driving licence", "Driving Licence / Driving License, Licence Number, DL No, Valid Till, Date of Issue"], ["Claim form", "Claim Form, Claimant, Date of Loss, Accident Details, Claim Number"], ["FIR / police report", "First Information Report, FIR No, Police Station, Complainant"], ["Garage estimate", "Garage Estimate, Repair Estimate, Estimate No, Labour Charges, Estimated Cost"], ["Repair invoice", "Tax Invoice, Invoice Number, GSTIN, Bill Amount, Amount Payable"], ["Accident-photo record", "Accident Photograph, Damage Photograph, Vehicle Damage Photo"]], [47 * mm, 123 * mm]), Spacer(1, 7 * mm), p("Confidence", ST["h2"]), p("Each matched indicator adds to the selected type's score. More evidence raises confidence; close competing types lower it. If confidence is below the configured 0.70 threshold, the service returns NEEDS_REVIEW rather than taking a confident position.", ST["body"]), PageBreak()]

    story += [p("5. Expected-versus-detected validation", ST["h1"]), p("Classification identifies what the uploaded content appears to be. Validation compares that result with what the user or workflow expected. This catches a common real-world issue: a customer uploads an RC where the FIR was requested, even if the file name says FIR.pdf.", ST["body"]), table([["Expected", "Detected from content", "Result", "Meaning"], ["RC", "RC", "VALID", "The content matches the expected document type."], ["FIR", "RC", "WRONG_DOCUMENT", "The content is readable but is not the requested type."], ["None", "Driving licence", "VALID", "Automatic detection succeeded without a pre-selected type."], ["RC", "Unknown / low confidence", "NEEDS_REVIEW", "Do not reject; send for a human check."], ["Any", "Unreadable / invalid PDF", "UNREADABLE", "The service cannot safely inspect the content."], ["Any", "Exact same file as earlier", "DUPLICATE", "The file content was already uploaded."]], [27 * mm, 42 * mm, 34 * mm, 67 * mm]), Spacer(1, 8 * mm), p("Important distinction", ST["h2"]), p("WRONG_DOCUMENT is not the same as UNREADABLE. Wrong means the content was understood and did not match the requested type. Unreadable means the content could not safely be inspected. NEEDS_REVIEW means the system deliberately asks for human help instead of pretending certainty.", ST["body"]), PageBreak()]

    story += [p("6. Claim-level completeness", ST["h1"]), p("A standard motor claim package in the current configuration requires five documents: claim form, RC, policy, driving licence, and garage estimate. FIR, repair invoice, and accident-photo records can still be classified when present but are not mandatory in the default rule set. Actual requirements should later be driven by claim type, policy rules, and incident facts.", ST["body"]), table([["Claim result field", "Explanation"], ["required_documents", "The configured list of documents required for the claim."], ["missing_documents", "Required types that did not receive a VALID document."], ["documents_received", "Number of uploaded files, including duplicates and unreadable files."], ["valid_documents", "Number of file results with status VALID."], ["invalid_documents", "All non-VALID file results in the current Phase 1 response."], ["overall_status", "COMPLETE only when there are no missing documents and no non-VALID uploads; otherwise NEEDS_CORRECTION."], ["files", "An audit-friendly item for every submitted file, including detected type, confidence, message, evidence, and duplicate reference."]], [55 * mm, 115 * mm]), Spacer(1, 8 * mm), p("Example response", ST["h2"]), p('{"file_name":"document_04.pdf", "expected_document":"rc", "detected_document":"fir", "classification_confidence":0.96, "status":"WRONG_DOCUMENT", "message":"Expected rc, but content indicates fir"}', ST["code"]), PageBreak()]

    story += [p("7. Code structure and responsibilities", ST["h1"]), table([["Location", "Responsibility"], ["app/main.py", "Creates the FastAPI application, test page, health endpoint, and API router."], ["app/api/v1/routes/claims.py", "Accepts HTTP uploads, validates request shape, and creates IncomingFile objects."], ["app/services/validator.py", "Runs file checks, text extraction, duplicate detection, expected-vs-detected validation, and claim aggregation."], ["app/services/classifier.py", "Defines document indicators and calculates deterministic classification confidence."], ["app/schemas/documents.py", "Defines Pydantic document types, statuses, and response contracts."], ["app/core/config.py", "Reads environment-based settings such as size and confidence thresholds."], ["tests/test_validator.py", "Verifies complete claims, wrong documents, duplicates, ambiguity, RC wording, and scanned-PDF review handling."], ["sample_data/", "Contains clearly labelled synthetic PDFs for local demo and regression testing."]], [59 * mm, 111 * mm]), Spacer(1, 9 * mm), p("Why this separation matters", ST["h2"]), p("The API layer can change without changing validation rules. The classifier can be improved or replaced by a model without changing the response contract. OCR can be introduced as a text-extraction provider without rewriting claim-completeness logic. This is the intended production evolution path.", ST["body"]), PageBreak()]

    story += [p("8. Local testing guide", ST["h1"]), p("Start the service", ST["h2"]), p("$py = 'C:\\Users\\mital\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe'\n& $py -m pip install -r requirements.txt\n& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload", ST["code"]), p("Use the upload page", ST["h2"])]
    story += [bullet("Open http://127.0.0.1:8001/."), bullet("Enter a claim ID, such as CLM-DEMO-001."), bullet("Select one or more synthetic PDFs under sample_data/motor_claim_clm_demo_001/."), bullet("For a package demonstration, leave Expected document type as Detect automatically."), bullet("Click Validate documents and inspect the returned per-file and claim-level JSON.")]
    story += [p("Run automated tests", ST["h2"]), p("& $py -m pytest -q", ST["code"]), p("Expected result: six tests pass in the committed Phase 1 baseline. The tests are a regression safety net; they should be expanded when new document types, OCR, or policy-specific requirements are introduced.", ST["body"]), PageBreak()]

    story += [p("9. LLMs, OCR, and the roadmap", ST["h1"]), table([["Capability", "Needed now?", "Reason"], ["Deterministic validation rules", "Yes", "Best for required documents, duplicates, file checks, auditability, and predictable expected-vs-detected comparisons."], ["LLM", "No", "Not required for the current classification and validation workflow. It can add cost and non-determinism if used where rules are enough."], ["OCR / IDP", "Required for scans", "Needed to convert image-only PDFs, JPGs, and PNGs into text before they can be classified."], ["Azure Document Intelligence", "Phase 1 production enhancement", "A suitable managed OCR/IDP option for document text, layout, and later structured fields."], ["LLM-assisted extraction", "Later, selectively", "Useful for varied layouts, nuanced explanations, and complex unstructured evidence after deterministic controls are in place."]], [55 * mm, 30 * mm, 85 * mm]), Spacer(1, 9 * mm), p("Recommended next phases", ST["h2"])]
    story += [bullet("Phase 1.1: OCR integration plus encrypted/malformed-PDF handling and an operator review queue."), bullet("Phase 2: Extract structured fields from classified documents, with field confidence and source evidence."), bullet("Phase 3: Cross-document checks: registration number, owner/insured name, policy period, and invoice consistency."), bullet("Phase 4: Policy coverage rules and human decision support. Do not autonomously settle claims."), bullet("Production hardening: identity and access control, malware scanning, object storage, database audit trail, secret management, monitoring, rate limits, CI/CD, and data-retention controls.")]
    story += [Spacer(1, 12 * mm), p("Key takeaway", ST["h2"]), p("Phase 1 is a reliable document-intake gate: it accepts files, inspects their readable content, classifies them with transparent rules, compares them with what was expected, identifies duplicates and gaps, and returns a human-reviewable outcome. OCR extends its reach to scans; an LLM is optional and belongs later, where unstructured understanding genuinely adds value.", ST["body"])]
    return story


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ST = build_styles()
    pdf = SimpleDocTemplate(str(OUTPUT), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=20 * mm, title="ContractIQ Phase 1 Document Validator Guide", author="ContractIQ")
    pdf.build(guide(), onFirstPage=header_footer, onLaterPages=header_footer)
