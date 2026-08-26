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
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)
from reportlab.lib.styles import (
    getSampleStyleSheet,
    ParagraphStyle
)
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# =========================================================
# 🔐 1. SECRETS
# =========================================================

NAVER_CLIENT_ID = st.secrets.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = st.secrets.get("NAVER_CLIENT_SECRET", "")

NOTION_TOKEN = st.secrets.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = st.secrets.get("NOTION_DATABASE_ID", "")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "").strip()

# 현재 사용할 Gemini 모델
GEMINI_MODEL = "gemini-2.5-flash"


# =========================================================
# ⚙️ 2. PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="AI 기반 보험 트렌드 & 이슈 인텔리전스 플랫폼",
    page_icon="📈",
    layout="wide"
)


# =========================================================
# 🔤 3. 한글 PDF 폰트
# =========================================================

@st.cache_resource
def init_korean_font():

    font_url = (
        "https://github.com/google/fonts/raw/main/"
        "ofl/nanumgothic/NanumGothic-Regular.ttf"
    )

    font_bold_url = (
        "https://github.com/google/fonts/raw/main/"
        "ofl/nanumgothic/NanumGothic-Bold.ttf"
    )

    try:

        r = requests.get(font_url, timeout=10)

        pdfmetrics.registerFont(
            TTFont(
                "NanumGothic",
                io.BytesIO(r.content)
            )
        )

        rb = requests.get(font_bold_url, timeout=10)

        pdfmetrics.registerFont(
            TTFont(
                "NanumGothic-Bold",
                io.BytesIO(rb.content)
            )
        )

        return True

    except Exception as e:

        st.sidebar.warning(
            f"⚠️ 한글 폰트 로드 실패: {e}"
        )

        return False


has_korean_font = init_korean_font()


# =========================================================
# 📰 4. 검증 언론사
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
        "domains": [
            "yna.co.kr",
            "yonhapnewstv.co.kr"
        ],
        "query": '"연합뉴스" 보험'
    }
}


# =========================================================
# 🔍 5. 중복 제거
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
# 🤖 6. Gemini API 공통 호출 함수
# =========================================================

def call_gemini(prompt, timeout=30):

    if not GEMINI_API_KEY:

        return None, "GEMINI_API_KEY가 없습니다."

    url = (
        f"https://generativelanguage.googleapis.com/"
        f"v1beta/models/{GEMINI_MODEL}:generateContent"
    )

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
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

            "temperature": 0.2,

            "responseMimeType":
                "application/json"
        }
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout
        )

        if response.status_code != 200:

            return (
                None,
                f"HTTP {response.status_code}: "
                f"{response.text[:1000]}"
            )

        data = response.json()

        candidates = data.get(
            "candidates",
            []
        )

        if not candidates:

            return (
                None,
                "Gemini 응답에 candidates가 없습니다."
            )

        parts = (
            candidates[0]
            .get("content", {})
            .get("parts", [])
        )

        if not parts:

            return (
                None,
                "Gemini 응답에 text가 없습니다."
            )

        text = parts[0].get(
            "text",
            ""
        )

        if not text:

            return (
                None,
                "Gemini가 빈 응답을 반환했습니다."
            )

        return text, None

    except Exception as e:

        return (
            None,
            f"{type(e).__name__}: {e}"
        )


# =========================================================
# 📊 7. Fallback 평가
# =========================================================

def evaluate_article_fallback(
    title,
    desc,
    pub_dt
):

    text = (
        title +
        " " +
        desc
    ).lower()


    # 산업 영향도
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

    else:

        ind = 10


    # 정책
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

    else:

        pol = 5


    # 소비자
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

    else:

        con = 5


    # 시장
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

    else:

        mkt = 6


    # 시의성
    try:

        days_diff = (
            datetime.now() -
            pub_dt
        ).days

    except:

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
        "API 연결이 되지 않아 규칙 기반 "
        "Fallback 평가를 적용했습니다."
    )


    return {

        "article_importance_score":
            total,

        "industry_score":
            ind,

        "policy_score":
            pol,

        "consumer_score":
            con,

        "market_score":
            mkt,

        "timeliness_score":
            tim,

        "importance_reason":
            reason,

        "eval_mode":
            "Fallback"
    }


