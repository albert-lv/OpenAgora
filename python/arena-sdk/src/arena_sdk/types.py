from pydantic import BaseModel, Field
from typing import Optional, Dict, List

class SamplingConfig(BaseModel):
    temperature: float = 0.7
    top_p: float = 0.95
    seed: Optional[int] = None
    max_tokens_budget: int = 0

class VerifyConfig(BaseModel):
    command: str
    log_parser: Optional[str] = None
    pass_to_pass: List[str] = Field(default_factory=list)
    fail_to_pass: List[str] = Field(default_factory=list)

class SandboxConfig(BaseModel):
    image: str
    memory: str = "8g"
    cpus: float = 2.0
    env_vars: Dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = 3600
