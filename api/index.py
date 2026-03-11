"""
매일 아침 08:00 KST 한국 주식 전망 자동화 시스템
Vercel Serverless Function (FastAPI)
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import os
import logging

from .data_collector import collect_market_data
from .analyzer import generate_report
from .telegram_sender import send_telegram_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/api")
@app.post("/api")
async def handler(request: Request):
    """Vercel Cron Job 엔드포인트 - 매일 UTC 23:00 (KST 08:00) 실행"""
    # Cron Job 인증 (Vercel이 자동으로 추가하는 헤더)
    auth_header = request.headers.get("authorization", "")
    cron_secret = os.environ.get("CRON_SECRET", "")

    if cron_secret and auth_header != f"Bearer {cron_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        logger.info("=== 한국 주식 분석 시작 ===")

        # 1. 시장 데이터 수집
        logger.info("시장 데이터 수집 중...")
        market_data = collect_market_data()

        # 2. AI 분석 리포트 생성
        logger.info("AI 분석 리포트 생성 중...")
        report = generate_report(market_data)

        # 3. 텔레그램 전송
        logger.info("텔레그램 전송 중...")
        send_telegram_message(report)

        logger.info("=== 분석 완료 및 전송 성공 ===")
        return JSONResponse({"status": "success", "message": "리포트 전송 완료"})

    except Exception as e:
        logger.error(f"오류 발생: {e}", exc_info=True)
        # 오류도 텔레그램으로 알림
        try:
            send_telegram_message(f"⚠️ *시스템 오류 발생*\n```\n{str(e)}\n```")
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "ok", "service": "Korean Stock Analyzer"}
