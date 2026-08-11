from pydantic import BaseModel, Field

CONTACT_FIELDS = ("company_name", "company_name_kana", "department", "position", "person_name", "person_name_kana", "postal_code", "address", "telephone", "fax", "mobile", "email", "website", "notes")

class OrganizationInput(BaseModel):
    name: str
    sharing_mode: str = Field(pattern="^(isolated|shared)$")
class GroupInput(BaseModel): name: str
class UserInput(BaseModel): name: str; group_id: str | None = None; role: str = "member"
class ContactInput(BaseModel):
    company_name: str | None = None; company_name_kana: str | None = None
    department: str | None = None; position: str | None = None
    person_name: str | None = None; person_name_kana: str | None = None
    postal_code: str | None = None; address: str | None = None
    telephone: str | None = None; fax: str | None = None; mobile: str | None = None
    email: str | None = None; website: str | None = None; notes: str | None = None
class ReprocessInput(BaseModel): ocr: bool = True; llm: bool = True
