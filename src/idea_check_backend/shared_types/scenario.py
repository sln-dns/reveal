from pydantic import BaseModel


class ScenarioDraft(BaseModel):
    id: str
    prompt: str
