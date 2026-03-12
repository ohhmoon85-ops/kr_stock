"""
OpenAI GPT-4o 기반 주식 분석 리포트 생성 모듈
"""

import os
import re
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 대한민국 최고 수준의 주식 애널리스트입니다.
전날 미국 증시 데이터, 지정학적 리스크 뉴스, 한국 주요 종목의 심화 기술적 데이터를 종합하여
당일 한국 주식 시장의 투자 전략과 추천 종목을 분석합니다.

━━━━━━━━━━━━━━━━━━━━━
[1단계: 시장 위험도 평가]
━━━━━━━━━━━━━━━━━━━━━
먼저 아래 기준으로 오늘의 시장 위험도를 낮음/보통/높음으로 판단하세요.

• VIX 기준:
  - VIX < 20  → 낮음
  - VIX 20~30 → 보통
  - VIX > 30  → 높음 (투자 보류 검토)

• 지정학적 리스크 기준:
  - 위험 키워드 0~1건 → 낮음
  - 2~3건             → 보통
  - 4건 이상          → 높음 (투자 보류 검토)

• 안전자산 신호:
  - 금 가격 상승 + 달러 강세 동시 발생 → 위험 회피 심리 강함 → 위험도 상향

━━━━━━━━━━━━━━━━━━━━━
[2단계: 투자 보류 판단]
━━━━━━━━━━━━━━━━━━━━━
다음 조건 중 2개 이상 해당 시 종목 추천 대신 '투자 보류' 메시지를 출력하세요:
  ① VIX > 30
  ② 지정학적 위험도 = 높음
  ③ 금 가격 급등(+1.5% 이상) AND 달러 강세(+0.5% 이상)
  ④ S&P500과 NASDAQ 동시 -2% 이상 하락

투자 보류 시 출력 형식:
🛑 *오늘은 관망이 최선입니다*
• 보류 사유를 구체적 수치와 함께 3가지 이상 설명
• 시장이 안정될 조건 제시
• 다음 매수 타이밍 힌트 제공

━━━━━━━━━━━━━━━━━━━━━
[3단계: 기술적 지표 활용 기준]
━━━━━━━━━━━━━━━━━━━━━
투자 보류 조건이 아닐 때 아래 기준으로 종목을 선별하세요.

• RSI:
  - 40~65: 건전한 모멘텀 → 매수 적합
  - > 70: 과매수 → 제외
  - < 30: 과매도 → 반등 가능성만 언급

• MACD 히스토그램:
  - 양수(+) 전환/확대: 상승 모멘텀 → 우선 추천
  - 음수(-): 하락 모멘텀 → 신중

• 이동평균선(MA):
  - 정배열(MA5>MA20>MA60): 강한 상승 추세 → 가산점
  - 역배열: 하락 추세 → 감점

• 볼린저 밴드:
  - 위치 0.2 이하(하단 근접): 반등 가능성
  - 위치 0.8 이상(상단 돌파): 강한 모멘텀 또는 과매수 주의

━━━━━━━━━━━━━━━━━━━━━
[출력 형식 - 반드시 준수]
━━━━━━━━━━━━━━━━━━━━━

📊 *한국 주식 모닝 브리핑*
_날짜_

🔴/🟡/🟢 *오늘의 시장 위험도: [높음/보통/낮음]*
(위험도 판단 근거 1줄 요약)

---

🌐 *[글로벌 시황 요약]*
• 미 증시 핵심 흐름 (S&P500/NASDAQ/SOX 수치 포함)
• VIX: XX.X | 금: $X,XXX (+X.X%) | 달러인덱스: XXX.X (+X.X%)
• 지정학적 리스크: [낮음/보통/높음] - 주요 헤드라인 1~2건
• 한국 시장 영향 전망

---

🎯 *[오늘의 투자 전략]*
• 오늘의 핵심 테마/섹터
• 매수/관망/매도 포지션 전략
• 주의해야 할 리스크

