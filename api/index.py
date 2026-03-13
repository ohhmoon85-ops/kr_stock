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
        elif path == "/api/evaluate":
            self._run_evaluation()
        elif path == "/api/test":
            self._run_test()
        else:
            self._respond(404, {"error": "Not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api":
            self._run_analysis()
        elif path == "/api/evaluate":
            self._run_evaluation()
        else:
            self._respond(404, {"error": "Not found"})

    # ── 일간 분석 (매일 08:00 KST) ───────────────────────────────────────────

    def _run_analysis(self):
        if not self._check_auth():
            return

        try:
            logger.info("=== 한국 주식 일간 분석 시작 ===")

            from data_collector  import collect_market_data
            from analyzer        import generate_report, extract_picks
            from telegram_sender import send_telegram_message

            logger.info("시장 데이터 수집 중...")
            market_data = collect_market_data()

            logger.info("AI 리포트 생성 중...")
            report = generate_report(market_data)

            logger.info("텔레그램 전송 중...")
            send_telegram_message(report)

            # 추천 종목 구조화 추출 후 GitHub에 저장
            try:
                from storage import save_weekly_picks
                picks = extract_picks(report)
                if picks:
                    save_weekly_picks(picks)
            except Exception as e:
                logger.warning(f"추천 종목 저장 실패 (분석은 정상 완료): {e}")

            logger.info("=== 일간 분석 완료 ===")
            self._respond(200, {"status": "success", "message": "리포트 전송 완료"})

        except Exception as e:
            logger.error(f"오류: {e}", exc_info=True)
            try:
                from telegram_sender import send_telegram_message
                send_telegram_message(f"⚠️ *오류 발생*\n`{str(e)}`")
            except Exception:
                pass
            self._respond(500, {"error": str(e)})

    # ── 데이터 수집 테스트 ────────────────────────────────────────────────────

    def _run_test(self):
        try:
            from data_collector import collect_market_data
            market_data = collect_market_data()
            summary = {
                "us_indices_count": len(market_data.get("us_indices", {})),
                "kr_stocks_count":  len(market_data.get("kr_stocks", {})),
                "us_indices": {k: v for k, v in market_data.get("us_indices", {}).items()},
                "kr_stocks":  {k: {"close": v.get("close"), "rsi": v.get("rsi")}
                               for k, v in market_data.get("kr_stocks", {}).items()},
                "elapsed_sec": market_data.get("elapsed_sec"),
            }
            self._respond(200, summary)
        except Exception as e:
            self._respond(500, {"error": str(e)})

    # ── 주간 성과 평가 (매주 월요일 08:00 KST) ───────────────────────────────

    def _run_evaluation(self):
        if not self._check_auth():
            return

        try:
            logger.info("=== 주간 성과 평가 시작 ===")

            from storage         import load_last_week_picks
            from evaluator       import evaluate_picks
            from telegram_sender import send_telegram_message

            last_week = load_last_week_picks()
            if not last_week:
                msg = "📋 *주간 성과 평가*\n지난주 추천 데이터가 없습니다."
                send_telegram_message(msg)
                self._respond(200, {"status": "skipped", "message": "지난주 데이터 없음"})
                return

            report = evaluate_picks(last_week)
            if report:
                send_telegram_message(report)
                logger.info("=== 주간 평가 완료 ===")
                self._respond(200, {"status": "success", "message": "평가 리포트 전송 완료"})
            else:
                self._respond(200, {"status": "skipped", "message": "평가 결과 없음"})

        except Exception as e:
            logger.error(f"평가 오류: {e}", exc_info=True)
            self._respond(500, {"error": str(e)})

    # ── 공통 ─────────────────────────────────────────────────────────────────

    def _check_auth(self) -> bool:
        auth_header  = self.headers.get("authorization", "")
        cron_secret  = os.environ.get("CRON_SECRET", "")
        if cron_secret and auth_header != f"Bearer {cron_secret}":
            self._respond(401, {"error": "Unauthorized"})
            return False
        return True

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        logger.info(fmt % args)
