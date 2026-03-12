"""
시장 데이터 수집 모듈 (최적화 버전)
- 배치 다운로드: yf.download()로 전 종목 1회 요청
- 타임아웃 가드: 8초 초과 시 수집 중단, 기수집 데이터로 분석
- 글로벌 뉴스: Google News RSS (거시경제 키워드 5~10건)
- 개별 종목 뉴스 수집 제거 (속도 최적화)
"""

import yfinance as yf
import pandas as pd
import time
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

US_INDICES = {
    "S&P500":           "^GSPC",
    "NASDAQ":           "^IXIC",
    "필라델피아 반도체": "^SOX",
    "다우존스":         "^DJI",
    "VIX(공포지수)":    "^VIX",
    "금(Gold)":         "GC=F",
    "달러인덱스(DXY)":  "DX-Y.NYB",
}

KR_STOCKS = {
    # 반도체
    "삼성전자":           "005930.KS",
    "SK하이닉스":         "000660.KS",
    "DB하이텍":           "000990.KS",
    "리노공업":           "058470.KS",
    # 2차전지
    "LG에너지솔루션":     "373220.KS",
    "삼성SDI":            "006400.KS",
    "에코프로비엠":       "247540.KQ",
    "포스코퓨처엠":       "003670.KS",
    # 바이오
    "삼성바이오로직스":   "207940.KS",
    "셀트리온":           "068270.KS",
    "유한양행":           "000100.KS",
    "HLB":                "028300.KQ",
    # IT/플랫폼
    "NAVER":              "035420.KS",
    "카카오":             "035720.KS",
    "크래프톤":           "259960.KS",
    # 자동차
    "현대차":             "005380.KS",
    "기아":               "000270.KS",
    "현대모비스":         "012330.KS",
    # 금융
    "KB금융":             "105560.KS",
    "신한지주":           "055550.KS",
    "하나금융지주":       "086790.KS",
    # 에너지/화학
    "LG화학":             "051910.KS",
    "한화솔루션":         "009830.KS",
    # 방산
    "한화에어로스페이스": "012450.KS",
    "LIG넥스원":          "079550.KS",
    "현대로템":           "064350.KS",
    # 조선
    "HD현대중공업":       "329180.KS",
    "삼성중공업":         "010140.KS",
    "한화오션":           "042660.KS",
}

KR_INDICES = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}

GEO_RISK_KEYWORDS = [
    "war", "nuclear", "military", "invasion", "missile", "attack",
    "sanctions", "crisis", "conflict", "Iran", "North Korea",
    "Ukraine", "Russia", "rate hike", "emergency", "collapse",
    "recession", "crash", "tariff", "trade war",
]

TIME_LIMIT = 55.0   # Vercel 60초 제한 대비 55초 안전선


# ── 기술적 지표 계산 ──────────────────────────────────────────────────────────

def _calc_rsi(closes: pd.Series, period: int = 14) -> float:
    delta    = closes.diff()
    gains    = delta.clip(lower=0)
    losses   = (-delta).clip(lower=0)
    avg_gain = gains.rolling(period).mean()
    avg_loss = losses.rolling(period).mean()
    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 1) if not pd.isna(val) else None


def _calc_macd(closes: pd.Series) -> dict:
    ema12  = closes.ewm(span=12, adjust=False).mean()
    ema26  = closes.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9,  adjust=False).mean()
    hist   = macd - signal
    return {
        "macd":      round(float(macd.iloc[-1]),   0),
        "signal":    round(float(signal.iloc[-1]), 0),
        "histogram": round(float(hist.iloc[-1]),   0),
    }


def _calc_ma(closes: pd.Series) -> dict:
    ma5  = closes.rolling(5).mean().iloc[-1]
    ma20 = closes.rolling(20).mean().iloc[-1]
    ma60 = closes.rolling(60).mean().iloc[-1] if len(closes) >= 60 else None
    result = {
        "ma5":  round(float(ma5),  0) if not pd.isna(ma5)  else None,
        "ma20": round(float(ma20), 0) if not pd.isna(ma20) else None,
        "ma60": round(float(ma60), 0) if (ma60 is not None and not pd.isna(ma60)) else None,
    }
    if all(v is not None for v in result.values()):
        result["golden_align"] = result["ma5"] > result["ma20"] > result["ma60"]
    else:
        result["golden_align"] = None
    return result


