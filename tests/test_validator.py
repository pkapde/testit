from app.schemas.documents import DocumentType, FileStatus
from app.services.validator import IncomingFile, validate_claim
from io import BytesIO
from pypdf import PdfWriter


def file(name: str, content: str, expected: DocumentType | None = None) -> IncomingFile:
    return IncomingFile(name, content.encode(), expected)


def test_classifies_and_validates_complete_claim():
    files = [
        file("x.txt", "Claim Form claimant accident details date of loss", DocumentType.CLAIM_FORM),
        file("x2.txt", "Registration Certificate registration no chassis no vehicle class", DocumentType.RC),
        file("x3.txt", "Insurance Policy policy number period of insurance insured declared value", DocumentType.POLICY),
        file("x4.txt", "Driving Licence licence no valid till driving licence", DocumentType.DRIVING_LICENCE),
        file("x5.txt", "Garage Estimate repair estimate estimated cost labour charges", DocumentType.GARAGE_ESTIMATE),
    ]
    result = validate_claim("CLM-1", files)
    assert result.overall_status == "COMPLETE"
    assert not result.missing_documents
    assert all(item.status == FileStatus.VALID for item in result.files)


def test_flags_wrong_document_based_on_content_not_filename():
    result = validate_claim("CLM-2", [file("RC.pdf.txt", "First Information Report FIR No police station complainant", DocumentType.RC)])
    assert result.files[0].detected_document == DocumentType.FIR
    assert result.files[0].status == FileStatus.WRONG_DOCUMENT


def test_flags_duplicates_and_missing_required_document():
    item = file("rc-one.txt", "Registration Certificate registration no chassis no vehicle class", DocumentType.RC)
    duplicate = file("rc-two.txt", "Registration Certificate registration no chassis no vehicle class", DocumentType.RC)
    result = validate_claim("CLM-3", [item, duplicate])
    assert result.files[1].status == FileStatus.DUPLICATE
    assert DocumentType.POLICY in result.missing_documents


def test_ambiguous_text_needs_review():
    result = validate_claim("CLM-4", [file("mystery.txt", "Some handwritten note about a car")])
    assert result.files[0].status == FileStatus.NEEDS_REVIEW


def test_classifies_common_rc_wording_found_in_digital_pdfs():
    result = validate_claim("CLM-5", [file("vehicle.pdf.txt", "Certificate of Registration Regn No Engine Number Chassis Number Maker's Name", DocumentType.RC)])
    assert result.files[0].detected_document == DocumentType.RC
    assert result.files[0].status == FileStatus.VALID


def test_scanned_pdf_requires_review_instead_of_being_marked_unreadable():
    pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    result = validate_claim("CLM-6", [IncomingFile("scanned.pdf", pdf.getvalue())])
    assert result.files[0].status == FileStatus.NEEDS_REVIEW
    assert "OCR" in result.files[0].message
