from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Embedding Service")

class TextIn(BaseModel):
    text: str

# cargar modelo perezosamente para evitar fallo en import si no hay GPU
_model = None

def get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as exc:
            raise RuntimeError(f"failed to load model: {exc}")
    return _model

@app.post("/embeddings")
async def embeddings(payload: TextIn):
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    model = get_model()
    vec = model.encode(payload.text, convert_to_numpy=True).tolist()
    return {"embedding": vec}
