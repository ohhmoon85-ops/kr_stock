"""
매일 아침 08:00 KST 한국 주식 전망 자동화 시스템
Vercel Serverless Function (Flask)
"""

import os
import sys
import logging

# api 디렉터리를 모듈 검색 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/api/health", methods=["GET"])
def health_check():
    """헬스 체크 엔드포인트"""
    return jsonify({"status": "ok", "service": "Korean Stock Analyzer"})


@app.route("/api", methods=["GET", "POST"])
def handler():
    """Vercel Cron Job 엔드포인트 - 매일 UTC 23:00 (KST 08:00) 실행"""
    # Cron Job 인증
    auth_header = request.headers.get("authorization", "")
    cron_secret = os.environ.get("CRON_SECRET", "")
    if cron_secret and auth_header != f"Bearer {cron_secret}":
        return jsonify({"error": "Unauthorized"}), 401

    try:
        logger.info("=== 한국 주식 분석 시작 ===")

        # 지연 임포트 (콜드 스타트 최적화)
        from data_collector import collect_market_data
        from analyzer import generate_report
        from telegram_sender import send_telegram_message

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
        return jsonify({"status": "success", "message": "리포트 전송 완료"})

    except Exception as e:
        logger.error(f"오류 발생: {e}", exc_info=True)
        try:
            from telegram_sender import send_telegram_message
            send_telegram_message(f"⚠️ *시스템 오류 발생*\n```\n{str(e)}\n```")
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500
