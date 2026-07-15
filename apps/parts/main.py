# -*- coding: utf-8 -*-
"""
main.py — AS 부품 이미지 자동 매칭 서버 (ServerBox 입주 앱 #1)

  · 계산(SIFT 매칭, 배경 제거)을 전부 서버에서 수행 → 접속 PC 는 화면만 담당
  · AI 유사도(CLIP)는 공용 AI 서버(ai-server, 포트 8100)가 켜져 있으면 자동 사용
  실행:  uvicorn main:app --host 0.0.0.0 --port 8001
"""
import io
import os
import sys
import threading
import time
import uuid
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # engine 임포트 (실행 위치 무관)

import httpx
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

import engine
import excel_writer

AI_SERVER = "http://127.0.0.1:8100"  # 공용 AI 모델 서버 (없으면 SIFT 만으로 동작)

app = FastAPI(title="AS 부품 매칭 서버")

# ---------------------------------------------------------------- 작업(job) 저장소
JOBS: dict = {}          # job_id → {status, progress, message, result, ...}
JOB_TTL = 60 * 60        # 1시간 뒤 자동 정리


def _new_job(kind: str) -> str:
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"kind": kind, "status": "running", "progress": 0, "message": "준비 중…",
                 "created": time.time(), "result": None, "error": None}
    # 오래된 작업 정리
    for k in [k for k, v in JOBS.items() if time.time() - v["created"] > JOB_TTL]:
        JOBS.pop(k, None)
    return jid


def _set(jid, progress=None, message=None):
    j = JOBS.get(jid)
    if not j:
        return
    if progress is not None:
        j["progress"] = round(progress)
    if message is not None:
        j["message"] = message


# ---------------------------------------------------------------- AI 서버 연동 (선택)

