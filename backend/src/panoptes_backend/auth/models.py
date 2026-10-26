from panoptes_contracts.base import Contract
from pydantic import Field, SecretStr


class Login(Contract):
    email: str = Field(min_length=1, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)


class Refresh(Contract):
    refresh_token: SecretStr = Field(min_length=1, max_length=4096)