def _calc_bollinger(closes: pd.Series, period: int = 20) -> dict:
    ma    = closes.rolling(period).mean()
    std   = closes.rolling(period).std()
    upper = (ma + 2 * std).iloc[-1]
    lower = (ma - 2 * std).iloc[-1]
    mid   = ma.iloc[-1]
    if pd.isna(upper) or pd.isna(lower):
        return {"upper": None, "middle": None, "lower": None, "band_position": None}
    width = float(upper) - float(lower)
    last  = float(closes.iloc[-1])
    pos   = round((last - float(lower)) / width, 2) if width > 0 else 0.5
    return {
        "upper":         round(float(upper), 0),
        "middle":        round(float(mid),   0),
        "lower":         round(float(lower), 0),
        "band_position": pos,
    }


def _technicals_from_series(closes: pd.Series, volumes: pd.Series, ticker: str) -> dict:
    """종가/거래량 시리즈에서 모든 기술적 지표 계산"""
    closes  = closes.dropna()
    volumes = volumes.dropna()
    if len(closes) < 26:
        return {}
    last_close = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])
    return {
        "close":      round(last_close, 0),
        "prev_close": round(prev_close, 0),
        "change_pct": round((last_close - prev_close) / prev_close * 100, 2),
        "volume":     int(volumes.iloc[-1]) if not volumes.empty else 0,
        "rsi":        _calc_rsi(closes),
        "macd":       _calc_macd(closes),
        "ma":         _calc_ma(closes),
        "bollinger":  _calc_bollinger(closes),
        "ticker":     ticker,
    }


# ── 지정학적 리스크 수집 ──────────────────────────────────────────────────────

def collect_geopolitical_news() -> dict:
    """Google News RSS: 거시경제·지정학 키워드 헤드라인 (최대 10건)"""
    try:
        import feedparser
        url  = "https://news.google.com/rss/search?q=war+crisis+geopolitical+risk+economy&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)

        headlines  = []
        risk_count = 0
        for entry in feed.entries[:10]:
            title = entry.get("title", "")
            if not title:
                continue
            headlines.append(title)
            if any(kw.lower() in title.lower() for kw in GEO_RISK_KEYWORDS):
                risk_count += 1

        level = "높음" if risk_count >= 4 else "보통" if risk_count >= 2 else "낮음"
        logger.info(f"  지정학 뉴스: {len(headlines)}건, 위험 키워드 {risk_count}건 → {level}")
        return {"headlines": headlines[:7], "risk_count": risk_count, "risk_level": level}
    except Exception as e:
        logger.warning(f"지정학 뉴스 수집 실패: {e}")
        return {"headlines": [], "risk_count": 0, "risk_level": "알 수 없음"}


# ── 배치 수집 ─────────────────────────────────────────────────────────────────

def collect_us_indices() -> dict:
    """미 증시 + 안전자산 지수 배치 수집"""
    tickers = list(US_INDICES.values())
    names   = list(US_INDICES.keys())
    result  = {}
    try:
        raw = yf.download(tickers, period="5d", auto_adjust=True,
                          progress=False, threads=True)
        close_df = raw["Close"] if "Close" in raw.columns else raw.xs("Close", axis=1, level=0)
        for name, ticker in zip(names, tickers):
            try:
                col = close_df[ticker].dropna()
                if len(col) < 2:
                    continue
                change = (float(col.iloc[-1]) - float(col.iloc[-2])) / float(col.iloc[-2]) * 100
                result[name] = {"close": round(float(col.iloc[-1]), 2), "change_pct": round(change, 2)}
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"미 증시 배치 실패, 개별 시도: {e}")
        for name, ticker in zip(names, tickers):
            try:
                hist = yf.Ticker(ticker).history(period="5d")
                if len(hist) < 2:
                    continue
                c = hist["Close"]
                change = (float(c.iloc[-1]) - float(c.iloc[-2])) / float(c.iloc[-2]) * 100
                result[name] = {"close": round(float(c.iloc[-1]), 2), "change_pct": round(change, 2)}
            except Exception:
                pass
    logger.info(f"  미 증시 {len(result)}/{len(tickers)}개 수집")
    return result


