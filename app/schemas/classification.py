from enum import Enum
from pydantic import BaseModel, Field


class ClassificationCategory(str, Enum):
    CLAIM_FORM = "claim_form"
    REGISTRATION_CERTIFICATE = "registration_certificate"
    INSURANCE_POLICY = "insurance_policy"
    DRIVING_LICENCE = "driving_licence"
    SURVEY_REPORT = "survey_report"
    REPAIR_ESTIMATE = "repair_estimate"
    REPAIR_INVOICE = "repair_invoice"
    ACCIDENT_PHOTOS = "accident_photos"
    GARAGE_ESTIMATE = "garage_estimate"
    FIR_POLICY = "fir_policy"

    @classmethod
    def normalize(cls, value: str) -> "ClassificationCategory":
        cleaned = value.strip().lower()
        alias_map = {
            # RC
            "rc": cls.REGISTRATION_CERTIFICATE,
            "registration_certificate": cls.REGISTRATION_CERTIFICATE,
            "registration certificate": cls.REGISTRATION_CERTIFICATE,
            # Policy
            "policy": cls.INSURANCE_POLICY,
            "insurance_policy": cls.INSURANCE_POLICY,
            "insurance policy": cls.INSURANCE_POLICY,
            # Claim Form
            "claim_form": cls.CLAIM_FORM,
            "claim form": cls.CLAIM_FORM,
            # Driver Licence
            "driver licence": cls.DRIVING_LICENCE,
            "driver license": cls.DRIVING_LICENCE,
            "driver_licence": cls.DRIVING_LICENCE,
            "driver_license": cls.DRIVING_LICENCE,
            "driving_licence": cls.DRIVING_LICENCE,
            "driving licence": cls.DRIVING_LICENCE,
            "driving_license": cls.DRIVING_LICENCE,
            "driving license": cls.DRIVING_LICENCE,
            "dl": cls.DRIVING_LICENCE,
            # Survey Report Motor Insurance
            "survey_report": cls.SURVEY_REPORT,
            "survey report": cls.SURVEY_REPORT,
            "survey report motor insurance": cls.SURVEY_REPORT,
            "survey_report_motor_insurance": cls.SURVEY_REPORT,
            "survey": cls.SURVEY_REPORT,
            # Repair Estimate Details
            "repair_estimate": cls.REPAIR_ESTIMATE,
            "repair estimate": cls.REPAIR_ESTIMATE,
            "repair estimate details": cls.REPAIR_ESTIMATE,
            "repair_estimate_details": cls.REPAIR_ESTIMATE,
            "garage_estimate": cls.REPAIR_ESTIMATE,
            "garage estimate": cls.REPAIR_ESTIMATE,
            # Repair Invoice
            "repair_invoice": cls.REPAIR_INVOICE,
            "repair invoice": cls.REPAIR_INVOICE,
            # Accident Photos / Car Pic Four Side
            "accident_photos": cls.ACCIDENT_PHOTOS,
            "accident photos": cls.ACCIDENT_PHOTOS,
            "car pic four side": cls.ACCIDENT_PHOTOS,
            "car_pic_four_side": cls.ACCIDENT_PHOTOS,
            "car pics four side": cls.ACCIDENT_PHOTOS,
            "car pic 4 side": cls.ACCIDENT_PHOTOS,
            "accident_photos_of_vehicle_from_all_4_side": cls.ACCIDENT_PHOTOS,
            "accident photos of vehicle from all 4 side": cls.ACCIDENT_PHOTOS,
            # FIR
            "fir": cls.FIR_POLICY,
            "fir_policy": cls.FIR_POLICY,
            "fir policy": cls.FIR_POLICY,
        }
        if cleaned in alias_map:
            return alias_map[cleaned]
        try:
            return cls(cleaned)
        except ValueError:
            raise ValueError(
                f"Invalid category_type '{value}'. Must be one of: "
                f"{', '.join([e.value for e in cls])} or common aliases like 'rc', 'policy', 'survey report motor insurance'."
            )


class FileAssessment(BaseModel):
    filename: str
    status: str
    detected_content: str
    notes: str


class AccidentPhotoCoverage(BaseModel):
    front_view: bool = False
    rear_view: bool = False
    left_side_view: bool = False
    right_side_view: bool = False
    all_4_sides_present: bool = False
    missing_views: list[str] = Field(default_factory=list)


class ClassificationResponse(BaseModel):
    is_valid: bool
    category_type: str
    detected_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    description: str
    error: str | None = None
    file_assessments: list[FileAssessment] = Field(default_factory=list)
    accident_photo_coverage: AccidentPhotoCoverage | None = None
