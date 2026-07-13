from uuid import UUID

from pydantic import Field, model_validator

from app.core.schemas import ApiModel


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class AdminProfile(ApiModel):
    id: UUID
    username: str
    first_login_required: bool


class LoginResponse(ApiModel):
    admin: AdminProfile
    csrf_token: str
    first_login_required: bool


class ChangePasswordRequest(ApiModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("new password and confirmation must match")
        return self


class SuccessResponse(ApiModel):
    success: bool = True
