from typing import Literal
from uuid import UUID

from pydantic import Field, HttpUrl

from .base import Contract


class StoredAsset(Contract):
    public_id: UUID
    kind: Literal["html", "image", "document", "screenshot", "other"]
    bucket: str = Field(min_length=3)
    object_key: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_qt: int = Field(ge=0)
    media_type: str = Field(min_length=1)
    source_url: HttpUrl | None = None

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.object_key}"
