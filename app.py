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

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# =========================================================
# 🔐 SECRETS
# =========================================================

NAVER_CLIENT_ID = st.secrets.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = st.secrets.get("NAVER_CLIENT_SECRET", "")

NOTION_TOKEN = st.secrets.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = st.secrets.get("NOTION_DATABASE_ID", "")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# ⭐ 현재 사용 모델
GEMINI_MODEL = "gemini-3.6-flash"

# ⭐ API 기본 주소
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)


# =========================================================
# ⚙️ PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="AI 기반 보험 트렌드 & 이슈 인텔리전스 플랫폼",
    page_icon="📈",
    layout="wide"
)


# =========================================================
# 🇰🇷 한글 PDF 폰트
# =========================================================

@st.cache_resource
def init_korean_font():

    font_url = (
        "https://github.com/google/fonts/raw/main/ofl/nanumgothic/"
        "NanumGothic-Regular.ttf"
    )

    font_bold_url = (
        "https://github.com/google/fonts/raw/main/ofl/nanumgothic/"
        "NanumGothic-Bold.ttf"
    )

    try:

        r = requests.get(font_url, timeout=10)

        if r.status_code == 200:
            pdfmetrics.registerFont(
                TTFont("NanumGothic", io.BytesIO(r.content))
            )

        rb = requests.get(font_bold_url, timeout=10)

        if rb.status_code == 200:
            pdfmetrics.registerFont(
                TTFont("NanumGothic-Bold", io.BytesIO(rb.content))
            )

        return True

    except Exception as e:

        st.sidebar.warning(
            f"⚠️ 한글 폰트 로드 실패: {e}"
        )

        return False


has_korean_font = init_korean_font()


# =========================================================
# 📰 검증 언론사
# =========================================================

TARGET_PRESS_CONFIG = {

    "한국보험신문": {
        "type": "보험 전문지",
        "domains": ["insweek.co.kr"],
        "query": '"한국보험신문"'
    },

    "보험매일": {
        "type": "보험 전문지",
        "domains": ["fins.co.kr"],
        "query": '"보험매일"'
    },

    "보험신문": {
        "type": "보험 전문지",
        "domains": ["bohumnews.com"],
        "query": '"보험신문"'
    },

    "대한금융신문": {
        "type": "금융 전문지",
        "domains": ["kbanker.co.kr"],
        "query": '"대한금융신문" 보험'
    },

    "CEO스코어데일리": {
        "type": "기업·경영 전문지",
        "domains": ["ceoscoredaily.com"],
        "query": '"CEO스코어데일리" 보험'
    },

    "매일경제": {
        "type": "경제지",
        "domains": ["mk.co.kr"],
        "query": '"매일경제" 보험'
    },

    "한국경제": {
        "type": "경제지",
        "domains": ["hankyung.com"],
        "query": '"한국경제" 보험'
    },

    "머니투데이": {
        "type": "경제지",
        "domains": ["mt.co.kr"],
        "query": '"머니투데이" 보험'
    },

    "서울경제": {
        "type": "경제지",
        "domains": ["sedaily.com"],
        "query": '"서울경제" 보험'
    },

    "연합뉴스": {
        "type": "종합지",
        "domains": ["yna.co.kr", "yonhapnewstv.co.kr"],
        "query": '"연합뉴스" 보험'
    }
}


# =========================================================
# 🔍 중복 제거
# =========================================================

def normalize_title(title):

    t = re.sub(
        r"\[.*?\]|\(.*?\)",
        "",
        title
    )

    t = re.sub(
        r"[^\w\s]",
        "",
        t
    )

    return set(
        t.strip().split()
    )


def is_duplicate_article(
    title_tokens,
    existing_tokens_list
):

    if not title_tokens:
        return False

    for existing in existing_tokens_list:

        intersection = title_tokens.intersection(existing)
        union = title_tokens.union(existing)

        if union:

            jaccard = (
                len(intersection) /
                len(union)
            )

            if jaccard >= 0.55:
                return True

    return False


# =========================================================
# 🤖 Gemini API 호출 공통 함수
# =========================================================

def call_gemini(prompt, timeout=60):

    if not GEMINI_API_KEY:

        return {
            "success": False,
            "error": "GEMINI_API_KEY가 Streamlit Secrets에 없습니다.",
            "data": None
        }

    headers = {
        "Content-Type": "application/json"
    }

    payload = {

        "contents": [

            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }

        ],

        "generationConfig": {

            "responseMimeType": "application/json",

            "temperature": 0.2

        }

    }

    try:

        response = requests.post(
            GEMINI_URL,
            headers=headers,
            params={
                "key": GEMINI_API_KEY.strip()
            },
            json=payload,
            timeout=timeout
        )

        if response.status_code != 200:

            try:
                error_json = response.json()

                error_message = (
                    error_json
                    .get("error", {})
                    .get("message", response.text)
                )

            except Exception:

                error_message = response.text

            return {
                "success": False,
                "error": (
                    f"HTTP {response.status_code}: "
                    f"{error_message}"
                ),
                "data": None
            }

        data = response.json()

        try:

            raw_text = (
                data["candidates"][0]
                ["content"]["parts"][0]["text"]
            )

        except Exception:

            return {
                "success": False,
                "error": f"Gemini 응답 구조를 읽을 수 없습니다: {data}",
                "data": None
            }

        # 혹시 ```json ```으로 감싸져 오는 경우 제거
        raw_text = raw_text.strip()

        raw_text = re.sub(
            r"^```json\s*",
            "",
            raw_text,
            flags=re.IGNORECASE
        )

        raw_text = re.sub(
            r"\s*```$",
            "",
            raw_text
        )

        try:

            parsed = json.loads(raw_text)

        except Exception as e:

            return {
                "success": False,
                "error": (
                    "Gemini가 JSON 형식으로 응답하지 않았습니다. "
                    f"원문: {raw_text[:1000]}"
                ),
                "data": None
            }

        return {
            "success": True,
            "error": None,
            "data": parsed
        }

    except requests.exceptions.Timeout:

        return {
            "success": False,
            "error": (
                f"Gemini API 요청 시간이 {timeout}초를 초과했습니다."
            ),
            "data": None
        }

    except requests.exceptions.RequestException as e:

        return {
            "success": False,
            "error": f"네트워크 오류: {e}",
            "data": None
        }

    except Exception as e:

        return {
            "success": False,
            "error": f"예상하지 못한 오류: {e}",
            "data": None
        }


