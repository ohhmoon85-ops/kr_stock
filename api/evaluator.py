"""
주간 추천 종목 성과 평가 모듈
매주 월요일 08:00 KST 실행 → 7일 전 추천 종목의 수익률 평가 후 텔레그램 전송
"""

import yfinance as yf
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def evaluate_picks(entry: dict) -> str | None:
    """
    entry: {"date": "YYYY-MM-DD", "picks": [...]}
    각 pick: {"name", "ticker", "entry_price", "target_price", "stop_price"}

    반환: 텔레그램용 마크다운 문자열 (실패 시 None)
    """
    if not entry:
        return None

    picks      = entry.get("picks", [])
    pick_date  = entry.get("date", "알 수 없음")
    eval_date  = datetime.now().strftime("%Y-%m-%d")

    results    = []
    wins       = 0
    target_hit = 0
    stop_hit   = 0

    for pick in picks:
        ticker       = pick.get("ticker")
        entry_price  = pick.get("entry_price")
        target_price = pick.get("target_price")
        stop_price   = pick.get("stop_price")
        name         = pick.get("name", ticker)

        if not ticker or not entry_price:
            continue

        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if hist.empty:
                continue
            current = float(hist["Close"].iloc[-1])
            week_high = float(hist["High"].max())
            week_low  = float(hist["Low"].min())
            pnl_pct   = (current - entry_price) / entry_price * 100

            # 상태 판단
            if target_price and week_high >= target_price:
                status = "🎯 목표가 달성"
                wins      += 1
                target_hit += 1
            elif stop_price and week_low <= stop_price:
                status = "🛑 손절가 터치"
                stop_hit += 1
            elif pnl_pct > 0:
                status = "✅ 수익 중"
                wins   += 1
            else:
                status = "📉 손실 중"

            results.append({
                "name":    name,
                "ticker":  ticker,
                "entry":   entry_price,
                "current": current,
                "pnl_pct": round(pnl_pct, 2),
                "status":  status,
            })

        except Exception as e:
            logger.warning(f"{ticker} 평가 실패: {e}")

    if not results:
        return None

    total    = len(results)
    win_rate = wins / total * 100 if total else 0

    # ── 리포트 작성 ────────────────────────────────────────────────────────
    lines = [
        "📋 *주간 추천 종목 성과 평가*",
        f"_추천일: {pick_date}  →  평가일: {eval_date}_",
        "",
        "---",
        "",
    ]

    for r in results:
        sign = "+" if r["pnl_pct"] >= 0 else ""
        lines += [
            f"*{r['name']}* `{r['ticker']}`",
            f"• 진입가: {r['entry']:,}원 → 현재가: {r['current']:,.0f}원",
            f"• 수익률: *{sign}{r['pnl_pct']:.2f}%*  {r['status']}",
            "",
        ]

    lines += [
        "---",
        "",
        f"📊 *종합 결과*",
        f"• 수익 종목: {wins}/{total}개",
        f"• 적중률: *{win_rate:.0f}%*",
        f"• 목표가 달성: {target_hit}개  |  손절 터치: {stop_hit}개",
        "",
        "⚠️ _본 평가는 AI 자동 분석이며 실제 매매 결과와 다를 수 있습니다._",
    ]

    return "\n".join(lines)
