from pydantic import BaseModel, Field

CONTACT_FIELDS = ("company_name", "company_name_kana", "department", "position", "person_name", "person_name_kana", "postal_code", "address", "telephone", "fax", "mobile", "email", "website", "notes")

class OrganizationInput(BaseModel):
    name: str
    sharing_mode: str = Field(pattern="^(isolated|shared)$")
class GroupInput(BaseModel): name: str
class UserInput(BaseModel):
    username: str
    name: str
    password: str = Field(min_length=12)
    group_ids: list[str] = Field(min_length=1)
    role: str = Field(default="member", pattern="^(admin|member)$")
class LoginInput(BaseModel): username: str; password: str
class TotpInput(BaseModel): code: str
class PasswordResetInput(BaseModel): password: str = Field(min_length=12)
class ContactInput(BaseModel):
    company_name: str | None = None; company_name_kana: str | None = None
    department: str | None = None; position: str | None = None
    person_name: str | None = None; person_name_kana: str | None = None
    postal_code: str | None = None; address: str | None = None
    telephone: str | None = None; fax: str | None = None; mobile: str | None = None
    email: str | None = None; website: str | None = None; notes: str | None = None
    resolved_fields: list[str] = []
class ReprocessInput(BaseModel): ocr: bool = True; llm: bool = True
class ManualCardInput(BaseModel):
    corners: list[tuple[float, float]] = Field(min_length=4, max_length=4)
class CompleteReviewInput(BaseModel): retain_photo: bool = False
class BatchConfirmInput(BaseModel): card_ids: list[str] = Field(min_length=1)
class OrientationInput(BaseModel): rotation: int = Field(ge=0, le=270, multiple_of=90)
