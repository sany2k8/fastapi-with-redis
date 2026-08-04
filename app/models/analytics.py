"""Request models for the Probabilistic / Time Series / Vector Set endpoints."""

from pydantic import BaseModel, Field


class EmailIn(BaseModel):
    email: str = Field(min_length=3, examples=["alice@example.com"])


class SearchIn(BaseModel):
    user_id: str = Field(min_length=1, examples=["alice"])
    term: str = Field(min_length=1, max_length=100, examples=["redis streams"])


class MetricIn(BaseModel):
    value: float = Field(examples=[42.5])
    timestamp_ms: int | None = Field(default=None, description="Defaults to server time")


class VectorIn(BaseModel):
    tags: list[str] = Field(min_length=1, examples=[["redis", "python", "databases"]])


class LocationIn(BaseModel):
    longitude: float = Field(ge=-180, le=180, examples=[4.8952])
    latitude: float = Field(ge=-85.05, le=85.05, examples=[52.3702])