def collect_kr_indices() -> dict:
    """KOSPI/KOSDAQ 배치 수집"""
    tickers = list(KR_INDICES.values())
    names   = list(KR_INDICES.keys())
    result  = {}
    try:
        raw = yf.download(tickers, period="5d", auto_adjust=True,
                          progress=False, threads=True)
        close_df = raw["Close"] if isinstance(raw.columns, pd.Index) else raw.xs("Close", axis=1, level=0)
        for name, ticker in zip(names, tickers):
            try:
                col = close_df[ticker].dropna()
                if len(col) < 2:
                    continue
                change = (float(col.iloc[-1]) - float(col.iloc[-2])) / float(col.iloc[-2]) * 100
                result[name] = {"close": round(float(col.iloc[-1]), 2), "change_pct": round(change, 2)}
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"한국 지수 배치 실패: {e}")
    return result


def collect_kr_stocks(start_time: float) -> dict:
    """
    한국 종목 배치 수집 + 기술적 지표 계산
    - yf.download() 1회 요청으로 전 종목 데이터 수신
    - 타임아웃 가드: 8초 초과 시 기수집 데이터만 반환
    """
    tickers = list(KR_STOCKS.values())
    names   = list(KR_STOCKS.keys())

    # ── 1회 배치 다운로드 ──
    logger.info("  한국 종목 배치 다운로드 중...")
    try:
        raw = yf.download(
            tickers, period="60d", auto_adjust=True,
            progress=False, threads=True, timeout=20,
        )
    except Exception as e:
        logger.warning(f"배치 다운로드 실패: {e}")
        raw = None

    result = {}

    if raw is not None and not raw.empty:
        try:
            # MultiIndex: (Price, Ticker) 또는 단일 Index
            if isinstance(raw.columns, pd.MultiIndex):
                close_df  = raw["Close"]
                volume_df = raw["Volume"]
            else:
                close_df  = raw[["Close"]]
                volume_df = raw[["Volume"]]

            for name, ticker in zip(names, tickers):
                if time.time() - start_time > TIME_LIMIT:
                    logger.warning(f"⏱ 타임아웃 가드 발동 ({len(result)}개 처리 후 중단)")
                    break
                try:
                    closes  = close_df[ticker].dropna()  if ticker in close_df.columns  else pd.Series(dtype=float)
                    volumes = volume_df[ticker].dropna() if ticker in volume_df.columns else pd.Series(dtype=float)
                    info = _technicals_from_series(closes, volumes, ticker)
                    if info:
                        result[name] = info
                except Exception as ex:
                    logger.debug(f"  {name} 지표 계산 실패: {ex}")
        except Exception as e:
            logger.warning(f"배치 데이터 파싱 실패: {e}")

    # 배치 실패 시 개별 수집 (타임아웃 가드 적용)
    if not result:
        logger.info("  개별 수집으로 폴백...")
        for name, ticker in zip(names, tickers):
            if time.time() - start_time > TIME_LIMIT:
                logger.warning(f"⏱ 타임아웃 가드 발동 ({len(result)}개 처리 후 중단)")
                break
            try:
                hist = yf.Ticker(ticker).history(period="60d")
                if hist.empty or len(hist) < 26:
                    continue
                info = _technicals_from_series(hist["Close"], hist["Volume"], ticker)
                if info:
                    result[name] = info
            except Exception:
                pass

    # ── 모멘텀 점수 정렬 → 상위 15개 ──
    def score(item):
        rsi     = item[1].get("rsi") or 50
        hist_v  = (item[1].get("macd") or {}).get("histogram", 0)
        ma      = item[1].get("ma") or {}
        vol     = item[1].get("volume", 0)
        return (
            (1 if 40 <= rsi <= 65 else 0)
            + (1 if hist_v > 0 else 0)
            + (1 if ma.get("golden_align") else 0),
            vol,
        )

    top15 = dict(sorted(result.items(), key=score, reverse=True)[:15])
    logger.info(f"  한국 종목: {len(result)}개 수집 → 상위 {len(top15)}개 선별")
    return top15


# ── 프롬프트 포맷터 ────────────────────────────────────────────────────────────

