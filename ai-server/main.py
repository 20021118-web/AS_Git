# -*- coding: utf-8 -*-
"""
main.py — ServerBox 공용 AI 모델 서버

여러 프로젝트가 공유하는 AI 기능을 API 로 제공한다. 모델은 최초 호출 시 1회만
메모리에 올라가고 이후 재사용된다 (프로젝트마다 따로 올리지 않아 메모리 절약).

  GET  /health      서버 생존 확인
  POST /embed       이미지 → CLIP 임베딩(512차원, 정규화) — 의미 유사도 비교용
  POST /remove-bg   이미지 → 배경 제거된 PNG(투명 배경)

실행:  uvicorn main:app --host 127.0.0.1 --port 8100
       (보안상 같은 PC 안의 앱들만 쓰도록 127.0.0.1 바인딩)
"""
import io
import threading

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import Response
from PIL import Image

app = FastAPI(title="ServerBox AI 모델 서버")

_lock = threading.Lock()
_clip = None
_rembg = None


def _get_clip():
    """CLIP ViT-B/32 (sentence-transformers). 최초 1회 로딩(~600MB 다운로드)."""
    global _clip
    with _lock:
        if _clip is None:
            from sentence_transformers import SentenceTransformer
            _clip = SentenceTransformer("clip-ViT-B-32", device="cpu")
    return _clip


def _get_rembg():
    global _rembg
    with _lock:
        if _rembg is None:
            from rembg import new_session
            _rembg = new_session()
    return _rembg


@app.get("/health")
def health():
    return {"ok": True, "clip_loaded": _clip is not None, "rembg_loaded": _rembg is not None}


@app.post("/embed")
async def embed(file: UploadFile = File(...)):
    img = Image.open(io.BytesIO(await file.read())).convert("RGB")
    model = _get_clip()
    vec = model.encode(img, normalize_embeddings=True)
    return {"embedding": vec.tolist()}


@app.post("/remove-bg")
async def remove_bg(file: UploadFile = File(...)):
    from rembg import remove
    img = Image.open(io.BytesIO(await file.read()))
    if max(img.size) > 1024:
        img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    out = remove(img, session=_get_rembg())
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")
