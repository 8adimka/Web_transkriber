from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class AuthResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None = None
    picture_url: str | None = None
    auth_provider: str | None = None
    access_token: str
    refresh_token: str
    token_type: str

    class Config:
        from_attributes = True


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class User(BaseModel):
    id: int
    email: EmailStr

    class Config:
        from_attributes = True


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None = None
    picture_url: str | None = None
    auth_provider: str | None = None

    class Config:
        from_attributes = True
