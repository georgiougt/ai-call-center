from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


# --- Request Models ---

class MessageCreate(BaseModel):
    role: str  # "user" or "model"
    content: str


class ConversationCreate(BaseModel):
    session_id: str
    language: Optional[str] = "el"


class RepairRequestCreate(BaseModel):
    conversation_id: Optional[int] = None
    name: str
    serial: str
    issue: Optional[str] = None


class RepairRequestUpdate(BaseModel):
    name: str
    serial: str
    issue: Optional[str] = None


class MessageUpdate(BaseModel):
    content: str


class ManualConversation(BaseModel):
    messages: List[MessageCreate]
    department: Optional[str] = None


# --- Response Models ---

class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    timestamp: str

    class Config:
        from_attributes = True


class RepairRequestResponse(BaseModel):
    id: int
    conversation_id: Optional[int]
    name: str
    serial: str
    issue: Optional[str]
    timestamp: str

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: int
    session_id: str
    created_at: str
    language: Optional[str]
    department_routed: Optional[str]
    has_repair_data: bool
    messages: List[MessageResponse] = []

    class Config:
        from_attributes = True


class ConversationSummary(BaseModel):
    id: int
    session_id: str
    created_at: str
    language: Optional[str]
    department_routed: Optional[str]
    has_repair_data: bool
    message_count: int

    class Config:
        from_attributes = True