# =========================================================
# 🤖 8. Gemini 기사 중요도 평가
# =========================================================

def evaluate_articles_batch_with_gemini(
    articles_list
):

    if not articles_list:

        return []


    if not GEMINI_API_KEY:

        st.warning(
            "⚠️ GEMINI_API_KEY가 없어 "
            "Fallback 평가를 사용합니다."
        )

        return [
            evaluate_article_fallback(
                a["기사제목"],
                a["기사내용"],
                a["pub_datetime"]
            )
            for a in articles_list
        ]


    prompt_items = []


    for idx, article in enumerate(
        articles_list,
        1
    ):

        prompt_items.append(

            f"""
기사 #{idx}

- 제목:
{article['기사제목']}

- 요약:
{article['기사내용']}

- 언론사:
{article['언론사']}
"""
        )


    context_str = "\n".join(
        prompt_items
    )


    prompt = f"""
당신은 대한민국 보험산업 수석 이코노미스트입니다.

아래 보험 기사 목록을 분석하여
각 기사의 중요도를 100점 만점으로 정량 평가하세요.

[기사 목록]

{context_str}


[채점 기준]

1. 산업 영향도 (25점)

21~25:
보험산업 구조 또는 IFRS17, CSM,
K-ICS, 지급여력 등에 구조적 변화

16~20:
다수 보험사 또는 보험산업 수익성에 영향

11~15:
특정 상품이나 채널에 영향

1~10:
산업 영향 제한적


2. 정책/제도 (20점)

16~20:
금융당국, 법령, 감독규정 등의 직접적인 변화

11~15:
제도 개편 논의

6~10:
간접적인 정책 영향

1~5:
정책 관련성 낮음


3. 소비자 영향 (20점)

16~20:
다수 보험가입자에게 직접 영향

11~15:
특정 소비자 집단에 영향

6~10:
간접적인 영향

1~5:
제한적 영향


4. 시장 영향 (20점)

16~20:
경쟁구도, 수익성, 시장규모에 큰 영향

11~15:
특정 시장에 영향

6~10:
제한적 영향

1~5:
낮은 영향


5. 시의성 (15점)

13~15:
현재 진행 중인 매우 중요한 현안

10~12:
최근 중요 이슈

6~9:
일반적인 최근 이슈

1~5:
시의성 낮음


반드시 아래 JSON 형식으로만 응답하세요.

{{
  "evaluations": [
    {{
      "index": 1,
      "industry_score": 0,
      "policy_score": 0,
      "consumer_score": 0,
      "market_score": 0,
      "timeliness_score": 0,
      "importance_reason":
        "점수 산정 근거 2문장 내외"
    }}
  ]
}}
"""


    raw_text, error = call_gemini(
        prompt,
        timeout=30
    )


    if error:

        st.error(
            "❌ Gemini 기사 평가 API 오류\n\n"
            + error
        )

        return [
            evaluate_article_fallback(
                a["기사제목"],
                a["기사내용"],
                a["pub_datetime"]
            )
            for a in articles_list
        ]


    try:

        result_json = json.loads(
            raw_text
        )

        evaluations = result_json.get(
            "evaluations",
            []
        )

    except Exception as e:

        st.error(
            "❌ Gemini JSON 파싱 오류\n\n"
            + str(e)
        )

        return [
            evaluate_article_fallback(
                a["기사제목"],
                a["기사내용"],
                a["pub_datetime"]
            )
            for a in articles_list
        ]


    results = []


    for idx, article in enumerate(
        articles_list,
        1
    ):

        matching = next(
            (
                e for e in evaluations
                if int(e.get("index", -1))
                == idx
            ),
            None
        )


        if not matching:

            results.append(
                evaluate_article_fallback(
                    article["기사제목"],
                    article["기사내용"],
                    article["pub_datetime"]
                )
            )

            continue


        try:

            ind = int(
                matching.get(
                    "industry_score",
                    10
                )
            )

            pol = int(
                matching.get(
                    "policy_score",
                    5
                )
            )

            con = int(
                matching.get(
                    "consumer_score",
                    5
                )
            )

            mkt = int(
                matching.get(
                    "market_score",
                    5
                )
            )

            tim = int(
                matching.get(
                    "timeliness_score",
                    5
                )
            )

        except:

            results.append(
                evaluate_article_fallback(
                    article["기사제목"],
                    article["기사내용"],
                    article["pub_datetime"]
                )
            )

            continue


        total = (
            ind +
            pol +
            con +
            mkt +
            tim
        )


        results.append({

            "article_importance_score":
                total,

            "industry_score":
                ind,

            "policy_score":
                pol,

            "consumer_score":
                con,

            "market_score":
                mkt,

            "timeliness_score":
                tim,

            "importance_reason":
                str(
                    matching.get(
                        "importance_reason",
                        "Gemini AI 분석 완료"
                    )
                ),

            "eval_mode":
                "AI"
        })


    return results