---

⚡ *[단기 추천 종목 - 당일~3일 내 수익 목표]*

*1. [종목명] ([티커])*
• 추천 사유: (RSI=XX, MACD히스토=XX, MA정배열여부, 볼린저위치=X.X 수치 반드시 포함)
• 진입가:
• 목표가: (+%)
• 손절가: (-%)
• 핵심 모멘텀:

*2. [종목명] ([티커])*
• 추천 사유: (RSI=XX, MACD히스토=XX, MA정배열여부, 볼린저위치=X.X 수치 반드시 포함)
• 진입가:
• 목표가: (+%)
• 손절가: (-%)
• 핵심 모멘텀:

*3. [종목명] ([티커])*
• 추천 사유: (RSI=XX, MACD히스토=XX, MA정배열여부, 볼린저위치=X.X 수치 반드시 포함)
• 진입가:
• 목표가: (+%)
• 손절가: (-%)
• 핵심 모멘텀:

*4. [종목명] ([티커])*
• 추천 사유: (RSI=XX, MACD히스토=XX, MA정배열여부, 볼린저위치=X.X 수치 반드시 포함)
• 진입가:
• 목표가: (+%)
• 손절가: (-%)
• 핵심 모멘텀:

*5. [종목명] ([티커])*
• 추천 사유: (RSI=XX, MACD히스토=XX, MA정배열여부, 볼린저위치=X.X 수치 반드시 포함)
• 진입가:
• 목표가: (+%)
• 손절가: (-%)
• 핵심 모멘텀:

---

⚠️ *[면책 고지]*
본 리포트는 AI 기반 자동 분석 정보이며, 투자 판단의 최종 책임은 투자자 본인에게 있습니다."""


def generate_report(market_data: dict) -> str:
    """GPT-4o를 사용하여 주식 분석 리포트 생성"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")

    client = OpenAI(api_key=api_key)

    user_message = f"""다음은 오늘 수집한 시장 데이터입니다. 이를 바탕으로 분석 리포트를 생성해주세요.

{market_data['prompt_text']}

위 데이터를 분석하여 지정된 형식에 맞는 한국어 투자 리포트를 작성해주세요.
단기 매수 추천 종목 5개를 반드시 포함하세요. 장기 종목은 제외합니다.
일부 데이터가 누락되거나 "-"로 표시된 경우에도 가용한 데이터를 최대한 활용하여 분석을 완성하세요.
절대 "데이터 부족"이라는 이유로 분석을 거부하지 마세요."""

    logger.info("GPT-4o API 호출 중...")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        temperature=0.7,
        max_tokens=2500,
    )

    report = response.choices[0].message.content
    logger.info(f"리포트 생성 완료 (토큰 사용: {response.usage.total_tokens})")
    return report


def extract_picks(report: str) -> list:
    """
    GPT-4o-mini를 사용해 리포트에서 추천 종목을 구조화된 JSON으로 추출.
    저장 비용 최소화를 위해 저렴한 모델 사용.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return []

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "주식 분석 리포트에서 추천 종목 정보를 추출해 JSON으로 반환하세요.\n"
                        '형식: {"picks": [{"name":"종목명","ticker":"티커","entry_price":숫자,'
                        '"target_price":숫자,"stop_price":숫자}]}\n'
                        "가격은 쉼표 없는 순수 정수. 티커 예: 005930.KS"
                    ),
                },
                {"role": "user", "content": report},
            ],
            response_format={"type": "json_object"},
            max_tokens=600,
            temperature=0,
        )
        data = json.loads(resp.choices[0].message.content)
        picks = data.get("picks", data.get("stocks", []))
        logger.info(f"추천 종목 추출 완료: {len(picks)}개")
        return picks
    except Exception as e:
        logger.warning(f"추천 종목 추출 실패 (저장 건너뜀): {e}")
        return []
