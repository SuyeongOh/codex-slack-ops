from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApprovalCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    command: str = Field(min_length=1)
    rationale: str = Field(min_length=3)
    risk_level: Literal["low", "medium", "high"] = "medium"
    requested_by: str = Field(min_length=1, max_length=128)
    channel_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class ExecutionUpdateRequest(BaseModel):
    status: Literal["executing", "completed", "failed"]
    result_summary: Optional[str] = None


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    command: str
    rationale: str
    risk_level: str
    status: str
    requested_by: str
    slack_channel_id: Optional[str]
    slack_message_ts: Optional[str]
    context: Dict[str, Any]
    approved_by: Optional[str]
    rejected_by: Optional[str]
    decision_reason: Optional[str]
    result_summary: Optional[str]
    expires_at: datetime
    decided_at: Optional[datetime]
    executed_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