def _ai_available() -> bool:
    try:
        r = httpx.get(AI_SERVER + "/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _ai_embed(png_bytes: bytes):
    """AI 서버에서 CLIP 임베딩. 실패 시 None."""
    try:
        r = httpx.post(AI_SERVER + "/embed", files={"file": ("img.png", png_bytes, "image/png")}, timeout=30)
        if r.status_code == 200:
            return r.json()["embedding"]
    except Exception:
        pass
    return None


def _cos(a, b):
    s = sum(x * y for x, y in zip(a, b))
    return s


def _pil_png_bytes(pil):
    buf = io.BytesIO()
    pil.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- 매칭 API

@app.post("/api/match")
async def start_match(
    excels: list[UploadFile] = File(...),
    photos: list[UploadFile] = File(...),
    img_col: str = Form("D"),
    code_col: str = Form("E"),
    start_row: int = Form(4),
    threshold: int = Form(15),
    ai_threshold: float = Form(0.83),
):
    excel_data = [(f.filename, await f.read()) for f in excels]
    photo_data = [(f.filename, await f.read()) for f in photos]
    jid = _new_job("match")
    JOBS[jid]["files"] = {"excels": excel_data}  # 수정 엑셀 생성용 원본 보관

    t = threading.Thread(target=_run_match, daemon=True,
                         args=(jid, excel_data, photo_data, img_col, code_col, start_row, threshold, ai_threshold))
    t.start()
    return {"job_id": jid}


def _run_match(jid, excel_data, photo_data, img_col, code_col, start_row, threshold, ai_threshold):
    try:
        use_ai = _ai_available()

        # 1) 원본 사진 분석
        photos = []
        for i, (name, data) in enumerate(photo_data):
            _set(jid, 5 + 20 * (i + 1) / len(photo_data), f"[1/3] 원본 사진 분석 {i + 1}/{len(photo_data)}")
            pil = Image.open(io.BytesIO(data)).convert("RGB")
            kp, des = engine.get_sift_features(pil)
            emb = _ai_embed(_pil_png_bytes(pil)) if use_ai else None
            photos.append({"name": name, "pil": pil, "kp": kp, "des": des, "emb": emb,
                           "thumb": engine.pil_to_jpeg_b64(pil, 240)})

        # 2) 엑셀 파싱
        _set(jid, 28, "[2/3] 엑셀 분석 중…")
        pairs = []
        for name, data in excel_data:
            folder = name.rsplit(".", 1)[0]
            for sh in engine.parse_workbook(data, img_col, code_col, start_row):
                for r in sh["rows"]:
                    pairs.append({"folder": folder, "excel": name, "sheet": sh["sheet"],
                                  "row": r["row"], "code": r["code"], "image": r["image"]})

        # 3) 매칭 계산
        result_pairs = []
        for i, p in enumerate(pairs):
            _set(jid, 30 + 70 * (i + 1) / max(1, len(pairs)),
                 f"[3/3] 매칭 계산 {i + 1}/{len(pairs)}")
            kp, des = engine.get_sift_features(p["image"])
            q_emb = _ai_embed(_pil_png_bytes(p["image"])) if use_ai else None

            cands = []
            for idx, ph in enumerate(photos):
                score = engine.match_features(kp, des, ph["kp"], ph["des"]) if kp is not None else 0
                ai = _cos(q_emb, ph["emb"]) if (q_emb and ph["emb"]) else None
                cands.append({"photoIdx": idx, "score": score, "ai": ai})
            cands.sort(key=lambda c: (-(c["ai"] or 0), -c["score"]) if use_ai else (-c["score"], 0))

            top = cands[0] if cands else {"photoIdx": -1, "score": 0, "ai": None}
            auto = (top.get("ai") is not None and top["ai"] >= ai_threshold) or top["score"] >= threshold
            result_pairs.append({
                "id": f"p{i}", "folder": p["folder"], "excel": p["excel"], "sheet": p["sheet"],
                "row": p["row"], "code": p["code"],
                "thumb": engine.pil_to_jpeg_b64(p["image"], 240),
                "candidates": cands, "selectedIdx": top["photoIdx"], "auto": auto,
            })

        JOBS[jid]["photos_raw"] = [(ph["name"], ph["pil"]) for ph in photos]  # 내보내기용
        JOBS[jid]["result"] = {
            "aiUsed": use_ai,
            "photos": [{"name": ph["name"], "thumb": ph["thumb"]} for ph in photos],
            "pairs": result_pairs,
        }
        JOBS[jid]["status"] = "done"
        _set(jid, 100, f"매칭 완료 — 총 {len(result_pairs)}건")
    except Exception as e:
        JOBS[jid]["status"] = "error"
        JOBS[jid]["error"] = str(e)


@app.get("/api/match/{jid}")
def match_status(jid: str):
    j = JOBS.get(jid)
    if not j:
        return JSONResponse({"error": "작업을 찾을 수 없습니다"}, status_code=404)
    body = {"status": j["status"], "progress": j["progress"], "message": j["message"], "error": j["error"]}
    if j["status"] == "done":
        body["result"] = j["result"]
    return body


# ---------------------------------------------------------------- 내보내기 API

@app.post("/api/export")
async def start_export(payload: dict):
    """payload: {match_job, items:[{code, folder, sheet, row, photoIdx}], fails:[{sheet, row, excel}], use_bg, fail_col}"""
    mj = JOBS.get(payload.get("match_job", ""))
    if not mj or "photos_raw" not in mj:
        return JSONResponse({"error": "매칭 작업을 찾을 수 없습니다. 다시 매칭해 주세요."}, status_code=400)

    jid = _new_job("export")
    t = threading.Thread(target=_run_export, daemon=True, args=(jid, mj, payload))
    t.start()
    return {"job_id": jid}


def _run_export(jid, mj, payload):
    try:
        items = payload.get("items", [])
        use_bg = bool(payload.get("use_bg", True))
        photos = mj["photos_raw"]

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, it in enumerate(items):
                _set(jid, 90 * (i + 1) / max(1, len(items)),
                     f"처리 중 ({i + 1}/{len(items)}) — {it['folder']}/{it['code']}.jpg")
                pil = photos[it["photoIdx"]][1]
                jpg = engine.remove_bg_white(pil, use_bg=use_bg)
                zf.writestr(f"{it['folder']}/{it['code']}.jpg", jpg)

        # 수정 엑셀 (엑셀 파일별로 실패 행 표시)
        _set(jid, 95, "수정 엑셀 생성 중…")
        fail_col = payload.get("fail_col", "A")
        xlsx_files = []
        for name, data in mj["files"]["excels"]:
            fails = {}
            for f in payload.get("fails", []):
                if f.get("excel") == name:
                    fails.setdefault(f["sheet"], []).append(f["row"])
            if fails:
                data = excel_writer.mark_fail_rows(data, fails, fail_col)
            base = name.rsplit(".", 1)[0]
            xlsx_files.append((base + "_수정.xlsx", data))

        JOBS[jid]["zip"] = zip_buf.getvalue()
        JOBS[jid]["xlsx"] = xlsx_files
        JOBS[jid]["status"] = "done"
        _set(jid, 100, f"완료 — 사진 {len(items)}개 · 엑셀 {len(xlsx_files)}개")
    except Exception as e:
        JOBS[jid]["status"] = "error"
        JOBS[jid]["error"] = str(e)


@app.get("/api/export/{jid}")
def export_status(jid: str):
    j = JOBS.get(jid)
    if not j:
        return JSONResponse({"error": "작업을 찾을 수 없습니다"}, status_code=404)
    return {"status": j["status"], "progress": j["progress"], "message": j["message"], "error": j["error"],
            "xlsxCount": len(j.get("xlsx", []))}


@app.get("/api/export/{jid}/zip")
def export_zip(jid: str):
    j = JOBS.get(jid)
    if not j or "zip" not in j:
        return JSONResponse({"error": "없음"}, status_code=404)
    return Response(j["zip"], media_type="application/zip", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + "AS%EB%B6%80%ED%92%88_%EA%B2%B0%EA%B3%BC%EB%AC%BC.zip"})


@app.get("/api/export/{jid}/xlsx/{idx}")
def export_xlsx(jid: str, idx: int):
    j = JOBS.get(jid)
    if not j or idx >= len(j.get("xlsx", [])):
        return JSONResponse({"error": "없음"}, status_code=404)
    name, data = j["xlsx"][idx]
    from urllib.parse import quote
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@app.get("/api/health")
def health():
    return {"ok": True, "ai": _ai_available()}


# 정적 프런트 (맨 마지막에 마운트, 실행 위치와 무관하게 파일 기준 경로)
_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")
