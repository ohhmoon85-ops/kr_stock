import os
import sys
import json
import logging
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/health":
            self._respond(200, {"status": "ok", "service": "Korean Stock Analyzer"})

        elif path == "/api":
            self._run_analysis()

        else:
            self._respond(404, {"error": "Not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api":
            self._run_analysis()
        else:
            self._respond(404, {"error": "Not found"})

    def _run_analysis(self):
        # Cron 인증
        auth_header = self.headers.get("authorization", "")
        cron_secret = os.environ.get("CRON_SECRET", "")
        if cron_secret and auth_header != f"Bearer {cron_secret}":
            self._respond(401, {"error": "Unauthorized"})
            return

        try:
            logger.info("=== 한국 주식 분석 시작 ===")

            from data_collector import collect_market_data
            from analyzer import generate_report
            from telegram_sender import send_telegram_message

            logger.info("시장 데이터 수집 중...")
            market_data = collect_market_data()

            logger.info("AI 리포트 생성 중...")
            report = generate_report(market_data)

            logger.info("텔레그램 전송 중...")
            send_telegram_message(report)

            logger.info("=== 완료 ===")
            self._respond(200, {"status": "success", "message": "리포트 전송 완료"})

        except Exception as e:
            logger.error(f"오류: {e}", exc_info=True)
            try:
                from telegram_sender import send_telegram_message
                send_telegram_message(f"⚠️ *오류 발생*\n`{str(e)}`")
            except Exception:
                pass
            self._respond(500, {"error": str(e)})

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        logger.info(fmt % args)
