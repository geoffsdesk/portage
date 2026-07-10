from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict


class EscalationItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="Escalation ID")
    skill: str = Field(..., description="Originating skill name")
    reason: str = Field(..., description="Why the skill stopped or escalated")
    status: str = Field(default="OPEN", description="OPEN, RESOLVED, or DEFERRED")


class OrchestratorState(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str = Field(..., description="Unique migration run ID")
    source: Dict[str, Any] = Field(..., description="Source environment metadata (AWS account, region, cluster)")
    target: Dict[str, Any] = Field(..., description="Target environment metadata (GCP project, region, cluster)")
    current_phase: str = Field(default="P0", description="Current phase (P0-P5)")
    current_skill: Optional[str] = Field(None, description="Currently executing skill")
    completed_skills: List[str] = Field(default_factory=list, description="List of completed skills")
    open_escalations: List[EscalationItem] = Field(default_factory=list, description="Open escalations requiring human review")