# =========================================================
# 📰 9. 네이버 뉴스 수집
# =========================================================

@st.cache_data(
    ttl=timedelta(hours=8)
)
def fetch_real_naver_news():

    collected_at = (
        datetime.now()
        .strftime(
            "%Y-%m-%d %H:%M:%S"
        )
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


    for press_name, config in (
        TARGET_PRESS_CONFIG.items()
    ):

        encoded_query = urllib.parse.quote(
            config["query"]
        )


        url = (
            "https://openapi.naver.com/"
            "v1/search/news.json"
            f"?query={encoded_query}"
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


            items = res.json().get(
                "items",
                []
            )


            for item in items:

                pub_date_str = item.get(
                    "pubDate",
                    ""
                )


                try:

                    pub_dt = datetime.strptime(
                        pub_date_str,
                        "%a, %d %b %Y %H:%M:%S +0900"
                    )

                except:

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
                    .replace(
                        "&quot;",
                        '"'
                    )
                    .replace(
                        "&amp;",
                        "&"
                    )
                )


                clean_desc = (
                    item.get(
                        "description",
                        ""
                    )
                    .replace("<b>", "")
                    .replace("</b>", "")
                    .replace(
                        "&quot;",
                        '"'
                    )
                    .replace(
                        "&amp;",
                        "&"
                    )
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


    # Gemini AI 평가
    eval_results = (
        evaluate_articles_batch_with_gemini(
            candidate_articles
        )
    )


    all_evaluated_news = []


    for article, evaluation in zip(
        candidate_articles,
        eval_results
    ):

        all_evaluated_news.append({

            **article,
            **evaluation

        })


    final_df = pd.DataFrame(
        all_evaluated_news
    )


    return (
        final_df,
        collected_at
    )


# =========================================================
# 🧪 10. Demo 데이터
# =========================================================

def load_demo_data():

    now = datetime.now()

    now_str = now.strftime(
        "%Y-%m-%d"
    )


    return pd.DataFrame([

        {

            "날짜":
                now_str,

            "언론사":
                "한국보험신문",

            "매체구분":
                "보험 전문지",

            "기사제목":
                "IFRS17 2년차 진입 속 제3보험 신계약 CSM 확보 총력전",

            "기사내용":
                "주요 생손보사들이 장기 수익성 강화를 위해 GA 채널에 대한 수수료 개편과 건강보험 신상품 라인업을 집중 배치하고 있다.",

            "기사링크":
                "https://www.insweek.co.kr/",

            "pub_datetime":
                now,

            "article_importance_score":
                93,

            "industry_score":
                24,

            "policy_score":
                19,

            "consumer_score":
                18,

            "market_score":
                18,

            "timeliness_score":
                14,

            "importance_reason":
                "IFRS17/CSM 수익성 확보 전략 및 당국 가이드라인 대응 이슈로 산업 전반에 미치는 파급력이 매우 큼.",

            "eval_mode":
                "Demo"

        },

        {

            "날짜":
                now_str,

            "언론사":
                "매일경제",

            "매체구분":
                "경제지",

            "기사제목":
                "실손보험 비급여 과잉 도수치료 손해율 급등에 당국 정밀 심사 착수",

            "기사내용":
                "금융당국과 손해보험업계가 비급여 누수로 인한 손해율 악화를 방어하기 위해 인수심사 가이드라인과 비급여 지급 기준 개편에 나섰다.",

            "기사링크":
                "https://www.mk.co.kr/",

            "pub_datetime":
                now,

            "article_importance_score":
                89,

            "industry_score":
                18,

            "policy_score":
                19,

            "consumer_score":
                19,

            "market_score":
                18,

            "timeliness_score":
                15,

            "importance_reason":
                "전체 국민 실손보험료 조정 및 비급여 심사 강화와 직결되어 소비자 및 제도적 영향도가 높음.",

            "eval_mode":
                "Demo"

        }

    ])


# =========================================================
# 🏆 11. TOP 10
# =========================================================

def select_top10_articles(
    df_candidates
):

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
            press_count.get(
                press,
                0
            )
        )


        if current_cnt < 2:

            top10_list.append(
                row
            )

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
# 🧩 12. Gemini 핵심 이슈 분석
# =========================================================

@st.cache_data(
    ttl=timedelta(hours=8)
)
def analyze_core_issues_with_gemini(
    top10_df
):

    if top10_df.empty:

        return []


    articles_context = ""


    for _, r in top10_df.iterrows():

        articles_context += f"""
기사 #{r['순위']}

- 언론사:
{r['언론사']}

- 제목:
{r['기사제목']}

- 요약:
{r['기사내용']}

- URL:
{r['기사링크']}

"""


    if not GEMINI_API_KEY:

        return fallback_core_issues_analysis(
            top10_df
        )


    prompt = f"""
당신은 대한민국 보험사 전략기획 및
상품·영업 총괄 수석 이코노미스트입니다.

제공된 이번 주 보험 중요도 TOP 10 기사를
분석하여 관통하는 핵심 이슈 3~5개를
동적으로 도출하세요.

반드시 제공된 기사 내용만 근거로 판단하세요.

각 이슈마다 다음을 작성하세요.

1. core_issue
2. related_article_numbers
3. related_article_count
4. core_summary
5. facts
6. why_it_matters
7. 상품기획 Fact / Implication / Action
8. 영업관리 Fact / Implication / Action


[TOP 10 기사]

{articles_context}


반드시 아래 JSON 형식으로만 응답하세요.

{{
  "issues": [
    {{
      "core_issue":
        "핵심 이슈 명칭",

      "related_article_numbers":
        [1, 2],

      "related_article_count":
        2,

      "core_summary":
        "핵심 요약 2문장",

      "facts": [
        "[기사 #1] 기사제목 : 확인된 객관적 사실"
      ],

      "why_it_matters":
        "보험산업 관점에서 중요한 이유",

      "product_planning_insight": {{
        "fact":
          "상품기획 관련 사실",

        "implication":
          "상품 및 손익 영향",

        "action":
          "상품기획 실행 권고"
      }},

      "sales_management_insight": {{
        "fact":
          "영업현장 관련 사실",

        "implication":
          "판매조직 및 고객 영향",

        "action":
          "영업관리 실행 권고"
      }}
    }}
  ]
}}
"""


    raw_text, error = call_gemini(
        prompt,
        timeout=30
    )


    if error:

        st.error(
            "❌ Gemini 핵심 이슈 분석 오류\n\n"
            + error
        )

        return fallback_core_issues_analysis(
            top10_df
        )


    try:

        result = json.loads(
            raw_text
        )

        return result.get(
            "issues",
            []
        )

    except Exception as e:

        st.error(
            "❌ 핵심 이슈 JSON 파싱 오류\n\n"
            + str(e)
        )

        return fallback_core_issues_analysis(
            top10_df
        )


# =========================================================
# 🛟 13. 핵심 이슈 Fallback
# =========================================================

def fallback_core_issues_analysis(
    top10_df
):

    issues = []


    for _, r in (
        top10_df.head(3).iterrows()
    ):

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
                    f"{r['기사내용'][:100]}..."
                ],

            "why_it_matters":
                "보험산업의 수익성, 상품 및 "
                "영업전략에 영향을 줄 가능성이 있는 이슈입니다.",

            "product_planning_insight":
                {
                    "fact":
                        "기사 요약문에서 "
                        "상품 및 손익 관련 변화가 확인됩니다.",

                    "implication":
                        "상품 라인업 및 "
                        "수익성 관리에 영향을 줄 수 있습니다.",

                    "action":
                        "관련 상품의 손해율과 "
                        "수익성을 점검하고 대응안을 마련합니다."
                },

            "sales_management_insight":
                {
                    "fact":
                        "보험 판매채널과 "
                        "고객 반응에 영향을 줄 수 있습니다.",

                    "implication":
                        "판매조직의 설명 및 "
                        "고객 대응 기준 변화가 필요할 수 있습니다.",

                    "action":
                        "채널별 교육자료와 "
                        "표준 안내문을 점검합니다."
                }

        })


    return issues