# =========================================================
# 🧠 Fallback 평가
# =========================================================

def evaluate_article_fallback(
    title,
    desc,
    pub_dt
):

    text = (
        title + " " + desc
    ).lower()

    if any(
        k in text
        for k in [
            "ifrs17",
            "csm",
            "k-ics",
            "계리",
            "자본확충",
            "지급여력"
        ]
    ):

        ind = 23
        ind_r = (
            "IFRS17/CSM 등 산업 전반 "
            "구조적 지표 연관"
        )

    elif any(
        k in text
        for k in [
            "손해율",
            "언더라이팅",
            "uwd",
            "실적개선",
            "수익성"
        ]
    ):

        ind = 18
        ind_r = (
            "다수 보험사 손익 및 "
            "심사 기준 영향"
        )

    else:

        ind = 10
        ind_r = (
            "개별사 또는 제한적 산업 영향"
        )


    if any(
        k in text
        for k in [
            "금융위",
            "금감원",
            "금융감독원",
            "시행령",
            "감독규정",
            "가이드라인"
        ]
    ):

        pol = 18
        pol_r = (
            "금융당국의 직접적인 "
            "규제/정책 변화"
        )

    elif any(
        k in text
        for k in [
            "제도개편",
            "개선안",
            "tf",
            "공청회",
            "논의"
        ]
    ):

        pol = 13
        pol_r = (
            "제도 개편 및 "
            "당국 논의 단계"
        )

    else:

        pol = 5
        pol_r = "정책 관련성 낮음"


    if any(
        k in text
        for k in [
            "실손",
            "비급여",
            "보험료 인상",
            "보험료 인하",
            "약관",
            "지급기준"
        ]
    ):

        con = 18
        con_r = (
            "대다수 가입자 보험료 및 "
            "보장 직접 영향"
        )

    elif any(
        k in text
        for k in [
            "청구간소화",
            "펫보험",
            "유병자",
            "고령화",
            "치매"
        ]
    ):

        con = 13
        con_r = (
            "특정 타깃 가입자층 영향"
        )

    else:

        con = 5
        con_r = "소비자 영향 제한적"


    if any(
        k in text
        for k in [
            "제3보험",
            "m/s",
            "점유율",
            "가격경쟁",
            "출혈경쟁",
            "ga"
        ]
    ):

        mkt = 17
        mkt_r = (
            "시장 경쟁구도 및 "
            "채널 판도 영향"
        )

    elif any(
        k in text
        for k in [
            "신상품",
            "특약",
            "배타적사용권",
            "담보"
        ]
    ):

        mkt = 12
        mkt_r = (
            "특정 상품군 라인업 변화"
        )

    else:

        mkt = 6
        mkt_r = "시장 영향도 제한적"


    try:

        days_diff = (
            datetime.now() - pub_dt
        ).days

    except Exception:

        days_diff = 7


    if days_diff <= 1:
        tim = 14

    elif days_diff <= 3:
        tim = 11

    elif days_diff <= 5:
        tim = 8

    else:
        tim = 4


    total = (
        ind +
        pol +
        con +
        mkt +
        tim
    )

    reason = (
        f"[{ind_r}] 및 "
        f"[{pol_r}] 기반 중요도 산정 "
        "(Fallback 평가)"
    )

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


# =========================================================
# 🤖 Gemini 기사 중요도 평가
# =========================================================

