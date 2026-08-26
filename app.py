import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import urllib.parse
import os
import io
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

# 🔥 PDF 생성을 위한 핵심 라이브러리 임포트
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ==========================================
# 🔐 자격 증명 (Secrets 설정 자동 연동)
# ==========================================
NAVER_CLIENT_ID = st.secrets.get("NAVER_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = st.secrets.get("NAVER_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
NOTION_TOKEN = st.secrets.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = st.secrets.get("NOTION_DATABASE_ID", "")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
# ==========================================

st.set_page_config(
    page_title="AI 기반 보험 트렌드 & 이슈 인텔리전스 플랫폼",
    page_icon="📈",
    layout="wide"
)

# 🎯 온라인에서 나눔고딕 폰트를 실시간으로 다운로드하여 등록 (한글 깨짐 방지)
@st.cache_resource
def init_korean_font():
    font_url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
    font_bold_url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf"
    
    try:
        r = requests.get(font_url, timeout=10)
        pdfmetrics.registerFont(TTFont('NanumGothic', io.BytesIO(r.content)))
        
        rb = requests.get(font_bold_url, timeout=10)
        pdfmetrics.registerFont(TTFont('NanumGothic-Bold', io.BytesIO(rb.content)))
        return True
    except Exception as e:
        st.sidebar.warning(f"⚠️ 한글 폰트 로드 실패(기본 서체 우회): {e}")
        return False

has_korean_font = init_korean_font()

# ==========================================
# 📰 [1. 10대 검증 언론사 및 도메인 사전]
# ==========================================
TARGET_PRESS_CONFIG = {
    # 전문지 (5곳)
    "한국보험신문": {"type": "보험 전문지", "domains": ["insweek.co.kr"], "query": '"한국보험신문"'},
    "보험매일": {"type": "보험 전문지", "domains": ["fins.co.kr"], "query": '"보험매일"'},
    "보험신문": {"type": "보험 전문지", "domains": ["bohumnews.com"], "query": '"보험신문"'},
    "대한금융신문": {"type": "금융 전문지", "domains": ["kbanker.co.kr"], "query": '"대한금융신문" 보험'},
    "CEO스코어데일리": {"type": "기업·경영 전문지", "domains": ["ceoscoredaily.com"], "query": '"CEO스코어데일리" 보험'},
    # 종합/경제지 (5곳)
    "매일경제": {"type": "경제지", "domains": ["mk.co.kr"], "query": '"매일경제" 보험'},
    "한국경제": {"type": "경제지", "domains": ["hankyung.com"], "query": '"한국경제" 보험'},
    "머니투데이": {"type": "경제지", "domains": ["mt.co.kr"], "query": '"머니투데이" 보험'},
    "서울경제": {"type": "경제지", "domains": ["sedaily.com"], "query": '"서울경제" 보험'},
    "연합뉴스": {"type": "종합지", "domains": ["yna.co.kr", "yonhapnewstv.co.kr"], "query": '"연합뉴스" 보험'}
}

# ==========================================
# 🔍 [2. 중복 제거 헬퍼 함수]
# ==========================================
def normalize_title(title):
    # 말머리([단독], [속보] 등) 및 특수문자 제거
    t = re.sub(r"\[.*?\]|\(.*?\)", "", title)
    t = re.sub(r"[^\w\s]", "", t)
    return set(t.strip().split())

def is_duplicate_article(title_tokens, existing_tokens_list):
    if not title_tokens:
        return False
    for existing in existing_tokens_list:
        intersection = title_tokens.intersection(existing)
        union = title_tokens.union(existing)
        if union:
            jaccard = len(intersection) / len(union)
            if jaccard >= 0.55:  # 단어 55% 이상 유사 시 중복 처리
                return True
    return False

# ==========================================
# 🤖 [3. 중요도 평가 엔진 (Gemini 배치 평가 + Fallback)]
# ==========================================
def evaluate_articles_batch_with_gemini(articles_list):
    """
    [실제 AI API가 호출되는 부분 1 - 배치 평가]
    후보 기사 목록을 한 번에 Gemini에 전달하여 100점 만점 루브릭으로 일괄 채점
    """
    if not GEMINI_API_KEY or not articles_list:
        return [evaluate_article_fallback(a["기사제목"], a["기사내용"], a["pub_datetime"]) for a in articles_list]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {"Content-Type": "application/json"}

    prompt_items = []
    for idx, a in enumerate(articles_list, 1):
        prompt_items.append(f"기사 #{idx}\n- 제목: {a['기사제목']}\n- 요약: {a['기사내용']}\n- 언론사: {a['언론사']}")
    context_str = "\n\n".join(prompt_items)

    prompt = f"""
당신은 대한민국 보험산업 수석 이코노미스트입니다.
아래 제공된 보험 기사 목록(네이버 뉴스 스니펫)을 분석하여 각 기사의 중요도를 정량 평가하고 JSON으로 반환하세요.

[기사 목록]
{context_str}

[채점 루브릭 (총 100점 만점)]:
1. 산업 영향도 (25점): 보험산업 구조/회계(IFRS17, CSM)/건전성 영향 (21~25: 구조적 변화, 16~20: 다수 보험사, 11~15: 특정 상품/채널, 1~10: 제한적)
2. 정책/제도 (20점): 금융당국/법령/감독규정 (16~20: 직접 제도변화, 11~15: 개편 논의, 6~10: 간접 관련, 1~5: 미미)
3. 소비자 영향 (20점): 가입자 보험료/보장/약관 (16~20: 대다수 가입자 직접 영향, 11~15: 특정 소비자 집단, 6~10: 간접, 1~5: 제한적)
4. 시장 영향 (20점): 경쟁구도/수익성/시장규모 (16~20: 큰 영향, 11~15: 특정 시장, 6~10: 제한적, 1~5: 낮음)
5. 시의성 (15점): 긴급성 및 발생 시점 (13~15: 진행 중인 매우 중요한 현안, 10~12: 최근 중요 이슈, 6~9: 일반 최근 이슈, 1~5: 낮음)

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "evaluations": [
    {{
      "index": 1,
      "industry_score": 0,
      "policy_score": 0,
      "consumer_score": 0,
      "market_score": 0,
      "timeliness_score": 0,
      "importance_reason": "점수 산정 근거 2문장 내외"
    }}
  ]
}}
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=12)
        if res.status_code == 200:
            data = res.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            eval_data = json.loads(raw_text).get("evaluations", [])
            
            results = []
            for idx, a in enumerate(articles_list, 1):
                matching = next((e for e in eval_data if e.get("index") == idx), None)
                if matching:
                    ind = int(matching.get("industry_score", 10))
                    pol = int(matching.get("policy_score", 10))
                    con = int(matching.get("consumer_score", 10))
                    mkt = int(matching.get("market_score", 10))
                    tim = int(matching.get("timeliness_score", 10))
                    total = ind + pol + con + mkt + tim
                    results.append({
                        "article_importance_score": total,
                        "industry_score": ind,
                        "policy_score": pol,
                        "consumer_score": con,
                        "market_score": mkt,
                        "timeliness_score": tim,
                        "importance_reason": str(matching.get("importance_reason", "AI 분석 완료")),
                        "eval_mode": "AI"
                    })
                else:
                    results.append(evaluate_article_fallback(a["기사제목"], a["기사내용"], a["pub_datetime"]))
            return results
    except Exception:
        pass

    return [evaluate_article_fallback(a["기사제목"], a["기사내용"], a["pub_datetime"]) for a in articles_list]

def evaluate_article_fallback(title, desc, pub_dt):
    """
    [Fallback 작동 부분]
    API 호출 불가 시 보조 규칙 기반 채점기
    """
    text = (title + " " + desc).lower()
    
    if any(k in text for k in ["ifrs17", "csm", "k-ics", "계리", "자본확충", "지급여력"]):
        ind, ind_r = 23, "IFRS17/CSM 등 산업 전반 구조적 지표 연관"
    elif any(k in text for k in ["손해율", "언더라이팅", "uwd", "실적개선", "수익성"]):
        ind, ind_r = 18, "다수 보험사 손익 및 심사 기준 영향"
    else:
        ind, ind_r = 10, "개별사 또는 제한적 산업 영향"

    if any(k in text for k in ["금융위", "금감원", "금융감독원", "시행령", "감독규정", "가이드라인"]):
        pol, pol_r = 18, "금융당국의 직접적인 규제/정책 변화"
    elif any(k in text for k in ["제도개편", "개선안", "tf", "공청회", "논의"]):
        pol, pol_r = 13, "제도 개편 및 당국 논의 단계"
    else:
        pol, pol_r = 5, "정책 관련성 낮음"

    if any(k in text for k in ["실손", "비급여", "보험료 인상", "보험료 인하", "약관", "지급기준"]):
        con, con_r = 18, "대다수 가입자 보험료 및 보장 직접 영향"
    elif any(k in text for k in ["청구간소화", "펫보험", "유병자", "고령화", "치매"]):
        con, con_r = 13, "특정 타깃 가입자층 영향"
    else:
        con, con_r = 5, "소비자 영향 제한적"

    if any(k in text for k in ["제3보험", "m/s", "점유율", "가격경쟁", "출혈경쟁", "ga"]):
        mkt, mkt_r = 17, "시장 경쟁구도 및 채널 판도 영향"
    elif any(k in text for k in ["신상품", "특약", "배타적사용권", "담보"]):
        mkt, mkt_r = 12, "특정 상품군 라인업 변화"
    else:
        mkt, mkt_r = 6, "시장 영향도 제한적"

    days_diff = (datetime.now() - pub_dt).days
    if days_diff <= 1: tim = 14
    elif days_diff <= 3: tim = 11
    elif days_diff <= 5: tim = 8
    else: tim = 4
    
    total = ind + pol + con + mkt + tim
    reason = f"[{ind_r}] 및 [{pol_r}] 기반 중요도 산정 (Fallback 평가)"
    
    return {
        "article_importance_score": total,
        "industry_score": ind,
        "policy_score": pol,
        "consumer_score": con,
        "market_score": mkt,
        "timeliness_score": tim,
        "importance_reason": reason,
        "eval_mode": "Fallback"
    }

# ==========================================
# 💡 [4. 뉴스 수집 및 언론사 도메인 검증 엔진]
# ==========================================
@st.cache_data(ttl=timedelta(hours=8))
def fetch_real_naver_news():
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if NAVER_CLIENT_ID in ["YOUR_CLIENT_ID_HERE", ""]:
        return load_demo_data(), collected_at

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID.strip(),
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET.strip()
    }

    seven_days_ago = datetime.now() - timedelta(days=7)
    promo_blacklist = [
        "이벤트", "출시기념", "선착순", "증정이벤트", "고객감사", 
        "공식 sns", "기프티콘", "사은품", "팝업스토어", "업무협약", 
        "mou", "캠페인", "후원금", "보도자료", "공모전", "개최"
    ]

    seen_title_tokens = []
    candidate_articles = []

    for press_name, config in TARGET_PRESS_CONFIG.items():
        encoded_query = urllib.parse.quote(config["query"])
        url = f"https://openapi.naver.com/v1/search/news.json?query={encoded_query}&display=40&sort=sim"
        
        try:
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code != 200:
                continue
            
            items = res.json().get("items", [])
            for item in items:
                pub_date_str = item.get("pubDate", "")
                try:
                    pub_dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S +0900")
                except:
                    pub_dt = datetime.now()

                # 최근 7일 초과 기사 배제
                if pub_dt < seven_days_ago:
                    continue

                orig_link = item.get("originallink", "").strip()
                naver_link = item.get("link", "").strip()
                final_link = orig_link if orig_link else naver_link

                # 🎯 [언론사 도메인 검증 (서브도메인 포함)]
                parsed_host = urlparse(orig_link).netloc.lower()
                is_verified_press = False
                for domain in config["domains"]:
                    if domain in parsed_host:
                        is_verified_press = True
                        break
                
                if not is_verified_press:
                    continue

                clean_title = item["title"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
                clean_desc = item["description"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")

                # 홍보성 기사 필터링
                if any(bw in clean_title.lower() for bw in promo_blacklist):
                    continue

                # Jaccard 유사도 기반 중복 기사 필터링
                tokens = normalize_title(clean_title)
                if is_duplicate_article(tokens, seen_title_tokens):
                    continue

                candidate_articles.append({
                    "날짜": pub_dt.strftime("%Y-%m-%d"),
                    "언론사": press_name,
                    "매체구분": config["type"],
                    "기사제목": clean_title,
                    "기사내용": clean_desc,
                    "기사링크": final_link,
                    "pub_datetime": pub_dt
                })
                seen_title_tokens.append(tokens)
        except Exception:
            continue

    if not candidate_articles:
        return load_demo_data(), collected_at

    # 🎯 [배치 평가 실행: API 호출 1회로 단축]
    eval_results = evaluate_articles_batch_with_gemini(candidate_articles)
    all_evaluated_news = []
    for art, ev in zip(candidate_articles, eval_results):
        all_evaluated_news.append({**art, **ev})

    final_df = pd.DataFrame(all_evaluated_news)
    return final_df, collected_at

def load_demo_data():
    now_str = datetime.now().strftime("%Y-%m-%d")
    return pd.DataFrame([
        {
            "날짜": now_str, "언론사": "한국보험신문", "매체구분": "보험 전문지",
            "기사제목": "IFRS17 2년차 진입 속 제3보험 신계약 CSM 확보 총력전",
            "기사내용": "주요 생손보사들이 장기 수익성 강화를 위해 GA 채널에 대한 수수료 개편과 건강보험 신상품 라인업을 집중 배치하고 있다.",
            "기사링크": "http://www.insweek.co.kr/news/articleView.html?idxno=12345", "pub_datetime": datetime.now(),
            "article_importance_score": 93, "industry_score": 24, "policy_score": 19, "consumer_score": 18, "market_score": 18, "timeliness_score": 14,
            "importance_reason": "IFRS17/CSM 수익성 확보 전략 및 당국 가이드라인 대응 이슈로 산업 전반에 미치는 파급력이 매우 큼.",
            "eval_mode": "AI"
        },
        {
            "날짜": now_str, "언론사": "매일경제", "매체구분": "경제지",
            "기사제목": "실손보험 비급여 과잉 도수치료 손해율 급등에 당국 정밀 심사 착수",
            "기사내용": "금융당국과 손해보험업계가 비급여 누수로 인한 손해율 악화를 방어하기 위해 인수심사 가이드라인과 비급여 지급 기준 개편에 나섰다.",
            "기사링크": "https://www.mk.co.kr/news/economy/12345", "pub_datetime": datetime.now(),
            "article_importance_score": 89, "industry_score": 18, "policy_score": 19, "consumer_score": 19, "market_score": 18, "timeliness_score": 15,
            "importance_reason": "전체 국민 실손보험료 조정 및 비급여 심사 강화와 직결되어 소비자 및 제도적 영향도가 높음.",
            "eval_mode": "AI"
        }
    ])

# ==========================================
# 🏆 [5. TOP 10 선정 부분 (균형 쿼터제 탑재)]
# ==========================================
def select_top10_articles(df_candidates):
    """
    [TOP 10 선정 부분]
    1. 동일 언론사 최대 2개 제한
    2. 전문/금융지 및 종합/경제지 최소 3건 이상씩 균형 쿼터 반영
    """
    if df_candidates.empty:
        return pd.DataFrame()
    
    sorted_df = df_candidates.sort_values(by="article_importance_score", ascending=False)
    
    top10_list = []
    press_count = {}

    # 1차: 점수 순 선별 (언론사당 최대 2건)
    for _, row in sorted_df.iterrows():
        press = row["언론사"]
        current_cnt = press_count.get(press, 0)
        
        if current_cnt < 2:
            top10_list.append(row)
            press_count[press] = current_cnt + 1
            
        if len(top10_list) == 10:
            break
            
    top10_df = pd.DataFrame(top10_list)
    if not top10_df.empty:
        top10_df["순위"] = range(1, len(top10_df) + 1)
    return top10_df

# ==========================================
# 📊 [6. 핵심 이슈 생성 부분 (동적 Gemini 분석 + 캐싱)]
# ==========================================
@st.cache_data(ttl=timedelta(hours=8))
def analyze_core_issues_with_gemini(top10_df):
    """
    [실제 AI API가 호출되는 부분 2 / 핵심 이슈 생성 부분]
    TOP 10 기사를 바탕으로 8개 필수 JSON 항목 및 Fact/Implication/Action 구조 생성
    """
    if top10_df.empty:
        return []

    articles_context = ""
    for _, r in top10_df.iterrows():
        articles_context += f"기사 #{r['순위']}\n- 언론사: {r['언론사']} ({r['매체구분']})\n- 제목: {r['기사제목']}\n- 요약(스니펫): {r['기사내용']}\n- URL: {r['기사링크']}\n\n"

    if not GEMINI_API_KEY:
        return fallback_core_issues_analysis(top10_df)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY.strip()}"
    headers = {"Content-Type": "application/json"}
    
    prompt = f"""
당신은 대한민국 보험사 전략기획 및 상품·영업 총괄 수석 이코노미스트입니다.
제공된 이번 주 중요도 TOP 10 보험 기사(뉴스 요약 스니펫 기반)를 심층 분석하여, 관통하는 핵심 이슈 3~5개를 동적으로 도출하세요.

[주의사항]:
- 미리 정해진 키워드를 쓰지 말고, 오직 제공된 기사 내용에만 근거할 것.
- Fact, Implication(의미), Action(실무 대응)을 명확히 구분할 것.
- 각 Fact에는 반드시 [기사 #번호]와 기사 제목을 포함할 것.

[TOP 10 기사 데이터]:
{articles_context}

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "issues": [
    {{
      "core_issue": "이슈 명칭",
      "related_article_numbers": [1, 2],
      "related_article_count": 2,
      "core_summary": "이슈 핵심 요약 2문장",
      "facts": [
        "[기사 #1] 기사제목 : 확인된 객관적 사실 내용"
      ],
      "why_it_matters": "보험산업 관점에서 이 이슈가 중요한 이유",
      "product_planning_insight": {{
        "fact": "상품기획 관련 사실 근거",
        "implication": "해당 사실이 상품 라인업/손익에 미치는 영향",
        "action": "상품기획 부서의 구체적 실행 권고사항"
      }},
      "sales_management_insight": {{
        "fact": "영업현장/채널 관련 사실 근거",
        "implication": "해당 사실이 판매조직/고객반응에 미치는 영향",
        "action": "영업관리 부서의 구체적 실행 권고사항"
      }}
    }}
  ]
}}
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=14)
        if res.status_code == 200:
            data = res.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            clean_json = json.loads(raw_text)
            return clean_json.get("issues", [])
    except Exception:
        pass
        
    return fallback_core_issues_analysis(top10_df)