# =========================================================
# 💾 14. 스크랩 저장
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

        except:

            return []

    return []


def save_scraps(
    data_list
):

    if data_list:

        pd.DataFrame(
            data_list
        ).to_csv(
            DB_FILE,
            index=False,
            encoding="utf-8-sig"
        )

    else:

        if os.path.exists(
            DB_FILE
        ):

            os.remove(
                DB_FILE
            )


if "scrap_storage" not in st.session_state:

    st.session_state[
        "scrap_storage"
    ] = load_scraps()


# =========================================================
# 📄 15. PDF
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

        textColor=colors.HexColor(
            "#1A365D"
        ),

        spaceAfter=12,

        alignment=1
    )


    h2_style = ParagraphStyle(

        "PDFH2",

        parent=styles["Heading2"],

        fontName=font_bold_name,

        fontSize=12,

        textColor=colors.HexColor(
            "#2B6CB0"
        ),

        spaceBefore=10,

        spaceAfter=5
    )


    body_style = ParagraphStyle(

        "PDFBody",

        parent=styles["Normal"],

        fontName=font_name,

        fontSize=8.5,

        leading=13,

        spaceAfter=4
    )


    current_month_str = (
        datetime.now()
        .strftime("%Y년 %m월")
    )


    story.append(

        Paragraph(

            f"📈 {current_month_str} "
            f"보험시장 트렌드 & "
            f"핵심 이슈 인텔리전스 리포트",

            title_style
        )
    )


    story.append(

        Paragraph(

            "발행일자: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}",

            body_style
        )
    )


    story.append(
        Spacer(1, 8)
    )


    story.append(

        Paragraph(
            "1. 보험시장 중요도 TOP 10",
            h2_style
        )
    )


    table_data = [
        [
            "순위",
            "매체",
            "중요도",
            "평가",
            "기사 제목"
        ]
    ]


    if not top10_df.empty:

        for _, r in top10_df.iterrows():

            title = r["기사제목"]

            if len(title) > 32:

                title = title[:32] + "..."


            table_data.append([

                str(r["순위"]),

                str(r["언론사"]),

                f"{r['article_importance_score']}점",

                str(
                    r.get(
                        "eval_mode",
                        "-"
                    )
                ),

                title
            ])


    table = Table(

        table_data,

        colWidths=[
            30,
            80,
            50,
            50,
            330
        ]
    )


    table.setStyle(

        TableStyle([

            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#F7FAFC")
            ),

            (
                "FONTNAME",
                (0, 0),
                (-1, -1),
                font_name
            ),

            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "ALIGN",
                (0, 0),
                (3, -1),
                "CENTER"
            ),

            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#CBD5E0")
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE"
            )

        ])
    )


    story.append(table)


    story.append(
        Spacer(1, 10)
    )


    story.append(

        Paragraph(
            "2. 핵심 이슈 및 실무 Insight",
            h2_style
        )
    )


    for idx, issue in enumerate(
        issues_list,
        1
    ):

        story.append(

            Paragraph(

                f"<b>이슈 {idx}: "
                f"{issue.get('core_issue', '')}</b>",

                body_style
            )
        )


        story.append(

            Paragraph(

                f"[핵심 요약] "
                f"{issue.get('core_summary', '')}",

                body_style
            )
        )


        for fact in issue.get(
            "facts",
            []
        ):

            story.append(

                Paragraph(
                    f"[Fact] {fact}",
                    body_style
                )
            )


        story.append(

            Paragraph(

                f"[Why it matters] "
                f"{issue.get('why_it_matters', '')}",

                body_style
            )
        )


        pi = issue.get(
            "product_planning_insight",
            {}
        )


        if isinstance(
            pi,
            dict
        ):

            story.append(

                Paragraph(

                    f"[상품기획 Action] "
                    f"{pi.get('action', '')}",

                    body_style
                )
            )


        si = issue.get(
            "sales_management_insight",
            {}
        )


        if isinstance(
            si,
            dict
        ):

            story.append(

                Paragraph(

                    f"[영업관리 Action] "
                    f"{si.get('action', '')}",

                    body_style
                )
            )


    doc.build(story)


    buffer.seek(0)

    return buffer.getvalue()