def evaluate_articles_batch_with_gemini(
    articles_list
):

    if not articles_list:

        return []


    # API 키 없으면 Fallback
    if not GEMINI_API_KEY:

        return [
            evaluate_article_fallback(
                a["기사제목"],
                a["기사내용"],
                a["pub_datetime"]
            )
            for a in articles_list
        ]


    # ⭐ 최대 15개까지만 Gemini에 전달
    # 기사 수가 너무 많으면 timeout 가능성이 커짐
    articles_for_ai = articles_list[:15]


    prompt_items = []

    for idx, a in enumerate(
        articles_for_ai,
        1
    ):

        prompt_items.append(
            f"""
기사 #{idx}
제목: {a['기사제목']}
요약: {a['기사내용']}
언론사: {a['언론사']}
"""
        )


    context_str = "\n".join(
        prompt_items
    )


    prompt = f"""
당신은 대한민국 보험산업 전략기획 담당 수석 이코노미스트입니다.

아래 보험 기사들을 분석하여 각 기사의 중요도를
100점 만점으로 평가하세요.

[기사 목록]

{context_str}

[평가 기준]

1. 산업 영향도 25점
- 보험산업 구조
- IFRS17
- CSM
- K-ICS
- 보험사 수익성
- 상품/채널 변화

2. 정책/제도 20점
- 금융위원회
- 금융감독원
- 법령
- 감독규정
- 가이드라인
- 제도개편

3. 소비자 영향 20점
- 보험료
- 보장
- 약관
- 지급기준
- 실손
- 소비자 권익

4. 시장 영향 20점
- 경쟁구도
- 시장규모
- 수익성
- 상품경쟁
- GA
- 판매채널

5. 시의성 15점
- 현재 진행 중인 이슈인지
- 최근 발생한 이슈인지

반드시 제공된 기사 내용만 근거로 평가하세요.

반드시 아래 JSON 형식으로만 답하세요.

{{
    "evaluations": [
        {{
            "index": 1,
            "industry_score": 20,
            "policy_score": 15,
            "consumer_score": 10,
            "market_score": 15,
            "timeliness_score": 12,
            "importance_reason": "점수 산정 근거"
        }}
    ]
}}
"""


    result = call_gemini(
        prompt,
        timeout=60
    )


    if not result["success"]:

        # ⭐ Streamlit에 실제 오류 표시
        st.warning(
            "⚠️ Gemini 기사 평가 API 오류\n\n"
            + result["error"]
        )

        return [
            evaluate_article_fallback(
                a["기사제목"],
                a["기사내용"],
                a["pub_datetime"]
            )
            for a in articles_list
        ]


    evaluations = (
        result["data"]
        .get("evaluations", [])
    )


    results = []


    for idx, a in enumerate(
        articles_list,
        1
    ):

        # 15개까지만 AI 평가
        if idx <= len(articles_for_ai):

            matching = next(
                (
                    e for e in evaluations
                    if int(e.get("index", 0)) == idx
                ),
                None
            )

            if matching:

                try:

                    ind = max(
                        0,
                        min(
                            25,
                            int(
                                matching.get(
                                    "industry_score",
                                    10
                                )
                            )
                        )
                    )

                    pol = max(
                        0,
                        min(
                            20,
                            int(
                                matching.get(
                                    "policy_score",
                                    10
                                )
                            )
                        )
                    )

                    con = max(
                        0,
                        min(
                            20,
                            int(
                                matching.get(
                                    "consumer_score",
                                    10
                                )
                            )
                        )
                    )

                    mkt = max(
                        0,
                        min(
                            20,
                            int(
                                matching.get(
                                    "market_score",
                                    10
                                )
                            )
                        )
                    )

                    tim = max(
                        0,
                        min(
                            15,
                            int(
                                matching.get(
                                    "timeliness_score",
                                    10
                                )
                            )
                        )
                    )

                    total = (
                        ind +
                        pol +
                        con +
                        mkt +
                        tim
                    )

                    results.append({

                        "article_importance_score": total,

                        "industry_score": ind,

                        "policy_score": pol,

                        "consumer_score": con,

                        "market_score": mkt,

                        "timeliness_score": tim,

                        "importance_reason": str(
                            matching.get(
                                "importance_reason",
                                "Gemini AI 분석 완료"
                            )
                        ),

                        "eval_mode": "AI"

                    })

                    continue

                except Exception:
                    pass


        # AI 결과가 없으면 Fallback
        results.append(
            evaluate_article_fallback(
                a["기사제목"],
                a["기사내용"],
                a["pub_datetime"]
            )
        )


    return results


# =========================================================
# 📰 네이버 뉴스 수집
# =========================================================

@st.cache_data(
    ttl=timedelta(hours=8)
)
def fetch_real_naver_news():

    collected_at = (
        datetime.now()
        .strftime("%Y-%m-%d %H:%M:%S")
    )


    if not NAVER_CLIENT_ID:

        return (
            load_demo_data(),
            collected_at
        )


    headers = {

        "X-Naver-Client-Id":
            NAVER_CLIENT_ID.strip(),

        "X-Naver-Client-Secret":
            NAVER_CLIENT_SECRET.strip()

    }


    seven_days_ago = (
        datetime.now() -
        timedelta(days=7)
    )


    promo_blacklist = [

        "이벤트",
        "출시기념",
        "선착순",
        "증정이벤트",
        "고객감사",
        "공식 sns",
        "기프티콘",
        "사은품",
        "팝업스토어",
        "업무협약",
        "mou",
        "캠페인",
        "후원금",
        "보도자료",
        "공모전",
        "개최"

    ]


    seen_title_tokens = []

    candidate_articles = []


    for press_name, config in TARGET_PRESS_CONFIG.items():

        encoded_query = urllib.parse.quote(
            config["query"]
        )


        url = (
            "https://openapi.naver.com/v1/search/"
            "news.json?"
            f"query={encoded_query}"
            "&display=40"
            "&sort=sim"
        )


        try:

            res = requests.get(
                url,
                headers=headers,
                timeout=8
            )


            if res.status_code != 200:
                continue


            items = (
                res.json()
                .get("items", [])
            )


            for item in items:

                pub_date_str = (
                    item.get(
                        "pubDate",
                        ""
                    )
                )


                try:

                    pub_dt = datetime.strptime(
                        pub_date_str,
                        "%a, %d %b %Y %H:%M:%S +0900"
                    )

                except Exception:

                    pub_dt = datetime.now()


                if pub_dt < seven_days_ago:
                    continue


                orig_link = (
                    item.get(
                        "originallink",
                        ""
                    )
                    .strip()
                )


                naver_link = (
                    item.get(
                        "link",
                        ""
                    )
                    .strip()
                )


                final_link = (
                    orig_link
                    if orig_link
                    else naver_link
                )


                parsed_host = (
                    urlparse(orig_link)
                    .netloc
                    .lower()
                )


                is_verified_press = False


                for domain in config["domains"]:

                    if domain in parsed_host:

                        is_verified_press = True
                        break


                if not is_verified_press:
                    continue


                clean_title = (
                    item.get(
                        "title",
                        ""
                    )
                    .replace("<b>", "")
                    .replace("</b>", "")
                    .replace("&quot;", '"')
                    .replace("&amp;", "&")
                )


                clean_desc = (
                    item.get(
                        "description",
                        ""
                    )
                    .replace("<b>", "")
                    .replace("</b>", "")
                    .replace("&quot;", '"')
                    .replace("&amp;", "&")
                )


                if any(
                    bw in clean_title.lower()
                    for bw in promo_blacklist
                ):
                    continue


                tokens = normalize_title(
                    clean_title
                )


                if is_duplicate_article(
                    tokens,
                    seen_title_tokens
                ):
                    continue


                candidate_articles.append({

                    "날짜":
                        pub_dt.strftime(
                            "%Y-%m-%d"
                        ),

                    "언론사":
                        press_name,

                    "매체구분":
                        config["type"],

                    "기사제목":
                        clean_title,

                    "기사내용":
                        clean_desc,

                    "기사링크":
                        final_link,

                    "pub_datetime":
                        pub_dt

                })


                seen_title_tokens.append(
                    tokens
                )


        except Exception:
            continue


    if not candidate_articles:

        return (
            load_demo_data(),
            collected_at
        )


    # ⭐ 중요도 평가
    eval_results = (
        evaluate_articles_batch_with_gemini(
            candidate_articles
        )
    )


    all_evaluated_news = []


    for art, ev in zip(
        candidate_articles,
        eval_results
    ):

        all_evaluated_news.append({

            **art,
            **ev

        })


    final_df = pd.DataFrame(
        all_evaluated_news
    )


    return (
        final_df,
        collected_at
    )


