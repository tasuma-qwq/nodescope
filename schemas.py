from pydantic import BaseModel, Field
from typing import Dict, Any, List

class StartRequest(BaseModel):
    yaml_content: str = Field(max_length=5_000_000)
    config: Dict[str, Any] = Field(default_factory=dict)

class UpdateNodeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=512)

class ExportRequest(BaseModel):
    node_ids: List[int]

class RecheckRequest(BaseModel):
    config: Dict[str, Any] = Field(default_factory=dict)