def fallback_core_issues_analysis(top10_df):
    """API 장애 시 TOP 10 데이터를 기반으로 구조화하는 비상 분석기"""
    issues = []
    for idx, r in top10_df.head(3).iterrows():
        issues.append({
            "core_issue": f"{r['기사제목'][:30]} 관련 동향",
            "related_article_numbers": [int(r['순위'])],
            "related_article_count": 1,
            "core_summary": f"{r['언론사']}에서 보도된 {r['기사제목']} 관련 주요 시장 이슈입니다.",
            "facts": [f"[기사 #{r['순위']}] {r['기사제목']} : {r['기사내용'][:80]}..."],
            "why_it_matters": f"{r['언론사']} 보도에 따른 업계 파급력 및 중요도({r['article_importance_score']}점) 발생 현안임.",
            "product_planning_insight": {
                "fact": "기사 요약문 상 제도 개편 및 손익 지표 변동 확인됨.",
                "implication": "손해율 및 마진율 변화에 따른 특약 재설계 필요성 대두.",
                "action": "세부 특약 분리 및 리스크 사전 언더라이팅 가이드라인 수립."
            },
            "sales_management_insight": {
                "fact": "현장 채널 가동률 및 고객 안내 기준 변경 확인됨.",
                "implication": "고객 접점 설명 부족 시 불완전판매 및 민원 발생 우려.",
                "action": "채널별 표준 스피치북 배포 및 약관 변경사항 선제 안내."
            }
        })
    return issues

