import os, json, datetime, requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

DAILY_LIMIT = 5
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

def get_korea_date():
    # 한국시간(UTC+9) 기준 날짜
    utc_now = datetime.datetime.utcnow()
    korea_now = utc_now + datetime.timedelta(hours=9)
    return korea_now.strftime("%Y-%m-%d")

def get_counter():
    today = get_korea_date()
    url = f"{SUPABASE_URL}/rest/v1/insight_counter?id=eq.1&select=date,count"
    res = requests.get(url, headers=supabase_headers(), timeout=5)
    rows = res.json()
    if not rows:
        return {"date": today, "count": 0}
    row = rows[0]
    if row["date"] != today:
        return {"date": today, "count": 0}
    return row

def set_counter(date, count):
    url = f"{SUPABASE_URL}/rest/v1/insight_counter?id=eq.1"
    requests.patch(url, headers=supabase_headers(),
                   json={"date": date, "count": count}, timeout=5)

def build_es_prompt(stats):
    total_gmv = stats.get("totalGMV", 0)
    conf_cnt = stats.get("confCnt", 0)
    avg_gmv = stats.get("avgGMV", 0)
    paid_gmv = stats.get("paidGMV", 0)
    unpaid_gmv = stats.get("unpaidGMV", 0)
    paid_ratio = round(paid_gmv / total_gmv * 100, 1) if total_gmv else 0
    unpaid_ratio = round(100 - paid_ratio, 1) if total_gmv else 0

    return f"""여기어때 B2B ES사업부 전체 실적 데이터 요약 (아래 수치를 그대로 사용하고 재계산하지 마세요):
- 확정 GMV: {total_gmv:,}원 (= {total_gmv/100000000:.2f}억원)
- 확정 건수: {conf_cnt:,}건
- 취소율: {stats.get("cancelRate", "0%")} (취소 {stats.get("cancelCnt", 0):,}건 / 전체 {stats.get("totalCnt", 0):,}건)
- 건당 평균 GMV: {avg_gmv:,}원
- 활성 기업수: {stats.get("corpCnt", 0)}개
- 전월 대비 GMV: {stats.get("momGMV", "N/A")}
- 전주 대비 GMV: {stats.get("wowGMV", "N/A")}
- GMV Top3 기업: {stats.get("top3Corps", "N/A")}
- 카테고리별 GMV: {stats.get("catGMVRaw", "N/A")}
- 쿠폰 GMV 할인율: {stats.get("couponRate", "N/A")}
- 유상멤버 GMV: {paid_gmv:,}원 ({paid_ratio}%) / 비유상: {unpaid_gmv:,}원 ({unpaid_ratio}%)
- 데이터 기간: {stats.get("dateRange", "N/A")}

위 데이터를 바탕으로 아래 3가지를 간결하게 작성해주세요.

1. **핵심 현황** (2~3줄): 가장 주목할 수치와 변화
2. **주요 시사점** (2~3줄): 원인 추정 및 주의할 기업/카테고리
3. **상부 보고용 1문단** (3~4줄): 임원에게 보고하는 형식으로, 수치 포함

실무 중심으로, 불필요한 서두 없이 바로 내용만 작성해주세요."""

def build_biz_prompt(stats):
    total_gmv = stats.get("totalGMV", 0)
    conf_cnt = stats.get("confCnt", 0)
    avg_gmv = stats.get("avgGMV", 0)
    comply_n = stats.get("complyN", 0)
    non_comply_n = stats.get("nonComplyN", 0)
    comply_total = comply_n + non_comply_n
    comply_rate = round(comply_n / comply_total * 100, 1) if comply_total else 0
    biz_pt = stats.get("bizPointTotal", 0)

    return f"""여기어때 B2B ES사업부 출장 실적 데이터 요약 (아래 수치를 그대로 사용하고 재계산하지 마세요):
- 확정 GMV: {total_gmv:,}원 (= {total_gmv/100000000:.2f}억원)
- 확정 건수: {conf_cnt:,}건
- 취소율: {stats.get("cancelRate", "0%")} (취소 {stats.get("cancelCnt", 0):,}건 / 전체 {stats.get("totalCnt", 0):,}건)
- 건당 평균 GMV: {avg_gmv:,}원
- 활성 기업수: {stats.get("corpCnt", 0)}개
- 전월 대비 GMV: {stats.get("momGMV", "N/A")}
- 전주 대비 GMV: {stats.get("wowGMV", "N/A")}
- GMV Top3 기업: {stats.get("top3Corps", "N/A")}
- 카테고리별 GMV: {stats.get("catGMVRaw", "N/A")}
- 주요 결제방식 Top3: {stats.get("topPayMethod", "N/A")}
- 규정등록 건수: {stats.get("ruleRegCorps", 0)}건
- 규정준수율: {comply_rate}% (준수 {comply_n}건 / 미준수 {non_comply_n}건)
- 비즈포인트 사용액: {biz_pt:,}원
- 데이터 기간: {stats.get("dateRange", "N/A")}

위 출장 데이터를 바탕으로 아래 4가지를 간결하게 작성해주세요.

1. **핵심 현황** (2~3줄): GMV, 건수, 수치변화, 주요 결제방식 중심으로 가장 주목할 수치
2. **규정 준수 현황** (2~3줄): 준수율 평가, 미준수 기업 관리 필요성 시사점
3. **주요 시사점** (2~3줄): 카테고리/기업 관점 원인 추정 및 액션 포인트
4. **상부 보고용 1문단** (3~4줄): 임원 보고 형식, 출장 규정 준수 현황 포함

실무 중심으로, 불필요한 서두 없이 바로 내용만 작성해주세요."""

@app.route("/health")
def health():
    return jsonify({"status": "ok", "korea_date": get_korea_date()})

@app.route("/insight/status")
def status():
    try:
        counter = get_counter()
        remaining = max(0, DAILY_LIMIT - counter["count"])
        return jsonify({
            "date": counter["date"],
            "used": counter["count"],
            "limit": DAILY_LIMIT,
            "remaining": remaining
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/insight/generate", methods=["POST"])
def generate():
    try:
        counter = get_counter()
    except Exception as e:
        return jsonify({"error": "db_error", "message": str(e)}), 500

    if counter["count"] >= DAILY_LIMIT:
        return jsonify({
            "error": "daily_limit",
            "message": f"오늘 인사이트 생성 횟수({DAILY_LIMIT}회)를 모두 사용했습니다. (한국시간 기준 자정 초기화)",
            "remaining": 0
        }), 429

    data = request.json or {}
    stats = data.get("stats", {})
    mode = stats.get("mode", "es")

    if mode == "biz":
        prompt = build_biz_prompt(stats)
    else:
        prompt = build_es_prompt(stats)

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        result = message.content[0].text

        new_count = counter["count"] + 1
        set_counter(counter["date"], new_count)

        return jsonify({
            "insight": result,
            "remaining": DAILY_LIMIT - new_count,
            "used": new_count,
            "limit": DAILY_LIMIT
        })

    except anthropic.APIError as e:
        return jsonify({"error": "api_error", "message": str(e)}), 500
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
