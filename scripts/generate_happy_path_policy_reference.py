"""Create a fictional detailed policy schedule for happy-path E2E testing."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


OUTPUT = Path(__file__).resolve().parents[1] / "sample_data" / "synthetic_happy_path_claim" / "policy_schedule_happy_path_synthetic.pdf"
STYLES = getSampleStyleSheet()


def para(text, style="BodyText"):
    return Paragraph(text, STYLES[style])


def section_table(rows):
    table = Table([[para(f"<b>{key}</b>"), para(value)] for key, value in rows], colWidths=[55 * mm, 101 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF2F8")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9FB3C8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Synthetic Private Car Package Policy Schedule",
        author="ContractIQ Synthetic Test Data",
    )
    elements = [
        para("SYNTHETIC TEST DATA - NOT A REAL INSURANCE POLICY", "Title"),
        Spacer(1, 4 * mm),
        para("Private Car Package Policy Schedule", "Heading1"),
        para("Detailed fictional reference document for a straightforward, admissible own-damage claim."),
        Spacer(1, 5 * mm),
        section_table([
            ("Policy Number", "POL-HAPPY-2026-1024"),
            ("Policyholder", "Meera Iyer (Synthetic Test User)"),
            ("Vehicle Registration", "KA-00-HAPPY-2026"),
            ("Vehicle", "Metallic blue compact hatchback - fictional test vehicle"),
            ("Chassis Number", "MA3HAPPYPATH2026001"),
            ("Engine Number", "ENG-HAPPY-2026-4421"),
            ("Policy Period", "01 January 2026 to 31 December 2026"),
            ("Policy Type", "Private Car Package Policy"),
            ("Insured Declared Value (IDV)", "INR 780,000.00"),
            ("Own Damage Sum Insured", "IDV, subject to policy terms and applicable deductions"),
        ]),
        Spacer(1, 5 * mm),
        para("Coverage Summary", "Heading2"),
        section_table([
            ("Own Damage Cover", "Covered: accidental external means, fire, theft, natural perils and transit, subject to exclusions."),
            ("Third Party Liability", "Covered as required under the policy schedule; not assessed for this own-damage repair claim."),
            ("Accidental Damage", "Covered for the documented front-right collision during the active policy period."),
            ("Compulsory Deductible", "INR 1,000.00 per own-damage claim."),
            ("Voluntary Deductible", "Nil."),
            ("No Claim Bonus (NCB)", "20 percent shown for premium rating. Claim handling must follow the applicable policy conditions."),
            ("Depreciation", "Applicable where required by policy terms for replaced parts unless a valid zero-depreciation add-on applies."),
            ("Zero Depreciation Add-on", "Included for this synthetic test policy."),
            ("Roadside Assistance Add-on", "Included; service benefit, not part of repair reimbursement."),
        ]),
        PageBreak(),
        para("Claim Admissibility and Review Guide", "Heading1"),
        para("This section uses industry-standard terminology in a fictional scenario. It is a test fixture, not legal or coverage advice."),
        Spacer(1, 4 * mm),
        para("Happy-path claim facts", "Heading2"),
        section_table([
            ("Incident Date", "10 September 2026 - within the active policy period."),
            ("Incident Type", "Minor front-right collision with a roadside barrier."),
            ("Requested Reimbursement", "INR 36,500.00."),
            ("Supporting Evidence", "Claim form, RC, driving licence, four angle photos, garage estimate and invoice."),
            ("Expected Settlement Logic", "INR 36,500.00 less INR 1,000.00 compulsory deductible = INR 35,500.00, subject to reviewer confirmation."),
        ]),
        Spacer(1, 5 * mm),
        para("Terms for extraction and validator review", "Heading2"),
        *[
            para(f"- <b>{term}:</b> {definition}")
            for term, definition in [
                ("IDV", "Insured Declared Value; the vehicle sum insured for own-damage purposes."),
                ("Own Damage", "Loss of or damage to the insured vehicle, subject to the policy wording."),
                ("Third Party Liability", "Liability for injury, death, or property damage involving third parties."),
                ("Deductible or Excess", "The amount borne by the insured before the insurer pays an admissible claim."),
                ("NCB", "No Claim Bonus; a premium-rating benefit that may be affected by a claim."),
                ("Depreciation", "A reduction applied to eligible replacement-part value where the policy requires it."),
                ("Endorsement", "A documented amendment to the policy terms, cover, vehicle, or insured details."),
                ("Exclusion", "A circumstance or loss category that is not covered under the policy."),
                ("Surveyor Report", "Independent assessment evidence used to support damage and settlement review."),
                ("Cashless Repair", "Insurer-network repair arrangement; not required for this reimbursement test scenario."),
            ]
        ],
        Spacer(1, 5 * mm),
        para("Synthetic happy-path review conclusion", "Heading2"),
        para(
            "The fictional policy is active, the vehicle and policyholder identifiers are consistent, "
            "the photos support localized front-right collision damage, and the requested repair value "
            "is within the stated IDV. A human validator should still confirm document identity, "
            "licence validity, incident details, repair evidence, exclusions, and deductible before approval."
        ),
        Spacer(1, 6 * mm),
        para(
            "Source terminology reference: IRDAI public motor-insurance guidance and standard private-car package-policy concepts. "
            "All names, identifiers, dates, vehicles, values, terms arrangement, and coverage facts in this document are fictional.",
            "Italic",
        ),
    ]
    document.build(elements)

    claim_documents = [
        (
            "claim_form_happy_path_synthetic.pdf",
            "Motor Insurance Claim Form",
            "Fictional claim submission for the same front-right collision.",
            [
                ("Claim ID", "CLM-HAPPY-2026-0001"),
                ("Policy Number", "POL-HAPPY-2026-1024"),
                ("Policyholder", "Meera Iyer (Synthetic Test User)"),
                ("Vehicle Registration", "KA-00-HAPPY-2026"),
                ("Date of Loss", "10 September 2026"),
                ("Location", "Synthetic Business Park, Bengaluru"),
                ("Nature of Loss", "Minor front-right collision with a roadside barrier"),
                ("Requested Reimbursement", "INR 36,500.00"),
            ],
            ["Four photo angles show the same blue vehicle and localized front-right damage.", "All supporting records in this folder use matching fictional identifiers."],
        ),
        (
            "rc_certificate_happy_path_synthetic.pdf",
            "Certificate of Registration",
            "Fictional RC evidence for vehicle and ownership consistency validation.",
            [
                ("Registration Number", "KA-00-HAPPY-2026"),
                ("Registered Owner", "Meera Iyer (Synthetic Test User)"),
                ("Vehicle", "Metallic blue compact hatchback - fictional test vehicle"),
                ("Chassis Number", "MA3HAPPYPATH2026001"),
                ("Engine Number", "ENG-HAPPY-2026-4421"),
                ("Registration Date", "12 April 2024"),
                ("Fuel Type", "Petrol"),
            ],
            ["Registration, chassis, engine and owner details match the synthetic policy schedule.", "All values are test data only."],
        ),
        (
            "driving_license_happy_path_synthetic.pdf",
            "Driving Licence",
            "Fictional driver-identity and licence-validity evidence.",
            [
                ("Licence Number", "DL-HAPPY-2026-8877"),
                ("Holder Name", "Meera Iyer (Synthetic Test User)"),
                ("Vehicle Class Authorised", "LMV - Light Motor Vehicle"),
                ("Issue Date", "14 June 2012"),
                ("Valid Till", "13 June 2042"),
                ("Address", "Synthetic Address, Bengaluru"),
            ],
            ["Licence is valid on the fictional incident date.", "Vehicle class is suitable for the insured private car."],
        ),
        (
            "repair_estimate_happy_path_synthetic.pdf",
            "Garage Repair Estimate",
            "Fictional estimate for the documented front-right bumper and headlamp repair.",
            [
                ("Estimate Number", "EST-HAPPY-2601"),
                ("Garage", "Happy Path Auto Works"),
                ("Vehicle Registration", "KA-00-HAPPY-2026"),
                ("Front-right Bumper Repair", "INR 10,500.00"),
                ("Right Headlamp Assembly", "INR 16,000.00"),
                ("Paint and Labour", "INR 10,000.00"),
                ("Estimated Repair Cost", "INR 36,500.00"),
            ],
            ["Damage description matches the front-right photo evidence.", "The total matches the claim form and invoice."],
        ),
        (
            "repair_invoice_happy_path_synthetic.pdf",
            "Garage Repair Invoice",
            "Fictional invoice corresponding to the same estimate and repair items.",
            [
                ("Invoice Number", "INV-HAPPY-2601"),
                ("Related Estimate", "EST-HAPPY-2601"),
                ("Garage", "Happy Path Auto Works"),
                ("Vehicle Registration", "KA-00-HAPPY-2026"),
                ("Parts", "INR 26,500.00"),
                ("Labour and Paint", "INR 10,000.00"),
                ("Invoice Total", "INR 36,500.00"),
            ],
            ["Invoice total matches the estimate and requested reimbursement.", "The deductible is applied by the insurer, not added to this invoice."],
        ),
        (
            "survey_report_happy_path_synthetic.pdf",
            "Motor Vehicle Survey Report",
            "Fictional assessor summary for a valid own-damage reimbursement review.",
            [
                ("Survey Reference", "SUR-HAPPY-2026-031"),
                ("Claim ID", "CLM-HAPPY-2026-0001"),
                ("Policy Number", "POL-HAPPY-2026-1024"),
                ("Vehicle Registration", "KA-00-HAPPY-2026"),
                ("Observed Damage", "Front-right bumper scrape and right headlamp lens damage"),
                ("Damage Severity", "Minor to moderate"),
                ("Recommended Settlement", "INR 35,500.00 after INR 1,000.00 compulsory deductible"),
            ],
            ["Vehicle and damage appear consistent across four submitted angles.", "Policy remains active on the incident date; final approval remains with the human validator."],
        ),
    ]
    for filename, title, subtitle, rows, notes in claim_documents:
        _build_supporting_document(filename, title, subtitle, rows, notes)


def _build_supporting_document(filename, title, subtitle, rows, notes):
    document = SimpleDocTemplate(
        str(OUTPUT.parent / filename),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=title,
        author="ContractIQ Synthetic Test Data",
    )
    elements = [
        para("SYNTHETIC TEST DATA - NOT A REAL INSURANCE DOCUMENT", "Title"),
        Spacer(1, 5 * mm),
        para(title, "Heading1"),
        para(subtitle),
        Spacer(1, 5 * mm),
        section_table(rows),
        Spacer(1, 5 * mm),
        para("Validation Notes", "Heading2"),
        *[para(f"- {note}") for note in notes],
        Spacer(1, 6 * mm),
        para(
            "This fictional document was generated only for ContractIQ end-to-end testing. "
            "Do not use it for financial, identity, legal, or insurance purposes.",
            "Italic",
        ),
    ]
    document.build(elements)


if __name__ == "__main__":
    main()