# =========================================================
# 🚀 16. 데이터 파이프라인
# =========================================================

raw_df, collection_timestamp = (
    fetch_real_naver_news()
)


top10_df = (
    select_top10_articles(
        raw_df
    )
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
# 🖥️ 17. 화면
# =========================================================

st.title(
    "📊 AI 기반 보험 트렌드 & "
    "이슈 인텔리전스 플랫폼"
)


st.caption(

    "🔄 10대 검증 매체 뉴스 수집 → "
    "Gemini AI 정량 평가 → "
    "핵심 이슈 도출 파이프라인"
)


# =========================================================
# 🔑 API 상태
# =========================================================

with st.sidebar:

    st.subheader(
        "🔐 API 연결 상태"
    )


    if GEMINI_API_KEY:

        st.success(
            "🤖 Gemini API Key 감지됨"
        )

    else:

        st.error(
            "❌ Gemini API Key 없음"
        )


    if NAVER_CLIENT_ID:

        st.success(
            "📰 Naver API 연결정보 감지됨"
        )

    else:

        st.warning(
            "⚠️ Naver API Key 없음 → Demo"
        )


    st.caption(
        f"Gemini 모델: {GEMINI_MODEL}"
    )


# =========================================================
# 📰 언론사 필터
# =========================================================

media_options = (

    list(
        raw_df["언론사"].unique()
    )

    if not raw_df.empty

    else
    ["한국보험신문"]
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


# =========================================================
# 📥 PDF
# =========================================================

st.sidebar.markdown("---")

st.sidebar.subheader(
    "📥 Executive Report"
)


try:

    pdf_data = generate_pdf_report(
        top10_df,
        core_issues
    )


    st.sidebar.download_button(

        label=
        "📄 보험 이슈 리포트 PDF 다운로드",

        data=pdf_data,

        file_name=
        "보험시장_핵심이슈_리포트_"
        f"{datetime.now().strftime('%Y%m%d')}.pdf",

        mime="application/pdf",

        use_container_width=True
    )

except Exception as e:

    st.sidebar.error(
        f"PDF 생성 오류: {e}"
    )


# =========================================================
# 🛠️ 18. 진단 보드
# =========================================================

st.subheader(
    "🛠️ 시스템 데이터 진단 및 평가 현황"
)


col1, col2, col3, col4 = (
    st.columns(4)
)


with col1:

    st.metric(
        "📋 검증 수집 기사 수",
        f"{len(raw_df)}건"
    )


with col2:

    ai_cnt = (

        len(
            raw_df[
                raw_df["eval_mode"]
                == "AI"
            ]
        )

        if (
            not raw_df.empty
            and "eval_mode"
            in raw_df.columns
        )

        else 0
    )


    fb_cnt = (
        len(raw_df) -
        ai_cnt
    )


    st.metric(
        "🤖 AI vs ⚙️ Fallback",
        f"AI {ai_cnt}건 / FB {fb_cnt}건"
    )


with col3:

    if not top10_df.empty:

        type_str = " | ".join(

            [
                f"{k[:4]} {v}"

                for k, v in
                top10_df[
                    "매체구분"
                ]
                .value_counts()
                .items()
            ]
        )

    else:

        type_str = "-"


    st.metric(
        "🎯 TOP 10 매체 구성",
        type_str
    )


with col4:

    st.metric(
        "🧩 도출된 핵심 이슈",
        f"{len(core_issues)}개"
    )


with st.expander(
    "📊 실제 언론사별 수집 통계"
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


st.markdown("---")


# =========================================================
# 🏆 19. TOP 10 그래프
# =========================================================

st.subheader(
    "🏆 이번 주 보험시장 중요도 TOP 10"
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
                "중요도 총점",

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


st.markdown("---")


# =========================================================
# 🧩 20. 핵심 이슈
# =========================================================

st.subheader(
    "🧩 AI 종합 분석: "
    "주간 핵심 이슈 & 실무 Insight"
)


for idx, issue in enumerate(
    core_issues
):

    with st.expander(

        f"📌 [이슈 {idx + 1}] "
        f"{issue.get('core_issue', '이슈')} "
        f"(관련 기사 "
        f"{issue.get('related_article_count', 1)}건)",

        expanded=(idx == 0)
    ):

        st.markdown(
            "**📝 [Core Summary]**"
        )

        st.write(
            issue.get(
                "core_summary",
                ""
            )
        )


        st.markdown(
            "**⚖️ [Why it matters]**"
        )

        st.write(
            issue.get(
                "why_it_matters",
                ""
            )
        )


        st.markdown(
            "**🔍 [Fact - 기사 근거]**"
        )


        for fact in issue.get(
            "facts",
            []
        ):

            match = re.search(
                r"기사\s*#?(\d+)",
                fact
            )


            if match:

                num = int(
                    match.group(1)
                )


                if num in article_url_map:

                    target_url = (
                        article_url_map[
                            num
                        ]["link"]
                    )


                    st.markdown(

                        f"- {fact} "
                        f"👉 [🔗 원문 읽기]"
                        f"({target_url})"
                    )

                else:

                    st.markdown(
                        f"- {fact}"
                    )

            else:

                st.markdown(
                    f"- {fact}"
                )


        left, right = st.columns(2)


        with left:

            st.markdown(
                "##### 📦 상품기획 Insight"
            )


            pi = issue.get(
                "product_planning_insight",
                {}
            )


            if isinstance(
                pi,
                dict
            ):

                st.write(
                    f"• **Fact:** "
                    f"{pi.get('fact', '')}"
                )

                st.write(
                    f"• **Implication:** "
                    f"{pi.get('implication', '')}"
                )

                st.info(
                    f"👉 **Action:** "
                    f"{pi.get('action', '')}"
                )


        with right:

            st.markdown(
                "##### 💼 영업관리 Insight"
            )


            si = issue.get(
                "sales_management_insight",
                {}
            )


            if isinstance(
                si,
                dict
            ):

                st.write(
                    f"• **Fact:** "
                    f"{si.get('fact', '')}"
                )

                st.write(
                    f"• **Implication:** "
                    f"{si.get('implication', '')}"
                )

                st.success(
                    f"👉 **Action:** "
                    f"{si.get('action', '')}"
                )


st.markdown("---")


# =========================================================
# 🔍 21. 기사 정밀 분석 + 스크랩
# =========================================================

bottom_left, bottom_right = (
    st.columns(2)
)


with bottom_left:

    st.subheader(
        "🤖 기사 정밀 분석 및 평가 근거"
    )


    if not filtered_raw_df.empty:

        selected_title = st.selectbox(

            "📄 분석할 기사를 선택하세요",

            options=
            filtered_raw_df[
                "기사제목"
            ].values
        )


        article_info = (

            filtered_raw_df[
                filtered_raw_df[
                    "기사제목"
                ]
                == selected_title
            ]
            .iloc[0]
        )


        st.link_button(

            "🔗 선택한 기사 원문 읽기",

            article_info[
                "기사링크"
            ]
        )


        mode_label = (

            "🤖 AI 분석"

            if article_info.get(
                "eval_mode"
            ) == "AI"

            else "⚙️ Fallback 분석"
        )


        st.markdown(

            f"**📊 중요도:** "
            f"`{article_info['article_importance_score']}점 / 100점` "
            f"| 상태: **{mode_label}** "
            f"| 언론사: **{article_info['언론사']}**"
        )


        st.write(

            f"- 산업: "
            f"{article_info['industry_score']}점 | "

            f"정책: "
            f"{article_info['policy_score']}점 | "

            f"소비자: "
            f"{article_info['consumer_score']}점 | "

            f"시장: "
            f"{article_info['market_score']}점 | "

            f"시의성: "
            f"{article_info['timeliness_score']}점"
        )


        st.info(

            f"✍️ **채점 근거**\n\n"
            f"{article_info['importance_reason']}"
        )


        st.markdown(
            "🔍 **원문 핵심 스니펫**"
        )


        st.write(
            article_info["기사내용"]
        )


with bottom_right:

    st.subheader(
        "📁 대시보드 스크랩 및 노션 백업"
    )


    if not filtered_raw_df.empty:

        st.text_input(

            "📌 스크랩 대상 기사",

            value=selected_title,

            disabled=True
        )


        scrap_insight = st.text_area(

            "📝 오늘의 상품기획 / 영업관리 인사이트",

            placeholder=
            "기사에서 발견한 "
            "상품기획 또는 영업관리 인사이트를 기록하세요."
        )


        if st.button(
            "💾 대시보드 저장 및 노션 백업"
        ):

            if scrap_insight:

                is_duplicate = any(

                    item.get(
                        "기사제목"
                    )
                    == selected_title

                    for item in
                    st.session_state[
                        "scrap_storage"
                    ]
                )


                if not is_duplicate:

                    new_scrap = {

                        "일자":
                            datetime.now().strftime(
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


                    # -----------------------
                    # Notion
                    # -----------------------

                    if (
                        NOTION_TOKEN
                        and
                        NOTION_DATABASE_ID
                    ):

                        notion_url = (
                            "https://api.notion.com/"
                            "v1/pages"
                        )


                        headers = {

                            "Authorization":
                                "Bearer "
                                + NOTION_TOKEN.strip(),

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
                                                    datetime.now().strftime(
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

                                timeout=10
                            )


                            if notion_res.status_code in [
                                200,
                                201
                            ]:

                                st.success(
                                    "🎯 대시보드 저장 + "
                                    "노션 백업 성공!"
                                )

                            else:

                                st.warning(
                                    "⚠️ 대시보드 저장은 성공했지만 "
                                    "노션 전송 실패\n\n"
                                    f"{notion_res.text[:500]}"
                                )

                        except Exception as e:

                            st.warning(
                                f"⚠️ 노션 전송 오류: {e}"
                            )

                    else:

                        st.success(
                            "🎯 대시보드 저장 완료!"
                        )


                    st.rerun()


                else:

                    st.warning(
                        "⚠️ 이미 스크랩한 기사입니다."
                    )


            else:

                st.error(
                    "⚠️ 인사이트 내용을 입력하세요."
                )


    # =====================================================
    # 누적 스크랩
    # =====================================================

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


        display_df = scrap_df.copy()


        edited_df = st.data_editor(

            display_df,

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

            hide_index=True
        )


        updated_data = (
            edited_df
            .to_dict(
                orient="records"
            )
        )


        if (
            updated_data
            !=
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
            "🗑️ 전체 스크랩 내역 삭제"
        ):

            st.session_state[
                "scrap_storage"
            ] = []

            save_scraps([])

            st.success(
                "스크랩 목록을 삭제했습니다."
            )

            st.rerun()


st.markdown("---")


# =========================================================
# 📰 22. 전체 기사 데이터
# =========================================================

st.subheader(
    "📰 최근 7일간 검증 매체 기사 데이터"
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
