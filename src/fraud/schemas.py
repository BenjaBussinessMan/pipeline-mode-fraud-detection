from datetime import datetime

from pydantic import BaseModel, Field


class Transaction(BaseModel):
    transaction_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    amount: float = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    merchant_category: str = Field(min_length=1)
    country: str = Field(min_length=2, max_length=2)
    timestamp: datetime


class ScoreResult(BaseModel):
    transaction_id: str
    score: float = Field(ge=0, le=1)
    is_fraud: bool
    reasons: list[str]