# =========================================================
# 🧪 Demo 데이터
# =========================================================

def load_demo_data():

    now_str = (
        datetime.now()
        .strftime("%Y-%m-%d")
    )


    return pd.DataFrame([

        {

            "날짜": now_str,

            "언론사": "한국보험신문",

            "매체구분": "보험 전문지",

            "기사제목":
                "IFRS17 2년차 진입 속 제3보험 신계약 CSM 확보 총력전",

            "기사내용":
                "주요 생손보사들이 장기 수익성 강화를 위해 GA 채널에 대한 수수료 개편과 건강보험 신상품 라인업을 집중 배치하고 있다.",

            "기사링크":
                "https://www.insweek.co.kr/",

            "pub_datetime":
                datetime.now(),

            "article_importance_score": 93,

            "industry_score": 24,

            "policy_score": 19,

            "consumer_score": 18,

            "market_score": 18,

            "timeliness_score": 14,

            "importance_reason":
                "IFRS17/CSM 수익성 확보 전략 및 당국 가이드라인 대응 이슈로 산업 전반에 미치는 파급력이 매우 큼.",

            "eval_mode": "AI"

        },

        {

            "날짜": now_str,

            "언론사": "매일경제",

            "매체구분": "경제지",

            "기사제목":
                "실손보험 비급여 과잉 도수치료 손해율 급등에 당국 정밀 심사 착수",

            "기사내용":
                "금융당국과 손해보험업계가 비급여 누수로 인한 손해율 악화를 방어하기 위해 인수심사 가이드라인과 비급여 지급 기준 개편에 나섰다.",

            "기사링크":
                "https://www.mk.co.kr/",

            "pub_datetime":
                datetime.now(),

            "article_importance_score": 89,

            "industry_score": 18,

            "policy_score": 19,

            "consumer_score": 19,

            "market_score": 18,

            "timeliness_score": 15,

            "importance_reason":
                "전체 국민 실손보험료 조정 및 비급여 심사 강화와 직결되어 소비자 및 제도적 영향도가 높음.",

            "eval_mode": "AI"

        }

    ])


# =========================================================
# 🏆 TOP 10
# =========================================================

def select_top10_articles(df_candidates):

    if df_candidates.empty:
        return pd.DataFrame()


    sorted_df = (
        df_candidates
        .sort_values(
            by="article_importance_score",
            ascending=False
        )
    )


    top10_list = []

    press_count = {}


    for _, row in sorted_df.iterrows():

        press = row["언론사"]

        current_cnt = (
            press_count
            .get(press, 0)
        )


        if current_cnt < 2:

            top10_list.append(row)

            press_count[press] = (
                current_cnt + 1
            )


        if len(top10_list) == 10:
            break


    top10_df = pd.DataFrame(
        top10_list
    )


    if not top10_df.empty:

        top10_df["순위"] = range(
            1,
            len(top10_df) + 1
        )


    return top10_df


# =========================================================
# 🧩 Gemini 핵심 이슈 분석
# =========================================================

def analyze_core_issues_with_gemini(
    top10_df
):

    if top10_df.empty:
        return []


    articles_context = ""


    for _, r in top10_df.iterrows():

        articles_context += f"""

기사 #{r['순위']}
언론사: {r['언론사']}
매체구분: {r['매체구분']}
제목: {r['기사제목']}
요약: {r['기사내용']}
URL: {r['기사링크']}

"""


    if not GEMINI_API_KEY:

        return fallback_core_issues_analysis(
            top10_df
        )


    prompt = f"""
당신은 대한민국 보험사 전략기획 및 상품·영업 총괄 수석 이코노미스트입니다.

아래 이번 주 보험시장 중요도 TOP 10 기사를 분석하여
서로 연결되는 핵심 이슈 3~5개를 도출하세요.

반드시 제공된 기사 내용에 근거하세요.

각 이슈는 다음 구조로 작성합니다.

1. Core Issue
2. Core Summary
3. Fact
4. Why it matters
5. 상품기획 Insight
6. 영업관리 Insight

특히 Fact는 반드시 기사 번호와 제목을 포함하세요.

[TOP 10 기사]

{articles_context}


반드시 아래 JSON 형식으로만 답하세요.

{{
    "issues": [
        {{
            "core_issue": "핵심 이슈 명칭",

            "related_article_numbers": [1,2],

            "related_article_count": 2,

            "core_summary":
                "핵심 요약",

            "facts": [
                "[기사 #1] 기사제목 : 객관적 사실"
            ],

            "why_it_matters":
                "보험산업 관점에서 중요한 이유",

            "product_planning_insight": {{
                "fact":
                    "상품기획 관련 사실",

                "implication":
                    "상품 및 손익에 미치는 영향",

                "action":
                    "상품기획 부서의 실행 방안"
            }},

            "sales_management_insight": {{
                "fact":
                    "영업현장 관련 사실",

                "implication":
                    "판매조직 및 고객반응 영향",

                "action":
                    "영업관리 부서의 실행 방안"
            }}
        }}
    ]
}}
"""


    result = call_gemini(
        prompt,
        timeout=60
    )


    if not result["success"]:

        st.warning(
            "⚠️ Gemini 핵심 이슈 분석 오류\n\n"
            + result["error"]
        )

        return fallback_core_issues_analysis(
            top10_df
        )


    issues = (
        result["data"]
        .get("issues", [])
    )


    return issues