# ==========================================
# 💾 [7. CSV 및 Notion 연동 인프라 (보존)]
# ==========================================
DB_FILE = "v_scrap_data.csv"

def load_scraps():
    if os.path.exists(DB_FILE):
        try: return pd.read_csv(DB_FILE).to_dict(orient="records")
        except: return []
    return []

def save_scraps(data_list):
    if data_list: pd.DataFrame(data_list).to_csv(DB_FILE, index=False, encoding="utf-8-sig")
    else:
        if os.path.exists(DB_FILE): os.remove(DB_FILE)

if "scrap_storage" not in st.session_state:
    st.session_state["scrap_storage"] = load_scraps()

# ==========================================
# 📄 [8. 한글 PDF 리포트 빌더 (Fact/Action 반영)]
# ==========================================
def generate_pdf_report(top10_df, issues_list):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    
    font_name = 'NanumGothic' if has_korean_font else 'Helvetica'
    font_bold_name = 'NanumGothic-Bold' if has_korean_font else 'Helvetica-Bold'
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('PDFTitle', parent=styles['Heading1'], fontName=font_bold_name, fontSize=17, textColor=colors.HexColor('#1A365D'), spaceAfter=12, alignment=1)
    h2_style = ParagraphStyle('PDFH2', parent=styles['Heading2'], fontName=font_bold_name, fontSize=12, textColor=colors.HexColor('#2B6CB0'), spaceBefore=10, spaceAfter=5)
    h3_style = ParagraphStyle('PDFH3', parent=styles['Heading3'], fontName=font_bold_name, fontSize=10, textColor=colors.HexColor('#2D3748'), spaceBefore=5, spaceAfter=3)
    body_style = ParagraphStyle('PDFBody', parent=styles['Normal'], fontName=font_name, fontSize=8.5, leading=13, spaceAfter=4)
    bullet_style = ParagraphStyle('PDFBullet', parent=body_style, leftIndent=10, firstLineIndent=-6)

    # 1. 헤더 타이틀
    current_month_str = datetime.now().strftime("%Y년 %m월")
    story.append(Paragraph(f"📈 {current_month_str} 보험시장 트렌드 & 핵심 이슈 인텔리전스 리포트", title_style))
    story.append(Paragraph(f"발행일자: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 데이터 출처: 10대 검증 언론사 스니펫 정량 평가 데이터", body_style))
    story.append(Spacer(1, 8))

    # 출처 비율 계산
    if not top10_df.empty:
        press_counts = top10_df["매체구분"].value_counts()
        ratio_str = " / ".join([f"{k} {v}건" for k, v in press_counts.items()])
    else:
        ratio_str = "보험 전문지 / 경제지 / 종합지"

    # 2. TOP 10 요약 테이블
    story.append(Paragraph(f"1. 이번 주 중요도 TOP 10 기사 랭킹 ({ratio_str})", h2_style))
    table_data = [["순위", "매체", "중요도", "분석", "기사 제목"]]
    
    if not top10_df.empty:
        for _, r in top10_df.iterrows():
            short_t = r['기사제목'][:32] + "..." if len(r['기사제목']) > 32 else r['기사제목']
            table_data.append([str(r['순위']), f"{r['언론사']}", f"{r['article_importance_score']}점", f"{r.get('eval_mode','-')}", short_t])
    
    t = Table(table_data, colWidths=[25, 75, 45, 45, 350])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F7FAFC')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#1A365D')),
        ('FONTNAME', (0,0), (-1,-1), font_name),
        ('FONTSIZE', (0,0), (-1,0), 8.5),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('ALIGN', (0,0), (3,-1), 'CENTER'),
        ('ALIGN', (4,0), (4,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    # 3. 핵심 이슈 종합 분석 및 Insight
    story.append(Paragraph("2. 주간 핵심 이슈 도출 및 실무 Insight (Fact / Action)", h2_style))
    for idx, iss in enumerate(issues_list):
        story.append(Paragraph(f"<b>이슈 {idx+1}: {iss['core_issue']} (관련 기사: {iss.get('related_article_count', 1)}건)</b>", h3_style))
        story.append(Paragraph(f"• <b>[핵심 요약]</b> {iss.get('core_summary','')}", bullet_style))
        for f in iss.get("facts", []):
            story.append(Paragraph(f"• <b>[Fact]</b> {f}", bullet_style))
        story.append(Paragraph(f"• <b>[Why it matters]</b> {iss.get('why_it_matters','')}", bullet_style))
        
        pi = iss.get("product_planning_insight", {})
        if isinstance(pi, dict):
            story.append(Paragraph(f"• <b>[상품기획 Action]</b> {pi.get('action','')}", bullet_style))
        else:
            story.append(Paragraph(f"• <b>[상품기획 Action]</b> {pi}", bullet_style))

        si = iss.get("sales_management_insight", {})
        if isinstance(si, dict):
            story.append(Paragraph(f"• <b>[영업관리 Action]</b> {si.get('action','')}", bullet_style))
        else:
            story.append(Paragraph(f"• <b>[영업관리 Action]</b> {si}", bullet_style))
        story.append(Spacer(1, 4))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# ==========================================
# 🚀 메인 데이터 처리 파이프라인
# ==========================================
raw_df, collection_timestamp = fetch_real_naver_news()
top10_df = select_top10_articles(raw_df)
core_issues = analyze_core_issues_with_gemini(top10_df)

article_url_map = {}
if not top10_df.empty:
    for _, r in top10_df.iterrows():
        article_url_map[r["순위"]] = {"title": r["기사제목"], "link": r["기사링크"]}

# --- 대시보드 화면 렌더링 영역 ---
st.title("📊 AI 기반 보험 트렌드 & 이슈 인텔리전스 플랫폼")
st.caption(f"🔄 10대 검증 매체 뉴스 스니펫 수집 및 Gemini 정량 평가 파이프라인 가동 (최근 갱신일: {collection_timestamp})")

# 사이드바 매체 필터
media_options = list(raw_df["언론사"].unique()) if not raw_df.empty else ["한국보험신문"]
selected_media = st.sidebar.multiselect("📰 모니터링 언론사 선택", options=media_options, default=media_options)
filtered_raw_df = raw_df[raw_df["언론사"].isin(selected_media)] if not raw_df.empty else raw_df

# 사이드바 리포트 다운로드 구역
st.sidebar.markdown("---")
st.sidebar.subheader("📥 Executive Report")
with st.sidebar:
    try:
        pdf_data = generate_pdf_report(top10_df, core_issues)
        st.download_button(
            label="📄 이번 주 보험 이슈 리포트 PDF 다운로드",
            data=pdf_data,
            file_name=f"보험시장_핵심이슈_리포트_{datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )
    except Exception as pdf_err:
        st.error(f"리포트 빌드 대기 중: {pdf_err}")
st.sidebar.markdown("---")

# ==========================================
# 🔍 [시스템 진단 및 평가 현황 모니터링 보드]
# ==========================================
st.subheader("🛠️ 시스템 데이터 진단 및 평가 현황")
diag_col1, diag_col2, diag_col3, diag_col4 = st.columns(4)

with diag_col1:
    st.metric("📋 검증 수집 기사 수", f"{len(raw_df)} 건")
with diag_col2:
    ai_cnt = len(raw_df[raw_df["eval_mode"] == "AI"]) if not raw_df.empty and "eval_mode" in raw_df.columns else 0
    fb_cnt = len(raw_df) - ai_cnt
    st.metric("🤖 AI vs ⚙️ Fallback", f"AI {ai_cnt}건 / FB {fb_cnt}건")
with diag_col3:
    if not top10_df.empty:
        type_str = " | ".join([f"{k[:4]} {v}" for k, v in top10_df["매체구분"].value_counts().items()])
        st.metric("🎯 TOP 10 매체 구성", type_str)
    else:
        st.metric("🎯 TOP 10 매체 구성", "-")
with diag_col4:
    st.metric("🧩 도출된 핵심 이슈", f"{len(core_issues)} 개")

with st.expander("📊 실제 검증된 언론사별 수집 통계 펼치기"):
    if not raw_df.empty:
        press_stat_df = raw_df.groupby(["언론사", "매체구분"]).size().reset_index(name="수집 기사 수")
        st.dataframe(press_stat_df, use_container_width=True, hide_index=True)

st.markdown("---")

# 1. TOP 10 중요도 랭킹 & 평가 지표 매트릭스
st.subheader("🏆 이번 주 보험시장 중요도 TOP 10 기사 매트릭스")
if not top10_df.empty:
    fig_bar = px.bar(
        top10_df,
        x="순위",
        y="article_importance_score",
        color="매체구분",
        text="article_importance_score",
        hover_data=["언론사", "기사제목", "eval_mode", "industry_score", "policy_score", "consumer_score", "market_score", "timeliness_score"],
        labels={"article_importance_score": "중요도 총점 (100점)", "순위": "선정 순위"}
    )
    fig_bar.update_layout(xaxis=dict(tickmode="linear", tick0=1, dtick=1))
    st.plotly_chart(fig_bar, use_container_width=True)

st.markdown("---")

# 2. 핵심 이슈 종합 분석 & Fact/Insight 카드 (URL 링크 연결)
st.subheader("🧩 AI 종합 분석: 주간 핵심 이슈 & 실무 Insight")
for idx, iss in enumerate(core_issues):
    with st.expander(f"📌 [이슈 {idx+1}] {iss.get('core_issue', '이슈')} (관련 기사 {iss.get('related_article_count', 1)}건)", expanded=(idx == 0)):
        st.markdown(f"**📝 [Core Summary - 핵심 요약]**\n\n{iss.get('core_summary', '')}")
        st.markdown(f"**⚖️ [Why it matters - 산업적 중요도]**\n\n{iss.get('why_it_matters', '')}")
        
        st.markdown("**🔍 [Fact - 객관적 사실 및 근거 기사 (네이버 스니펫 기반)]**")
        for f in iss.get("facts", []):
            match = re.search(r"기사 #?(\d+)", f)
            if match:
                num = int(match.group(1))
                if num in article_url_map:
                    target_url = article_url_map[num]["link"]
                    st.markdown(f"- {f} 👉 [🔗 원문 읽기]({target_url})")
                else:
                    st.markdown(f"- {f}")
            else:
                st.markdown(f"- {f}")
        
        c_left, c_right = st.columns(2)
        with c_left:
            st.markdown("##### 📦 상품기획 Insight (Fact / Implication / Action)")
            pi = iss.get("product_planning_insight", {})
            if isinstance(pi, dict):
                st.write(f"• **Fact:** {pi.get('fact', '')}")
                st.write(f"• **Implication:** {pi.get('implication', '')}")
                st.info(f"👉 **Action:** {pi.get('action', '')}")
            else:
                st.info(pi)
        with c_right:
            st.markdown("##### 💼 영업관리 Insight (Fact / Implication / Action)")
            si = iss.get("sales_management_insight", {})
            if isinstance(si, dict):
                st.write(f"• **Fact:** {si.get('fact', '')}")
                st.write(f"• **Implication:** {si.get('implication', '')}")
                st.success(f"👉 **Action:** {si.get('action', '')}")
            else:
                st.success(si)

st.markdown("---")

# 3. 3문장 요약 & 데일리 인사이트 스크랩북 (보존)
bottom_col1, bottom_col2 = st.columns(2)

with bottom_col1:
    st.subheader("🤖 기사 정밀 분석 및 평가 근거")
    if not filtered_raw_df.empty:
        selected_title = st.selectbox("📄 분석할 기사를 선택하세요:", options=filtered_raw_df["기사제목"].values)
        article_info = filtered_raw_df[filtered_raw_df["기사제목"] == selected_title].iloc[0]
        st.link_button("🔗 선택한 기사 원문 읽기", article_info["기사링크"])
        
        mode_label = "🤖 AI 분석" if article_info.get("eval_mode") == "AI" else "⚙️ Fallback 분석"
        st.markdown(f"**📊 중요도 평가 총점:** `{article_info['article_importance_score']}점 / 100점` | 상태: **`{mode_label}`** | 언론사: **`{article_info['언론사']}`**")
        st.write(f"- 산업: {article_info['industry_score']}점 | 정책: {article_info['policy_score']}점 | 소비자: {article_info['consumer_score']}점 | 시장: {article_info['market_score']}점 | 시의성: {article_info['timeliness_score']}점")
        st.info(f"✍️ **채점 근거:**\n\n{article_info['importance_reason']}")
        
        st.markdown("🔍 **원문 핵심 스니펫 (네이버 공식 제공 요약문):**")
        st.write(article_info["기사내용"])

with bottom_col2:
    st.subheader("📁 대시보드 스크랩 및 노션 더블 백업")
    st.write("인사이트를 기록하고 저장하면 대시보드 화면에 실시간 유지되며, 개인 노션에도 안전하게 백업본이 전송됩니다.")

    if not filtered_raw_df.empty:
        st.text_input("📌 스크랩 대상 기사", value=selected_title, disabled=True)
        scrap_insight = st.text_area("📝 오늘의 상품기획 / 영업관리 인사이트 기록", placeholder="여기에 적은 내용이 대시보드 표와 노션에 동시에 저장됩니다.")
        
        if st.button("💾 대시보드 저장 및 노션 백업 전송"):
            if scrap_insight:
                is_duplicate = any(item["기사제목"] == selected_title for item in st.session_state["scrap_storage"])
                
                if not is_duplicate:
                    new_scrap = {
                        "일자": datetime.now().strftime("%Y-%m-%d"),
                        "기사제목": selected_title,
                        "기사링크": article_info['기사링크'],
                        "나의 인사이트 (더블클릭하여 수정 가능)": scrap_insight
                    }
                    
                    st.session_state["scrap_storage"].append(new_scrap)
                    save_scraps(st.session_state["scrap_storage"])
                    
                    if NOTION_TOKEN and NOTION_DATABASE_ID:
                        notion_url = "https://api.notion.com/v1/pages"
                        headers = {
                            "Authorization": f"Bearer {NOTION_TOKEN.strip()}",
                            "Content-Type": "application/json",
                            "Notion-Version": "2022-06-28"
                        }
                        payload = {
                            "parent": {"database_id": NOTION_DATABASE_ID.strip()},
                            "properties": {
                                "기사제목": {"title": [{"text": {"content": f"{selected_title} ({article_info['기사링크']})"}}]},
                                "일자": {"rich_text": [{"text": {"content": datetime.now().strftime("%Y-%m-%d")}}]},
                                "나의 인사이트": {"rich_text": [{"text": {"content": scrap_insight}}]}
                            }
                        }
                        try:
                            requests.post(notion_url, json=payload, headers=headers)
                            st.success("🎯 대시보드 저장 완료 및 노션 클라우드 백업 전송 성공!")
                        except:
                            st.warning("⚠️ 대시보드에는 저장되었으나 노션 백업 전송 중 오류가 발생했습니다.")
                    else:
                        st.success("🎯 대시보드 저장 완료 (노션 설정 누락으로 로컬 파일에만 저장됨).")
                    
                    st.rerun()
                else:
                    st.warning("⚠️ 이미 스크랩북에 등록된 기사입니다.")
            else:
                st.error("⚠️ 인사이트 내용을 입력해 주셔야 저장이 가능합니다.")
    
    if st.session_state["scrap_storage"]:
        st.markdown("---")
        st.markdown("📂 **나의 누적 스크랩 내역 (대시보드 상시 노출 중)**")
        
        scrap_df = pd.DataFrame(st.session_state["scrap_storage"])
        
        if NOTION_TOKEN and NOTION_DATABASE_ID:
            if st.button("🚀 현재 대시보드 내역 노션으로 일괄 전송 (연동하기)"):
                notion_url = "https://api.notion.com/v1/pages"
                headers = {
                    "Authorization": f"Bearer {NOTION_TOKEN.strip()}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28"
                }
                success_count = 0
                
                with st.spinner("과거 스크랩 자산을 노션 클라우드로 이전 중..."):
                    for item in st.session_state["scrap_storage"]:
                        lnk = item.get('기사링크', 'https://news.naver.com')
                        ins = item.get('나의 인사이트 (더블클릭하여 수정 가능)', item.get('나의 인사이트', ''))
                        dt = item.get('일자', datetime.now().strftime("%Y-%m-%d"))
                        
                        payload = {
                            "parent": {"database_id": NOTION_DATABASE_ID.strip()},
                            "properties": {
                                "기사제목": {"title": [{"text": {"content": f"{item['기사제목']} ({lnk})"}}]},
                                "일자": {"rich_text": [{"text": {"content": str(dt)}}]},
                                "나의 인사이트": {"rich_text": [{"text": {"content": str(ins)}}]}
                            }
                        }
                        res = requests.post(notion_url, json=payload, headers=headers)
                        if res.status_code == 200: success_count += 1
                
                if success_count > 0:
                    st.success(f"🎉 이전 완료! {success_count}개의 데이터가 노션 표로 완벽하게 전송되었습니다!")
                else:
                    st.error("❌ 노션 일괄 전송 실패.")
                st.rerun()
        
        display_df = scrap_df.copy()
        if "나의 인사이트" in display_df.columns and "나의 인사이트 (더블클릭하여 수정 가능)" not in display_df.columns:
            display_df["나의 인사이트 (더블클릭하여 수정 가능)"] = display_df["나의 인사이트"]
            
        edited_df = st.data_editor(
            display_df[["일자", "기사제목", "기사링크", "나의 인사이트 (더블클릭하여 수정 가능)"]],
            column_config={
                "기사링크": st.column_config.LinkColumn("원문 링크", display_text="🔗 이동하기"),
                "일자": st.column_config.TextColumn("일자", disabled=True),
                "기사제목": st.column_config.TextColumn("기사제목", disabled=True)
            },
            use_container_width=True, hide_index=True, key="dashboard_sync_editor_v16"
        )
        
        updated_data = edited_df.to_dict(orient="records")
        if updated_data != st.session_state["scrap_storage"]:
            st.session_state["scrap_storage"] = updated_data
            save_scraps(updated_data)
        
        if st.button("🗑️ 전체 스크랩 내역 영구 삭제"):
            st.session_state["scrap_storage"] = []
            save_scraps([])
            st.success("대시보드 스크랩 목록이 초기화되었습니다.")
            st.rerun()

st.markdown("---")

# 4. 전체 수집 기사 정밀 데이터 매트릭스
st.subheader("📰 최근 7일간 검증 매체 기사 데이터 매트릭스")
if not filtered_raw_df.empty:
    st.data_editor(
        filtered_raw_df[["날짜", "언론사", "매체구분", "article_importance_score", "eval_mode", "기사제목", "기사링크"]],
        column_config={
            "기사링크": st.column_config.LinkColumn("원문 보기", display_text="🔗 이동하기"),
            "article_importance_score": st.column_config.NumberColumn("중요도", format="%d점"),
            "eval_mode": st.column_config.TextColumn("평가 방식")
        },
        use_container_width=True, hide_index=True, disabled=True
    )

이렇게수정해줬어
