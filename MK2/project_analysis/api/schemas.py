from pydantic import BaseModel


class ReviewFileRequest(BaseModel):
    path: str
    question: str


class AskProjectRequest(BaseModel):
    question: str