# =========================================================
# 🧩 Fallback 핵심 이슈
# =========================================================

def fallback_core_issues_analysis(
    top10_df
):

    issues = []


    for _, r in top10_df.head(3).iterrows():

        issues.append({

            "core_issue":
                f"{r['기사제목'][:30]} 관련 동향",

            "related_article_numbers":
                [int(r["순위"])],

            "related_article_count":
                1,

            "core_summary":
                f"{r['언론사']}에서 보도된 "
                f"{r['기사제목']} 관련 주요 시장 이슈입니다.",

            "facts":
                [
                    f"[기사 #{r['순위']}] "
                    f"{r['기사제목']} : "
                    f"{r['기사내용'][:100]}"
                ],

            "why_it_matters":
                f"중요도 {r['article_importance_score']}점으로 "
                "보험시장에 미치는 영향이 높은 현안입니다.",

            "product_planning_insight":
                {

                    "fact":
                        "기사 요약에서 보험상품 및 손익 관련 변화가 확인됩니다.",

                    "implication":
                        "상품 라인업과 손익구조에 영향을 줄 가능성이 있습니다.",

                    "action":
                        "관련 상품의 손해율과 수익성을 점검하고 "
                        "상품·특약 경쟁력을 검토합니다."

                },

            "sales_management_insight":
                {

                    "fact":
                        "보험 판매채널 및 고객 안내와 관련된 변화가 확인됩니다.",

                    "implication":
                        "영업현장의 설명 방식과 고객 문의가 변화할 수 있습니다.",

                    "action":
                        "채널별 교육자료와 고객 설명 기준을 선제적으로 정비합니다."

                }

        })


    return issues


# =========================================================
# 💾 스크랩
# =========================================================

DB_FILE = "v_scrap_data.csv"


def load_scraps():

    if os.path.exists(DB_FILE):

        try:

            return pd.read_csv(
                DB_FILE
            ).to_dict(
                orient="records"
            )

        except Exception:

            return []

    return []


def save_scraps(data_list):

    if data_list:

        pd.DataFrame(
            data_list
        ).to_csv(
            DB_FILE,
            index=False,
            encoding="utf-8-sig"
        )

    else:

        if os.path.exists(DB_FILE):

            os.remove(DB_FILE)


if "scrap_storage" not in st.session_state:

    st.session_state[
        "scrap_storage"
    ] = load_scraps()


# =========================================================
# 📄 PDF
# =========================================================

def generate_pdf_report(
    top10_df,
    issues_list
):

    buffer = io.BytesIO()


    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )


    story = []


    font_name = (
        "NanumGothic"
        if has_korean_font
        else "Helvetica"
    )


    font_bold_name = (
        "NanumGothic-Bold"
        if has_korean_font
        else "Helvetica-Bold"
    )


    styles = getSampleStyleSheet()


    title_style = ParagraphStyle(
        "PDFTitle",
        parent=styles["Heading1"],
        fontName=font_bold_name,
        fontSize=17,
        textColor=colors.HexColor("#1A365D"),
        spaceAfter=12,
        alignment=1
    )


    h2_style = ParagraphStyle(
        "PDFH2",
        parent=styles["Heading2"],
        fontName=font_bold_name,
        fontSize=12,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=10,
        spaceAfter=5
    )


    h3_style = ParagraphStyle(
        "PDFH3",
        parent=styles["Heading3"],
        fontName=font_bold_name,
        fontSize=10,
        textColor=colors.HexColor("#2D3748"),
        spaceBefore=5,
        spaceAfter=3
    )


    body_style = ParagraphStyle(
        "PDFBody",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=8.5,
        leading=13,
        spaceAfter=4
    )


    bullet_style = ParagraphStyle(
        "PDFBullet",
        parent=body_style,
        leftIndent=10,
        firstLineIndent=-6
    )


    current_month_str = (
        datetime.now()
        .strftime("%Y년 %m월")
    )


    story.append(
        Paragraph(
            f"📈 {current_month_str} 보험시장 트렌드 & 핵심 이슈 인텔리전스 리포트",
            title_style
        )
    )


    story.append(
        Paragraph(
            f"발행일자: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')} "
            f"| 데이터 출처: 10대 검증 언론사",
            body_style
        )
    )


    story.append(
        Spacer(1, 8)
    )


    press_counts = (
        top10_df["매체구분"]
        .value_counts()
        if not top10_df.empty
        else {}
    )


    ratio_str = (
        " / ".join(
            [
                f"{k} {v}건"
                for k, v
                in press_counts.items()
            ]
        )
        if len(press_counts)
        else "보험 전문지 / 경제지 / 종합지"
    )


    story.append(
        Paragraph(
            f"1. 이번 주 중요도 TOP 10 기사 랭킹 ({ratio_str})",
            h2_style
        )
    )


    table_data = [
        [
            "순위",
            "매체",
            "중요도",
            "분석",
            "기사 제목"
        ]
    ]


    if not top10_df.empty:

        for _, r in top10_df.iterrows():

            short_t = (
                r["기사제목"][:32] + "..."
                if len(r["기사제목"]) > 32
                else r["기사제목"]
            )

            table_data.append(
                [
                    str(r["순위"]),
                    str(r["언론사"]),
                    f"{r['article_importance_score']}점",
                    r.get(
                        "eval_mode",
                        "-"
                    ),
                    short_t
                ]
            )


    t = Table(
        table_data,
        colWidths=[
            25,
            75,
            45,
            45,
            350
        ]
    )


    t.setStyle(
        TableStyle(
            [

                (
                    "BACKGROUND",
                    (0,0),
                    (-1,0),
                    colors.HexColor("#F7FAFC")
                ),

                (
                    "TEXTCOLOR",
                    (0,0),
                    (-1,0),
                    colors.HexColor("#1A365D")
                ),

                (
                    "FONTNAME",
                    (0,0),
                    (-1,-1),
                    font_name
                ),

                (
                    "FONTSIZE",
                    (0,0),
                    (-1,0),
                    8.5
                ),

                (
                    "FONTSIZE",
                    (0,1),
                    (-1,-1),
                    8
                ),

                (
                    "ALIGN",
                    (0,0),
                    (3,-1),
                    "CENTER"
                ),

                (
                    "ALIGN",
                    (4,0),
                    (4,-1),
                    "LEFT"
                ),

                (
                    "GRID",
                    (0,0),
                    (-1,-1),
                    0.5,
                    colors.HexColor("#CBD5E0")
                ),

                (
                    "VALIGN",
                    (0,0),
                    (-1,-1),
                    "MIDDLE"
                )

            ]
        )
    )


    story.append(t)


    story.append(
        Spacer(1, 8)
    )


    story.append(
        Paragraph(
            "2. 주간 핵심 이슈 및 실무 Insight",
            h2_style
        )
    )


    for idx, iss in enumerate(
        issues_list
    ):

        story.append(
            Paragraph(
                f"<b>이슈 {idx+1}: "
                f"{iss.get('core_issue', '이슈')}</b>",
                h3_style
            )
        )


        story.append(
            Paragraph(
                f"• <b>[핵심 요약]</b> "
                f"{iss.get('core_summary','')}",
                bullet_style
            )
        )


        for f in iss.get(
            "facts",
            []
        ):

            story.append(
                Paragraph(
                    f"• <b>[Fact]</b> {f}",
                    bullet_style
                )
            )


        story.append(
            Paragraph(
                f"• <b>[Why it matters]</b> "
                f"{iss.get('why_it_matters','')}",
                bullet_style
            )
        )


        pi = iss.get(
            "product_planning_insight",
            {}
        )


        if isinstance(pi, dict):

            story.append(
                Paragraph(
                    f"• <b>[상품기획 Action]</b> "
                    f"{pi.get('action','')}",
                    bullet_style
                )
            )


        si = iss.get(
            "sales_management_insight",
            {}
        )


        if isinstance(si, dict):

            story.append(
                Paragraph(
                    f"• <b>[영업관리 Action]</b> "
                    f"{si.get('action','')}",
                    bullet_style
                )
            )


    doc.build(story)


    buffer.seek(0)


    return buffer.getvalue()


