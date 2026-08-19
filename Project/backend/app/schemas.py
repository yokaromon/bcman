import re
from datetime import date
from pydantic import BaseModel, Field, field_validator

CONTACT_FIELDS = ("company_name", "company_name_kana", "department", "position", "person_name", "person_name_kana", "postal_code", "address", "telephone", "fax", "mobile", "email", "website", "notes")

COMPANY_CODE_PATTERN = r"^[a-z0-9-]{3,20}$"

def normalize_company_code(value: str) -> str:
    """スマホのキーボードで YKR と打たれても通るようにする。作成時とログイン時の両方で使う。"""
    return value.strip().lower() if isinstance(value, str) else value

class OrganizationInput(BaseModel):
    """既存 Organization の更新用。code は載せない（作成後は不変。models.Organization 参照）。"""
    name: str
    sharing_mode: str = Field(pattern="^(isolated|shared)$")
class OrganizationCreateInput(BaseModel):
    name: str
    code: str
    sharing_mode: str = Field(default="isolated", pattern="^(isolated|shared)$")
    group_name: str = Field(default="一般")
    admin_username: str
    admin_name: str

    @field_validator("code", mode="before")
    @classmethod
    def _normalize_code(cls, value):
        # Field(pattern=...) は生値に当たるので、ここで小文字化してから形を検査する
        normalized = normalize_company_code(value)
        if not isinstance(normalized, str) or not re.fullmatch(COMPANY_CODE_PATTERN, normalized):
            raise ValueError("会社コードは英小文字・数字・ハイフンの3〜20文字です")
        return normalized
class GroupInput(BaseModel): name: str
class UserInput(BaseModel):
    username: str
    name: str
    group_ids: list[str] = Field(min_length=1)
    role: str = Field(default="member", pattern="^(admin|member)$")
class LoginInput(BaseModel):
    company_code: str
    username: str
    password: str
class TotpInput(BaseModel): code: str
class InvitationCompleteInput(BaseModel):
    password: str = Field(min_length=12)
    code: str
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
class OrientationInput(BaseModel):
    rotation: int = Field(ge=0, le=270, multiple_of=90)
    reread: bool = True
class CardRegistrationInput(BaseModel):
    card_owner_user_id: str
    exchanged_at: date
class ReplacementApplyInput(BaseModel):
    """撮り直した画像を採用するとき、読み取りもやり直すか。
    やり直すと構造化の結果で14項目が上書きされる（手入力も消える）。"""
    reread: bool = False
