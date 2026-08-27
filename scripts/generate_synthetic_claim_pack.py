"""Generate a safe, synthetic motor-insurance claim document pack for local testing."""
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

OUTPUT = Path("sample_data/motor_claim_clm_demo_001")
CLAIM_ID = "CLM-DEMO-001"

DOCUMENTS = [
    ("01_claim_form.pdf", "Motor Insurance Claim Form", [
        ("Claim Number", CLAIM_ID), ("Claimant", "Aarav Sharma - SYNTHETIC TEST DATA"),
        ("Date of Loss", "15 August 2026"), ("Accident Details", "Minor front-impact collision in Pune."),
        ("Vehicle Registration", "MH12DE1234"),
    ]),
    ("02_registration_certificate_rc.pdf", "Certificate of Registration", [
        ("Registration No", "MH12DE1234"), ("Owner Name", "Aarav Sharma - SYNTHETIC TEST DATA"),
        ("Vehicle Class", "Motor Car"), ("Maker's Name", "Example Motors India"),
        ("Engine Number", "ENG-DEMO-2026-001"), ("Chassis Number", "CHS-DEMO-2026-001"),
        ("Date of Registration", "10 January 2025"),
    ]),
    ("03_insurance_policy.pdf", "Certificate of Insurance - Policy Schedule", [
        ("Policy Number", "POL-DEMO-2026-1001"), ("Policyholder", "Aarav Sharma - SYNTHETIC TEST DATA"),
        ("Vehicle Registration Number", "MH12DE1234"), ("Period of Insurance", "01 January 2026 to 31 December 2026"),
        ("Insured Declared Value", "INR 850,000"), ("Own Damage", "Covered"),
        ("Third Party Liability", "Covered"),
    ]),
    ("04_driving_licence.pdf", "Driving Licence", [
        ("Licence Number", "DL-DEMO-1234567"), ("Holder Name", "Aarav Sharma - SYNTHETIC TEST DATA"),
        ("Date of Issue", "20 June 2020"), ("Valid Till", "19 June 2040"),
        ("Vehicle Class", "LMV - Non Transport"),
    ]),
    ("05_fir_police_report.pdf", "First Information Report", [
        ("FIR No", "FIR-DEMO-2026-0815"), ("Police Station", "Demo Traffic Police Station, Pune"),
        ("Complainant", "Aarav Sharma - SYNTHETIC TEST DATA"),
        ("Date and Time of Occurrence", "15 August 2026, 14:30"), ("Vehicle Registration", "MH12DE1234"),
    ]),
    ("06_garage_estimate.pdf", "Garage Repair Estimate", [
        ("Estimate No", "EST-DEMO-001"), ("Garage Name", "Demo Auto Works"),
        ("Vehicle Registration", "MH12DE1234"), ("Parts Total", "INR 42,000"),
        ("Labour Charges", "INR 8,000"), ("Estimated Cost", "INR 50,000"),
    ]),
    ("07_repair_invoice.pdf", "Tax Invoice", [
        ("Invoice Number", "INV-DEMO-001"), ("GSTIN", "27ABCDE1234F1Z5"), ("Garage Name", "Demo Auto Works"),
        ("Vehicle Registration", "MH12DE1234"), ("Bill Amount", "INR 48,500"), ("Amount Payable", "INR 48,500"),
    ]),
    ("08_accident_photos_placeholder.pdf", "Accident Photograph Record", [
        ("Record", "Accident Photograph - SYNTHETIC PLACEHOLDER"), ("Vehicle Registration", "MH12DE1234"),
        ("Damage Photograph", "Front bumper, headlamp, and bonnet damage documented."),
        ("Capture Date", "15 August 2026"),
    ]),
]


def build_pdf(path: Path, title: str, fields: list[tuple[str, str]]) -> None:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], textColor=colors.HexColor("#17365D"), fontSize=20, leading=25)
    body_style = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=14)
    document = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    rows = [[Paragraph("<b>Field</b>", body_style), Paragraph("<b>Value</b>", body_style)]]
    rows += [[Paragraph(key, body_style), Paragraph(value, body_style)] for key, value in fields]
    table = Table(rows, colWidths=[55 * mm, 115 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B7C9DD")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F5F8FC")), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F5F8FC"), colors.white]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story = [Paragraph(title, title_style), Spacer(1, 4 * mm), Paragraph("SYNTHETIC TEST DOCUMENT - NOT VALID FOR INSURANCE, IDENTITY, OR FINANCIAL USE", body_style), Spacer(1, 8 * mm), Paragraph(f"Claim package: {CLAIM_ID}", body_style), Spacer(1, 6 * mm), table]
    document.build(story)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for filename, title, fields in DOCUMENTS:
        build_pdf(OUTPUT / filename, title, fields)
    (OUTPUT / "README.txt").write_text("Synthetic Phase 1 test documents only. Upload one or more PDFs to ContractIQ. Do not use as real insurance documents.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
