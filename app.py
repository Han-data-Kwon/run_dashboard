import os, json, datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

DAILY_LIMIT = 5
COUNTER_FILE = "/tmp/insight_counter.json"

def load_counter():
    today = datetime.date.today().isoformat()
    try:
        with open(COUNTER_FILE, "r") as f:
            data = json.load(f)
        if data.get("date") != today:
            return {"date": today, "count": 0}
        return data
    except Exception:
        return {"date": today, "count": 0}

def save_counter(data):
    try:
        with open(COUNTER_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/insight/status")
def status():
    counter = load_counter()
    remaining = max(0, DAILY_LIMIT - counter["count"])
    return jsonify({
        "date": counter["date"],
        "used": counter["count"],
        "limit": DAILY_LIMIT,
        "remaining": remaining
    })

@app.route("/insight/generate", methods=["POST"])
def generate():
    counter = load_counter()
    if counter["count"] >= DAILY_LIMIT:
        return jsonify({
            "error": "daily_limit",
            "message": f"오늘 인사이트 생성 횟수({DAILY_LIMIT}회)를 모두 사용했습니다. 내일 다시 시도해주세요.",
            "remaining": 0
        }), 429

    data = request.json or {}
    stats = data.get("stats", {})

    # 핵심 지표만 프롬프트에 담아 토큰 최소화
    prompt = f"""여기어때 B2B ES사업부 실적 데이터 요약:
- 확정 GMV: {stats.get('totalGMV', 0):,}원
- 확정 건수: {stats.get('confCnt', 0):,}건
- 취소율: {stats.get('cancelRate', '0%')}
- 건당 평균 GMV: {stats.get('avgGMV', 0):,}원
- 활성 기업수: {stats.get('corpCnt', 0)}개
- 전월 대비 GMV: {stats.get('momGMV', 'N/A')}
- 전주 대비 GMV: {stats.get('wowGMV', 'N/A')}
- GMV Top3 기업: {stats.get('top3Corps', 'N/A')}
- 카테고리별 GMV: {stats.get('catGMV', 'N/A')}
- 쿠폰 사용률: {stats.get('couponRate', 'N/A')}
- 유상멤버 GMV 비중: {stats.get('paidRatio', 'N/A')}
- 데이터 기간: {stats.get('dateRange', 'N/A')}

위 데이터를 바탕으로 아래 3가지를 간결하게 작성해주세요.

1. **핵심 현황** (2~3줄): 가장 주목할 수치와 변화
2. **주요 시사점** (2~3줄): 원인 추정 및 주의할 기업/카테고리
3. **상부 보고용 1문단** (3~4줄): 임원에게 보고하는 형식으로, 수치 포함

실무 중심으로, 불필요한 서두 없이 바로 내용만 작성해주세요."""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        result = message.content[0].text

        counter["count"] += 1
        save_counter(counter)

        return jsonify({
            "insight": result,
            "remaining": DAILY_LIMIT - counter["count"],
            "used": counter["count"],
            "limit": DAILY_LIMIT
        })

    except anthropic.APIError as e:
        return jsonify({"error": "api_error", "message": str(e)}), 500
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