def format_market_data_for_prompt(market_data: dict) -> str:
    lines = [f"[분석 기준일: {datetime.now().strftime('%Y년 %m월 %d일')}]"]

    # 지정학적 리스크
    geo = market_data.get("geo_risk", {})
    lines.append(f"\n### 지정학적 리스크")
    lines.append(f"- 위험도: {geo.get('risk_level','알 수 없음')} (위험 키워드 {geo.get('risk_count',0)}건)")
    for h in geo.get("headlines", []):
        lines.append(f"  - {h}")

    # 미 증시 + 안전자산
    lines.append("\n### 전일 미 증시 지수 (금·달러 포함)")
    for name, info in market_data.get("us_indices", {}).items():
        sign = "+" if info["change_pct"] >= 0 else ""
        lines.append(f"- {name}: {info['close']:,.2f} ({sign}{info['change_pct']:.2f}%)")

    # 한국 지수
    lines.append("\n### 한국 증시 지수")
    for name, info in market_data.get("kr_indices", {}).items():
        sign = "+" if info["change_pct"] >= 0 else ""
        lines.append(f"- {name}: {info['close']:,.2f} ({sign}{info['change_pct']:.2f}%)")

    # 한국 종목 요약표
    lines.append("\n### 한국 주요 종목 (기술적 지표)")
    lines.append("종목명 | 종가 | 등락률 | RSI | MACD히스토 | MA정배열 | 볼린저위치")
    lines.append("---|---|---|---|---|---|---")
    for name, info in market_data.get("kr_stocks", {}).items():
        sign   = "+" if info["change_pct"] >= 0 else ""
        rsi    = info.get("rsi") or "-"
        hist_v = (info.get("macd") or {}).get("histogram", "-")
        ma     = info.get("ma") or {}
        golden = "정배열✓" if ma.get("golden_align") else ("역배열✗" if ma.get("golden_align") is False else "-")
        bb     = info.get("bollinger") or {}
        bb_pos = bb.get("band_position", "-")
        lines.append(
            f"{name} | {info['close']:,} | {sign}{info['change_pct']:.2f}% "
            f"| {rsi} | {hist_v} | {golden} | {bb_pos}"
        )

    # MA 상세
    lines.append("\n### 이동평균선 (MA5 / MA20 / MA60)")
    for name, info in market_data.get("kr_stocks", {}).items():
        ma = info.get("ma") or {}
        if any(ma.get(k) for k in ("ma5", "ma20", "ma60")):
            lines.append(
                f"- {name}: MA5={ma.get('ma5','-')}  "
                f"MA20={ma.get('ma20','-')}  MA60={ma.get('ma60','-') or '-'}"
            )

    # 볼린저 밴드 상세
    lines.append("\n### 볼린저 밴드 (상단/중간/하단)")
    for name, info in market_data.get("kr_stocks", {}).items():
        bb = info.get("bollinger") or {}
        if bb.get("upper"):
            lines.append(
                f"- {name}: 상단={bb['upper']:,}  중간={bb['middle']:,}  "
                f"하단={bb['lower']:,}  위치={bb.get('band_position','-')}"
            )

    return "\n".join(lines)


# ── 메인 수집 함수 ─────────────────────────────────────────────────────────────

def collect_market_data() -> dict:
    start_time = time.time()

    logger.info("① 지정학적 리스크 뉴스 수집...")
    geo_risk = collect_geopolitical_news()
    logger.info(f"   완료 ({time.time()-start_time:.1f}s)")

    logger.info("② 미 증시 지수 배치 수집...")
    us_indices = collect_us_indices()
    logger.info(f"   완료 ({time.time()-start_time:.1f}s)")

    logger.info("③ 한국 지수 수집...")
    kr_indices = collect_kr_indices()
    logger.info(f"   완료 ({time.time()-start_time:.1f}s)")

    logger.info("④ 한국 종목 배치 수집 + 기술적 지표...")
    kr_stocks = collect_kr_stocks(start_time)
    logger.info(f"   완료 ({time.time()-start_time:.1f}s)")

    market_data = {
        "geo_risk":     geo_risk,
        "us_indices":   us_indices,
        "kr_indices":   kr_indices,
        "kr_stocks":    kr_stocks,
        "collected_at": datetime.now().isoformat(),
        "elapsed_sec":  round(time.time() - start_time, 1),
    }
    market_data["prompt_text"] = format_market_data_for_prompt(market_data)
    logger.info(f"전체 데이터 수집 완료: {market_data['elapsed_sec']}초")
    return market_data
