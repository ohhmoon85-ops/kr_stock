"""
로컬 테스트 스크립트 - Vercel 배포 전 동작 확인용
실행: python test_local.py
"""

import os
import sys

# .env 파일 로드 (python-dotenv 사용)
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ .env 파일 로드 완료")
except ImportError:
    print("⚠️  python-dotenv 없음 - 환경변수 직접 설정 필요")

# 환경 변수 확인
required_vars = ["OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
missing = [v for v in required_vars if not os.environ.get(v)]
if missing:
    print(f"❌ 누락된 환경 변수: {', '.join(missing)}")
    print("   .env 파일을 생성하거나 환경 변수를 설정하세요 (.env.example 참고)")
    sys.exit(1)

print("✅ 환경 변수 확인 완료\n")

# sys.path 설정 (api 패키지 임포트용)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.data_collector import collect_market_data
from api.analyzer import generate_report
from api.telegram_sender import send_telegram_message


def test_data_collection():
    print("=" * 50)
    print("1단계: 시장 데이터 수집 테스트")
    print("=" * 50)
    data = collect_market_data()

    print("\n[미 증시 지수]")
    for name, info in data["us_indices"].items():
        print(f"  {name}: {info['close']:,.2f} ({info['change_pct']:+.2f}%)")

    print("\n[한국 지수]")
    for name, info in data["kr_indices"].items():
        print(f"  {name}: {info['close']:,.2f} ({info['change_pct']:+.2f}%)")

    print(f"\n[한국 종목] {len(data['kr_stocks'])}개 수집 완료")
    return data


def test_report_generation(market_data):
    print("\n" + "=" * 50)
    print("2단계: AI 리포트 생성 테스트")
    print("=" * 50)
    report = generate_report(market_data)
    print("\n[생성된 리포트 미리보기 (앞 500자)]")
    print(report[:500])
    print("...")
    return report


def test_telegram_send(report):
    print("\n" + "=" * 50)
    print("3단계: 텔레그램 전송 테스트")
    print("=" * 50)
    answer = input("실제 텔레그램으로 전송하시겠습니까? (y/N): ").strip().lower()
    if answer == "y":
        send_telegram_message(report)
        print("✅ 텔레그램 전송 완료!")
    else:
        print("⏭️  텔레그램 전송 건너뜀")


if __name__ == "__main__":
    try:
        data   = test_data_collection()
        report = test_report_generation(data)
        test_telegram_send(report)
        print("\n✅ 모든 테스트 완료!")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