# =========================================================
# 🚀 MAIN
# =========================================================

raw_df, collection_timestamp = (
    fetch_real_naver_news()
)


top10_df = select_top10_articles(
    raw_df
)


core_issues = (
    analyze_core_issues_with_gemini(
        top10_df
    )
)


article_url_map = {}


if not top10_df.empty:

    for _, r in top10_df.iterrows():

        article_url_map[
            r["순위"]
        ] = {

            "title":
                r["기사제목"],

            "link":
                r["기사링크"]

        }


# =========================================================
# 🖥️ DASHBOARD
# =========================================================

st.title(
    "📊 AI 기반 보험 트렌드 & 이슈 인텔리전스 플랫폼"
)


st.caption(
    f"🔄 10대 검증 매체 뉴스 수집 + "
    f"Gemini 정량 평가 | "
    f"최근 갱신: {collection_timestamp}"
)


# =========================================================
# SIDEBAR
# =========================================================

media_options = (
    list(
        raw_df["언론사"].unique()
    )
    if not raw_df.empty
    else ["한국보험신문"]
)


selected_media = st.sidebar.multiselect(
    "📰 모니터링 언론사 선택",
    options=media_options,
    default=media_options
)


filtered_raw_df = (
    raw_df[
        raw_df["언론사"].isin(
            selected_media
        )
    ]
    if not raw_df.empty
    else raw_df
)


st.sidebar.markdown("---")


# =========================================================
# 🤖 GEMINI STATUS
# =========================================================

st.sidebar.subheader(
    "🤖 Gemini API 상태"
)


if GEMINI_API_KEY:

    st.sidebar.success(
        "Gemini 연결 설정 완료"
    )

    st.sidebar.caption(
        f"모델: {GEMINI_MODEL}"
    )

else:

    st.sidebar.error(
        "Gemini API Key 미설정"
    )


# =========================================================
# 📥 PDF
# =========================================================

st.sidebar.markdown("---")

st.sidebar.subheader(
    "📥 Executive Report"
)


with st.sidebar:

    try:

        pdf_data = generate_pdf_report(
            top10_df,
            core_issues
        )


        st.download_button(
            label="📄 이번 주 보험 이슈 리포트 PDF 다운로드",
            data=pdf_data,
            file_name=(
                f"보험시장_핵심이슈_리포트_"
                f"{datetime.now().strftime('%Y%m%d')}.pdf"
            ),
            mime="application/pdf",
            use_container_width=True
        )


    except Exception as pdf_err:

        st.error(
            f"리포트 생성 오류: {pdf_err}"
        )


# =========================================================
# SYSTEM DIAGNOSTIC
# =========================================================

st.markdown("---")


st.subheader(
    "🛠️ 시스템 데이터 진단 및 평가 현황"
)


diag_col1, diag_col2, diag_col3, diag_col4 = (
    st.columns(4)
)


with diag_col1:

    st.metric(
        "📋 검증 수집 기사 수",
        f"{len(raw_df)}건"
    )


with diag_col2:

    ai_cnt = (
        len(
            raw_df[
                raw_df["eval_mode"] == "AI"
            ]
        )
        if (
            not raw_df.empty
            and "eval_mode" in raw_df.columns
        )
        else 0
    )


    fb_cnt = (
        len(raw_df) - ai_cnt
    )


    st.metric(
        "🤖 AI vs ⚙️ Fallback",
        f"AI {ai_cnt}건 / FB {fb_cnt}건"
    )


