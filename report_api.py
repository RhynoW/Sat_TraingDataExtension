#!/usr/bin/env python3
"""report_api.py — 衛星機動偵測 PDF 報表 API（獨立於 Streamlit app 部署）。

用法（本機測試）：
    uvicorn report_api:app --host 0.0.0.0 --port 8080

呼叫範例：
    GET  /report?NORAD=66666&StartDate=20251201&EndDate=20260915&Format=F1
    POST /report  {"NORAD": 66666, "StartDate": "20251201", "EndDate": "20260915", "Format": "F2"}

Format：F1＝簡版（1 頁摘要）／F2＝完整版（摘要＋時序圖＋AI 思維過程說明）。
回傳：成功時 200 + application/pdf；失敗時 JSON 錯誤內容（404／422／500）。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

import maneuver_report_builder as rb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("report_api")

app = FastAPI(title="Maneuver Detection Report API", version="1.0.0")

# 互動式儀表板 app 的公開網址，用來組深連結（?mode=tool&norad=&d0=&d1=，
# 見 maneuver_app_2026SOctober.py 的對應支援）。可用環境變數覆寫（例如本機測試
# 時指向 http://localhost:8501）；未設時預設指向目前實際部署的正式站。
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://rhynowu-maneuver-detection-i18n.hf.space").rstrip("/")


class ReportRequest(BaseModel):
    NORAD: int = Field(..., description="衛星 NORAD 編號")
    StartDate: str = Field(..., description="起始日期，格式 YYYYMMDD")
    EndDate: str = Field(..., description="結束日期，格式 YYYYMMDD")
    Format: str = Field("F1", description="F1＝簡版／F2＝完整版")


def _parse_date(s: str, field: str):
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} 格式錯誤，應為 YYYYMMDD（收到：{s}）")


def _generate(request: Request, norad: int, start: str, end: str, fmt: str) -> Response:
    fmt_u = (fmt or "F1").upper()
    if fmt_u not in ("F1", "F2"):
        raise HTTPException(status_code=422, detail=f"Format 僅支援 F1／F2（收到：{fmt}）")
    d0 = _parse_date(start, "StartDate")
    d1 = _parse_date(end, "EndDate")
    if d1 < d0:
        raise HTTPException(status_code=422, detail="EndDate 早於 StartDate")

    try:
        data = rb.build_report_data(norad, d0, d1)
    except rb.ReportNotFoundError as e:
        # NORAD 查無資料 / 區間內筆數不足 → 視為找不到可報告的內容
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # 其他例外一律視為程式錯誤，回 500 並記錄完整 traceback（不可誤判成 404）
        logger.exception("build_report_data 失敗：NORAD=%s %s~%s", norad, d0, d1)
        raise HTTPException(status_code=500, detail=f"報表資料產製失敗：{e}")

    # QR code 一律指向這份報表的「GET 版可分享網址」——即使是 POST 呼叫產生的，
    # 掃碼也要能開出同一份報表，因此不用 request.url 原樣（POST 沒有查詢字串）。
    # scheme 優先信任 X-Forwarded-Proto：HF Space 等部署都是反向代理終止 TLS，
    # ASGI 層看到的 request.url.scheme 會是 http，直接使用會讓 QR code 指向錯誤的
    # 不安全網址（雖然通常仍可透過重導向到 https，但不應該讓使用者掃到錯的網址）。
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    base = f"{scheme}://{request.url.netloc}/report"
    source_url = f"{base}?NORAD={norad}&StartDate={start}&EndDate={end}&Format={fmt_u}"
    app_url = (f"{APP_BASE_URL}/?mode=tool&norad={norad}"
               f"&d0={d0.isoformat()}&d1={d1.isoformat()}")

    try:
        pdf_bytes = rb.render_pdf(data, fmt=fmt_u, source_url=source_url, app_url=app_url)
    except Exception as e:
        logger.exception("render_pdf 失敗：NORAD=%s", norad)
        raise HTTPException(status_code=500, detail=f"PDF 產製失敗：{e}")

    filename = f"maneuver_report_{norad}_{start}_{end}_{fmt_u}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/report")
def get_report(
    request: Request,
    NORAD: int = Query(...),
    StartDate: str = Query(...),
    EndDate: str = Query(...),
    Format: str = Query("F1"),
):
    return _generate(request, NORAD, StartDate, EndDate, Format)


@app.post("/report")
def post_report(req: ReportRequest, request: Request):
    return _generate(request, req.NORAD, req.StartDate, req.EndDate, req.Format)


@app.get("/health")
def health():
    return {"status": "ok", "data_backend": rb.DATA_BACKEND}