with diag_col3:

    if not top10_df.empty:

        type_str = " | ".join(
            [
                f"{k[:4]} {v}"
                for k, v
                in top10_df[
                    "매체구분"
                ]
                .value_counts()
                .items()
            ]
        )

        st.metric(
            "🎯 TOP 10 매체 구성",
            type_str
        )

    else:

        st.metric(
            "🎯 TOP 10 매체 구성",
            "-"
        )


with diag_col4:

    st.metric(
        "🧩 도출된 핵심 이슈",
        f"{len(core_issues)}개"
    )


# =========================================================
# PRESS STATS
# =========================================================

with st.expander(
    "📊 실제 검증된 언론사별 수집 통계"
):

    if not raw_df.empty:

        press_stat_df = (
            raw_df
            .groupby(
                [
                    "언론사",
                    "매체구분"
                ]
            )
            .size()
            .reset_index(
                name="수집 기사 수"
            )
        )


        st.dataframe(
            press_stat_df,
            use_container_width=True,
            hide_index=True
        )


# =========================================================
# TOP 10
# =========================================================

st.markdown("---")


st.subheader(
    "🏆 이번 주 보험시장 중요도 TOP 10 기사 매트릭스"
)


if not top10_df.empty:

    fig_bar = px.bar(

        top10_df,

        x="순위",

        y="article_importance_score",

        color="매체구분",

        text="article_importance_score",

        hover_data=[
            "언론사",
            "기사제목",
            "eval_mode",
            "industry_score",
            "policy_score",
            "consumer_score",
            "market_score",
            "timeliness_score"
        ],

        labels={
            "article_importance_score":
                "중요도 총점 (100점)",

            "순위":
                "선정 순위"
        }

    )


    fig_bar.update_layout(
        xaxis=dict(
            tickmode="linear",
            tick0=1,
            dtick=1
        )
    )


    st.plotly_chart(
        fig_bar,
        use_container_width=True
    )


# =========================================================
# CORE ISSUES
# =========================================================

st.markdown("---")


st.subheader(
    "🧩 AI 종합 분석: 주간 핵심 이슈 & 실무 Insight"
)


for idx, iss in enumerate(
    core_issues
):

    with st.expander(
        f"📌 [이슈 {idx+1}] "
        f"{iss.get('core_issue','이슈')} "
        f"(관련 기사 "
        f"{iss.get('related_article_count',1)}건)",
        expanded=(idx == 0)
    ):

        st.markdown(
            f"**📝 핵심 요약**\n\n"
            f"{iss.get('core_summary','')}"
        )


        st.markdown(
            f"**⚖️ 산업적 중요도**\n\n"
            f"{iss.get('why_it_matters','')}"
        )


        st.markdown(
            "**🔍 Fact - 객관적 사실 및 근거 기사**"
        )


        for f in iss.get(
            "facts",
            []
        ):

            match = re.search(
                r"기사 #?(\d+)",
                f
            )


            if match:

                num = int(
                    match.group(1)
                )


                if num in article_url_map:

                    target_url = (
                        article_url_map[num]
                        ["link"]
                    )


                    st.markdown(
                        f"- {f} "
                        f"👉 [🔗 원문 읽기]"
                        f"({target_url})"
                    )

                else:

                    st.markdown(
                        f"- {f}"
                    )

            else:

                st.markdown(
                    f"- {f}"
                )


        c_left, c_right = st.columns(2)


        with c_left:

            st.markdown(
                "##### 📦 상품기획 Insight"
            )


            pi = iss.get(
                "product_planning_insight",
                {}
            )


            if isinstance(pi, dict):

                st.write(
                    f"• **Fact:** "
                    f"{pi.get('fact','')}"
                )


                st.write(
                    f"• **Implication:** "
                    f"{pi.get('implication','')}"
                )


                st.info(
                    f"👉 **Action:** "
                    f"{pi.get('action','')}"
                )


        with c_right:

            st.markdown(
                "##### 💼 영업관리 Insight"
            )


            si = iss.get(
                "sales_management_insight",
                {}
            )


            if isinstance(si, dict):

                st.write(
                    f"• **Fact:** "
                    f"{si.get('fact','')}"
                )


                st.write(
                    f"• **Implication:** "
                    f"{si.get('implication','')}"
                )


                st.success(
                    f"👉 **Action:** "
                    f"{si.get('action','')}"
                )


# =========================================================
# SCRAPBOOK
# =========================================================

st.markdown("---")


bottom_col1, bottom_col2 = (
    st.columns(2)
)


with bottom_col1:

    st.subheader(
        "🤖 기사 정밀 분석 및 평가 근거"
    )


    if not filtered_raw_df.empty:

        selected_title = st.selectbox(
            "📄 분석할 기사를 선택하세요:",
            options=filtered_raw_df[
                "기사제목"
            ].values
        )


        article_info = (
            filtered_raw_df[
                filtered_raw_df[
                    "기사제목"
                ] == selected_title
            ]
            .iloc[0]
        )


        st.link_button(
            "🔗 선택한 기사 원문 읽기",
            article_info["기사링크"]
        )


        mode_label = (
            "🤖 AI 분석"
            if article_info.get(
                "eval_mode"
            ) == "AI"
            else
            "⚙️ Fallback 분석"
        )


        st.markdown(
            f"**📊 중요도 평가 총점:** "
            f"`{article_info['article_importance_score']}점 / 100점` "
            f"| 상태: **{mode_label}** "
            f"| 언론사: **{article_info['언론사']}**"
        )


        st.write(
            f"- 산업: {article_info['industry_score']}점 "
            f"| 정책: {article_info['policy_score']}점 "
            f"| 소비자: {article_info['consumer_score']}점 "
            f"| 시장: {article_info['market_score']}점 "
            f"| 시의성: {article_info['timeliness_score']}점"
        )


        st.info(
            f"✍️ **채점 근거:**\n\n"
            f"{article_info['importance_reason']}"
        )


        st.markdown(
            "🔍 **원문 핵심 스니펫:**"
        )


        st.write(
            article_info["기사내용"]
        )


with bottom_col2:

    st.subheader(
        "📁 대시보드 스크랩 및 노션 백업"
    )


    st.write(
        "인사이트를 기록하고 저장하면 "
        "대시보드에 유지되며 "
        "Notion에도 백업됩니다."
    )


    if not filtered_raw_df.empty:

        st.text_input(
            "📌 스크랩 대상 기사",
            value=selected_title,
            disabled=True
        )


        scrap_insight = st.text_area(
            "📝 오늘의 상품기획 / 영업관리 인사이트",
            placeholder=(
                "여기에 인사이트를 입력하세요."
            )
        )


        if st.button(
            "💾 대시보드 저장 및 노션 백업"
        ):

            if scrap_insight:

                is_duplicate = any(
                    item["기사제목"]
                    == selected_title
                    for item
                    in st.session_state[
                        "scrap_storage"
                    ]
                )


                if not is_duplicate:

                    new_scrap = {

                        "일자":
                            datetime.now()
                            .strftime(
                                "%Y-%m-%d"
                            ),

                        "기사제목":
                            selected_title,

                        "기사링크":
                            article_info[
                                "기사링크"
                            ],

                        "나의 인사이트":
                            scrap_insight

                    }


                    st.session_state[
                        "scrap_storage"
                    ].append(
                        new_scrap
                    )


                    save_scraps(
                        st.session_state[
                            "scrap_storage"
                        ]
                    )


                    # -------------------------
                    # Notion
                    # -------------------------

                    if (
                        NOTION_TOKEN
                        and
                        NOTION_DATABASE_ID
                    ):

                        notion_url = (
                            "https://api.notion.com/v1/pages"
                        )


                        headers = {

                            "Authorization":
                                f"Bearer "
                                f"{NOTION_TOKEN.strip()}",

                            "Content-Type":
                                "application/json",

                            "Notion-Version":
                                "2022-06-28"

                        }


                        payload = {

                            "parent": {
                                "database_id":
                                    NOTION_DATABASE_ID.strip()
                            },

                            "properties": {

                                "기사제목": {

                                    "title": [

                                        {
                                            "text": {
                                                "content":
                                                    selected_title
                                            }
                                        }

                                    ]

                                },

                                "일자": {

                                    "rich_text": [

                                        {
                                            "text": {
                                                "content":
                                                    datetime.now()
                                                    .strftime(
                                                        "%Y-%m-%d"
                                                    )
                                            }
                                        }

                                    ]

                                },

                                "나의 인사이트": {

                                    "rich_text": [

                                        {
                                            "text": {
                                                "content":
                                                    scrap_insight
                                            }
                                        }

                                    ]

                                }

                            }

                        }


                        try:

                            notion_res = requests.post(
                                notion_url,
                                json=payload,
                                headers=headers,
                                timeout=15
                            )


                            if notion_res.status_code in [
                                200,
                                201
                            ]:

                                st.success(
                                    "🎯 대시보드 저장 + "
                                    "Notion 백업 완료!"
                                )

                            else:

                                st.warning(
                                    "⚠️ 대시보드 저장 완료. "
                                    f"Notion 오류 "
                                    f"{notion_res.status_code}"
                                )

                        except Exception as e:

                            st.warning(
                                f"⚠️ Notion 전송 오류: {e}"
                            )

                    else:

                        st.success(
                            "🎯 대시보드 저장 완료"
                        )


                    st.rerun()


                else:

                    st.warning(
                        "⚠️ 이미 스크랩한 기사입니다."
                    )


            else:

                st.error(
                    "⚠️ 인사이트를 입력해주세요."
                )


    # 누적 스크랩

    if st.session_state[
        "scrap_storage"
    ]:

        st.markdown("---")


        st.markdown(
            "📂 **나의 누적 스크랩 내역**"
        )


        scrap_df = pd.DataFrame(
            st.session_state[
                "scrap_storage"
            ]
        )


        edited_df = st.data_editor(

            scrap_df[
                [
                    "일자",
                    "기사제목",
                    "기사링크",
                    "나의 인사이트"
                ]
            ],

            column_config={

                "기사링크":
                    st.column_config.LinkColumn(
                        "원문 링크",
                        display_text="🔗 이동하기"
                    ),

                "일자":
                    st.column_config.TextColumn(
                        "일자",
                        disabled=True
                    ),

                "기사제목":
                    st.column_config.TextColumn(
                        "기사제목",
                        disabled=True
                    )

            },

            use_container_width=True,

            hide_index=True,

            key="dashboard_sync_editor_v20"

        )


        updated_data = (
            edited_df
            .to_dict(
                orient="records"
            )
        )


        if updated_data != (
            st.session_state[
                "scrap_storage"
            ]
        ):

            st.session_state[
                "scrap_storage"
            ] = updated_data


            save_scraps(
                updated_data
            )


        if st.button(
            "🗑️ 전체 스크랩 내역 영구 삭제"
        ):

            st.session_state[
                "scrap_storage"
            ] = []


            save_scraps([])


            st.success(
                "스크랩 목록이 초기화되었습니다."
            )


            st.rerun()


# =========================================================
# 📰 전체 기사
# =========================================================

st.markdown("---")


st.subheader(
    "📰 최근 7일간 검증 매체 기사 데이터 매트릭스"
)


if not filtered_raw_df.empty:

    st.data_editor(

        filtered_raw_df[
            [
                "날짜",
                "언론사",
                "매체구분",
                "article_importance_score",
                "eval_mode",
                "기사제목",
                "기사링크"
            ]
        ],

        column_config={

            "기사링크":
                st.column_config.LinkColumn(
                    "원문 보기",
                    display_text="🔗 이동하기"
                ),

            "article_importance_score":
                st.column_config.NumberColumn(
                    "중요도",
                    format="%d점"
                ),

            "eval_mode":
                st.column_config.TextColumn(
                    "평가 방식"
                )

        },

        use_container_width=True,

        hide_index=True,

        disabled=True

    )
