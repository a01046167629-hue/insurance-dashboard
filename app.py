import html
import io
import json
import os
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


st.set_page_config(
    page_title="AI 기반 보험 트렌드 인텔리전스",
    page_icon="📈",
    layout="wide",
)

NAVER_CLIENT_ID = str(
    st.secrets.get("NAVER_CLIENT_ID", os.getenv("NAVER_CLIENT_ID", ""))
).strip()
NAVER_CLIENT_SECRET = str(
    st.secrets.get("NAVER_CLIENT_SECRET", os.getenv("NAVER_CLIENT_SECRET", ""))
).strip()
GEMINI_API_KEY = str(
    st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
).strip()
NOTION_TOKEN = str(
    st.secrets.get("NOTION_TOKEN", os.getenv("NOTION_TOKEN", ""))
).strip()
NOTION_DATABASE_ID = str(
    st.secrets.get("NOTION_DATABASE_ID", os.getenv("NOTION_DATABASE_ID", ""))
).strip()

NAVER_URL = "https://openapi.naver.com/v1/search/news.json"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
)
SCRAP_FILE = "insurance_scraps.csv"

TARGET_PRESS_CONFIG = {
    "한국보험신문": {
        "type": "보험 전문지",
        "domains": ["insweek.co.kr"],
        "query": '"한국보험신문" 보험',
    },
    "보험매일": {
        "type": "보험 전문지",
        "domains": ["fins.co.kr"],
        "query": '"보험매일" 보험',
    },
    "보험신문": {
        "type": "보험 전문지",
        "domains": ["bohumnews.com"],
        "query": '"보험신문" 보험',
    },
    "대한금융신문": {
        "type": "금융 전문지",
        "domains": ["kbanker.co.kr"],
        "query": '"대한금융신문" 보험',
    },
    "CEO스코어데일리": {
        "type": "기업·경영 전문지",
        "domains": ["ceoscoredaily.com"],
        "query": '"CEO스코어데일리" 보험',
    },
    "매일경제": {
        "type": "경제지",
        "domains": ["mk.co.kr"],
        "query": '"매일경제" 보험',
    },
    "한국경제": {
        "type": "경제지",
        "domains": ["hankyung.com"],
        "query": '"한국경제" 보험',
    },
    "머니투데이": {
        "type": "경제지",
        "domains": ["mt.co.kr"],
        "query": '"머니투데이" 보험',
    },
    "서울경제": {
        "type": "경제지",
        "domains": ["sedaily.com"],
        "query": '"서울경제" 보험',
    },
    "연합뉴스": {
        "type": "종합지",
        "domains": ["yna.co.kr", "yonhapnewstv.co.kr"],
        "query": '"연합뉴스" 보험',
    },
}


def add_diagnostic(kind, message):
    """API 오류를 숨기지 않고 화면에 표시하기 위한 함수"""
    st.session_state.setdefault("api_diagnostics", [])

    item = f"{kind}: {message}"
    if item not in st.session_state["api_diagnostics"]:
        st.session_state["api_diagnostics"].append(item)


def clean_html(value):
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def normalize_title(title):
    text = re.sub(r"\[.*?\]|\(.*?\)", "", title or "")
    return set(re.sub(r"[^\w\s]", " ", text).lower().split())


def is_duplicate_article(tokens, previous_tokens):
    for old_tokens in previous_tokens:
        if not tokens or not old_tokens:
            continue

        similarity = len(tokens & old_tokens) / len(tokens | old_tokens)
        if similarity >= 0.55:
            return True

    return False


def fallback_score(title, description, published_at):
    """Gemini를 사용할 수 없을 때의 규칙 기반 보조 평가"""
    text = f"{title} {description}".lower()

    if any(keyword in text for keyword in [
        "ifrs17", "csm", "k-ics", "지급여력", "자본확충"
    ]):
        industry = 23
    elif any(keyword in text for keyword in [
        "손해율", "언더라이팅", "수익성"
    ]):
        industry = 18
    else:
        industry = 10

    if any(keyword in text for keyword in [
        "금감원", "금융위", "금융감독원", "시행령", "감독규정", "가이드라인"
    ]):
        policy = 18
    elif any(keyword in text for keyword in [
        "제도개편", "개선안", "공청회", "논의"
    ]):
        policy = 13
    else:
        policy = 5

    if any(keyword in text for keyword in [
        "실손", "비급여", "보험료", "약관", "지급기준"
    ]):
        consumer = 18
    elif any(keyword in text for keyword in [
        "펫보험", "유병자", "고령", "치매"
    ]):
        consumer = 13
    else:
        consumer = 5

    if any(keyword in text for keyword in [
        "점유율", "가격경쟁", "ga", "제3보험"
    ]):
        market = 17
    elif any(keyword in text for keyword in [
        "신상품", "특약", "담보"
    ]):
        market = 12
    else:
        market = 6

    days = max(0, (datetime.now() - published_at.replace(tzinfo=None)).days)
    timeliness = 14 if days <= 1 else 11 if days <= 3 else 8 if days <= 5 else 4

    return {
        "article_importance_score": industry + policy + consumer + market + timeliness,
        "industry_score": industry,
        "policy_score": policy,
        "consumer_score": consumer,
        "market_score": market,
        "timeliness_score": timeliness,
        "importance_reason": (
            "규칙 기반 보조 평가입니다. "
            "Gemini API 진단 메시지를 확인하세요."
        ),
        "eval_mode": "Fallback",
    }


def gemini_json(prompt, timeout=45):
    """
    AQ. 형식 Gemini 인증 키를 지원한다.
    핵심: URL ?key=가 아니라 x-goog-api-key 헤더로 전송한다.
    """
    if not GEMINI_API_KEY:
        add_diagnostic("Gemini", "GEMINI_API_KEY가 설정되지 않았습니다.")
        return None

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }

    last_error = "알 수 없는 오류"

    for _ in range(2):
        try:
            response = requests.post(
                GEMINI_URL,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": GEMINI_API_KEY,
                },
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()

            data = response.json()
            response_text = data["candidates"][0]["content"]["parts"][0]["text"]

            return json.loads(response_text)

        except requests.RequestException as error:
            if error.response is not None:
                last_error = error.response.text[:500]
            else:
                last_error = str(error)

        except (KeyError, IndexError, ValueError) as error:
            last_error = f"Gemini 응답 형식 오류: {error}"

    add_diagnostic("Gemini", last_error)
    return None


def evaluate_articles_batch_with_gemini(articles):
    if not articles:
        return []

    article_context = "\n\n".join(
        (
            f"기사 #{index}\n"
            f"제목: {article['기사제목']}\n"
            f"요약: {article['기사내용']}\n"
            f"언론사: {article['언론사']}"
        )
        for index, article in enumerate(articles, 1)
    )

    prompt = f"""
당신은 대한민국 보험산업 분석가입니다.

아래 보험 기사만 근거로 각 기사의 중요도를 평가하세요.

{article_context}

반드시 아래 JSON 형식만 반환하세요.

{{
  "evaluations": [
    {{
      "index": 1,
      "industry_score": 0,
      "policy_score": 0,
      "consumer_score": 0,
      "market_score": 0,
      "timeliness_score": 0,
      "importance_reason": "평가 근거"
    }}
  ]
}}

배점:
- 산업 영향도: 0~25점
- 정책/제도 영향도: 0~20점
- 소비자 영향도: 0~20점
- 시장 영향도: 0~20점
- 시의성: 0~15점

산업 21~25점은 보험산업 전반의 구조 변화,
정책 16~20점은 직접적인 제도 변화,
소비자 16~20점은 다수 가입자 직접 영향,
시장 16~20점은 경쟁구도 또는 수익성의 큰 영향,
시의성 13~15점은 현재 진행 중인 긴급 현안입니다.
"""

    response_data = gemini_json(prompt)
    evaluations = (
        response_data.get("evaluations", [])
        if isinstance(response_data, dict)
        else []
    )

    results = []

    for index, article in enumerate(articles, 1):
        evaluation = next(
            (
                item
                for item in evaluations
                if item.get("index") == index
            ),
            None,
        )

        if not isinstance(evaluation, dict):
            results.append(
                fallback_score(
                    article["기사제목"],
                    article["기사내용"],
                    article["pub_datetime"],
                )
            )
            continue

        try:
            industry = max(0, min(25, int(evaluation.get("industry_score", 0))))
            policy = max(0, min(20, int(evaluation.get("policy_score", 0))))
            consumer = max(0, min(20, int(evaluation.get("consumer_score", 0))))
            market = max(0, min(20, int(evaluation.get("market_score", 0))))
            timeliness = max(0, min(15, int(evaluation.get("timeliness_score", 0))))

            results.append({
                "article_importance_score": (
                    industry + policy + consumer + market + timeliness
                ),
                "industry_score": industry,
                "policy_score": policy,
                "consumer_score": consumer,
                "market_score": market,
                "timeliness_score": timeliness,
                "importance_reason": str(
                    evaluation.get("importance_reason", "AI 평가 완료")
                ),
                "eval_mode": "AI",
            })

        except (TypeError, ValueError):
            results.append(
                fallback_score(
                    article["기사제목"],
                    article["기사내용"],
                    article["pub_datetime"],
                )
            )

    return results


def load_demo_data():
    now = datetime.now()

    rows = [
        (
            "IFRS17·CSM 공시 강화…보험사 자본관리 부담 커진다",
            "회계 기준과 지급여력 관리 관련 보도입니다.",
            "한국보험신문",
            "보험 전문지",
        ),
        (
            "금감원, 실손보험 비급여 관리 개선안 검토",
            "실손보험 보장과 소비자 부담 관련 정책 논의입니다.",
            "매일경제",
            "경제지",
        ),
    ]

    data = []

    for title, description, press, press_type in rows:
        data.append({
            "날짜": now.strftime("%Y-%m-%d"),
            "언론사": press,
            "매체구분": press_type,
            "기사제목": title,
            "기사내용": description,
            "기사링크": "https://news.naver.com",
            "pub_datetime": now,
            **fallback_score(title, description, now),
        })

    return pd.DataFrame(data)


@st.cache_data(ttl=timedelta(hours=2), show_spinner=False)
def fetch_real_naver_news():
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        add_diagnostic(
            "Naver",
            "NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET이 설정되지 않았습니다.",
        )
        return load_demo_data(), collected_at

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    cutoff = datetime.now() - timedelta(days=7)

    blacklist = [
        "이벤트", "출시기념", "증정", "공식 sns",
        "기프티콘", "사은품", "팝업", "업무협약",
        "mou", "공모전", "보도자료",
    ]

    seen_titles = []
    articles = []

    for press_name, config in TARGET_PRESS_CONFIG.items():
        try:
            response = requests.get(
                NAVER_URL,
                headers=headers,
                params={
                    "query": config["query"],
                    "display": 40,
                    "sort": "date",
                },
                timeout=15,
            )
            response.raise_for_status()
            items = response.json().get("items", [])

        except requests.RequestException as error:
            detail = (
                error.response.text[:300]
                if error.response is not None
                else str(error)
            )
            add_diagnostic("Naver", f"{press_name} 조회 실패: {detail}")
            continue

        for item in items:
            try:
                published_at = parsedate_to_datetime(
                    item.get("pubDate", "")
                ).replace(tzinfo=None)
            except (TypeError, ValueError):
                published_at = datetime.now()

            if published_at < cutoff:
                continue

            title = clean_html(item.get("title"))
            description = clean_html(item.get("description"))

            article_url = (
                item.get("originallink", "").strip()
                or item.get("link", "").strip()
            )

            host = urlparse(article_url).netloc.lower()
            tokens = normalize_title(title)

            if not title:
                continue

            if not any(domain in host for domain in config["domains"]):
                continue

            if any(word in title.lower() for word in blacklist):
                continue

            if is_duplicate_article(tokens, seen_titles):
                continue

            articles.append({
                "날짜": published_at.strftime("%Y-%m-%d"),
                "언론사": press_name,
                "매체구분": config["type"],
                "기사제목": title,
                "기사내용": description,
                "기사링크": article_url,
                "pub_datetime": published_at,
            })

            seen_titles.append(tokens)

    if not articles:
        add_diagnostic(
            "Naver",
            "최근 7일 조건을 만족하는 기사를 찾지 못해 데모 데이터를 표시합니다.",
        )
        return load_demo_data(), collected_at

    evaluations = evaluate_articles_batch_with_gemini(articles)

    combined = [
        {**article, **evaluation}
        for article, evaluation in zip(articles, evaluations)
    ]

    return pd.DataFrame(combined), collected_at


def select_top10_articles(dataframe):
    if dataframe.empty:
        return dataframe.copy()

    selected_rows = []
    press_count = {}

    sorted_dataframe = dataframe.sort_values(
        "article_importance_score",
        ascending=False,
    )

    for _, row in sorted_dataframe.iterrows():
        press = row["언론사"]

        if press_count.get(press, 0) >= 2:
            continue

        selected_rows.append(row)
        press_count[press] = press_count.get(press, 0) + 1

        if len(selected_rows) == 10:
            break

    result = pd.DataFrame(selected_rows)
    result.insert(0, "순위", range(1, len(result) + 1))

    return result


def analyze_core_issues(top10_dataframe):
    if top10_dataframe.empty:
        return []

    context = "\n".join(
        (
            f"#{row['순위']} "
            f"{row['기사제목']} | {row['기사내용']}"
        )
        for _, row in top10_dataframe.iterrows()
    )

    prompt = f"""
다음 보험 기사만 근거로 이번 주 핵심 이슈 3~5개를 JSON으로 작성하세요.

{context}

반드시 다음 형식만 반환하세요.

{{
  "issues": [
    {{
      "core_issue": "이슈명",
      "core_summary": "핵심 내용",
      "why_it_matters": "중요한 이유",
      "related_article_numbers": [1],
      "product_action": "상품기획 행동",
      "sales_action": "영업관리 행동"
    }}
  ]
}}

사실과 추론을 구분하고, 기사에 없는 수치를 만들지 마세요.
"""

    response_data = gemini_json(prompt)

    if (
        isinstance(response_data, dict)
        and isinstance(response_data.get("issues"), list)
    ):
        return response_data["issues"]

    return [{
        "core_issue": "기사 중요도 기반 주간 모니터링",
        "core_summary": (
            "Gemini API가 연결되지 않아 규칙 기반 평가 결과를 표시하고 있습니다."
        ),
        "why_it_matters": (
            "API 진단 메시지를 확인한 뒤 Gemini 연결을 완료하세요."
        ),
        "related_article_numbers": top10_dataframe["순위"].tolist(),
        "product_action": "핵심 기사별 상품 영향을 검토합니다.",
        "sales_action": "고객 문의 가능성과 판매 현장 영향을 점검합니다.",
    }]


def make_pdf(top10_dataframe, issues):
    buffer = io.BytesIO()
    styles = getSampleStyleSheet()

    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
    )

    story = [
        Paragraph("Insurance Trend Intelligence Report", styles["Title"]),
        Spacer(1, 10),
    ]

    table_data = [["Rank", "Press", "Score", "Title"]]

    for _, row in top10_dataframe.iterrows():
        table_data.append([
            str(row["순위"]),
            str(row["언론사"]),
            str(row["article_importance_score"]),
            str(row["기사제목"])[:65],
        ])

    report_table = Table(
        table_data,
        colWidths=[35, 80, 40, 360],
    )

    report_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
    ]))

    story += [
        report_table,
        Spacer(1, 12),
        Paragraph("Key issues", styles["Heading2"]),
    ]

    for issue in issues:
        story += [
            Paragraph(
                str(issue.get("core_issue", "Issue")),
                styles["Heading3"],
            ),
            Paragraph(
                str(issue.get("core_summary", "")),
                body_style,
            ),
            Paragraph(
                "Product: " + str(issue.get("product_action", "")),
                body_style,
            ),
            Paragraph(
                "Sales: " + str(issue.get("sales_action", "")),
                body_style,
            ),
            Spacer(1, 5),
        ]

    SimpleDocTemplate(buffer, pagesize=A4).build(story)

    return buffer.getvalue()


def save_scrap(item):
    dataframe = pd.DataFrame([item])

    dataframe.to_csv(
        SCRAP_FILE,
        mode="a",
        header=not os.path.exists(SCRAP_FILE),
        index=False,
        encoding="utf-8-sig",
    )


def send_to_notion(item):
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        return False, "Notion 설정이 없어 로컬 CSV에만 저장했습니다."

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "기사제목": {
                "title": [{"text": {"content": item["기사제목"]}}],
            },
            "날짜": {
                "rich_text": [{"text": {"content": item["날짜"]}}],
            },
            "인사이트": {
                "rich_text": [{"text": {"content": item["인사이트"]}}],
            },
        },
    }

    try:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers={
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        response.raise_for_status()

        return True, "Notion 백업까지 완료했습니다."

    except requests.RequestException as error:
        detail = (
            error.response.text[:300]
            if error.response is not None
            else str(error)
        )
        return False, f"로컬 저장은 완료했지만 Notion 전송 실패: {detail}"


st.title("📈 AI 기반 보험 트렌드 & 이슈 인텔리전스")
st.caption(
    "최근 7일의 검증 매체 뉴스를 분석하여 "
    "보험시장 핵심 이슈와 실무 인사이트를 제공합니다."
)

if st.button("🔄 뉴스·AI 분석 새로고침"):
    st.cache_data.clear()
    st.session_state["api_diagnostics"] = []
    st.rerun()

raw_df, collection_timestamp = fetch_real_naver_news()
top10_df = select_top10_articles(raw_df)
core_issues = analyze_core_issues(top10_df)

ai_count = int((raw_df["eval_mode"] == "AI").sum()) if not raw_df.empty else 0
fallback_count = len(raw_df) - ai_count

col1, col2, col3, col4 = st.columns(4)

col1.metric("검증 수집 기사 수", f"{len(raw_df)}건")
col2.metric("AI vs Fallback", f"AI {ai_count}건 / FB {fallback_count}건")
col3.metric("TOP 10 기사", f"{len(top10_df)}건")
col4.metric("도출 핵심 이슈", f"{len(core_issues)}개")

if st.session_state.get("api_diagnostics"):
    with st.expander("⚠️ API 진단 메시지", expanded=ai_count == 0):
        for message in st.session_state["api_diagnostics"]:
            st.error(message)

st.subheader("이번 주 중요도 TOP 10")

if not top10_df.empty:
    figure = px.bar(
        top10_df,
        x="순위",
        y="article_importance_score",
        color="매체구분",
        hover_data=[
            "언론사",
            "기사제목",
            "eval_mode",
            "importance_reason",
        ],
        text="article_importance_score",
    )

    st.plotly_chart(figure, use_container_width=True)

    st.dataframe(
        top10_df[
            [
                "순위",
                "날짜",
                "언론사",
                "기사제목",
                "article_importance_score",
                "eval_mode",
                "기사링크",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "기사링크": st.column_config.LinkColumn("원문"),
        },
    )

    st.download_button(
        "📄 PDF 리포트 다운로드",
        make_pdf(top10_df, core_issues),
        file_name=f"보험_인사이트_{datetime.now():%Y%m%d}.pdf",
        mime="application/pdf",
    )

st.subheader("AI 종합 분석: 핵심 이슈와 실무 인사이트")

for issue in core_issues:
    with st.expander(f"🧩 {issue.get('core_issue', '핵심 이슈')}"):
        st.write(issue.get("core_summary", ""))
        st.caption("중요한 이유: " + str(issue.get("why_it_matters", "")))
        st.info("상품기획 Action: " + str(issue.get("product_action", "")))
        st.success("영업관리 Action: " + str(issue.get("sales_action", "")))

st.subheader("기사 스크랩 및 인사이트")

if not raw_df.empty:
    selected_title = st.selectbox(
        "기사 선택",
        raw_df["기사제목"].tolist(),
    )

    insight = st.text_area("나의 상품기획 / 영업관리 인사이트")

    if st.button("💾 로컬 저장 및 Notion 백업"):
        if not insight.strip():
            st.warning("인사이트를 입력하세요.")

        else:
            selected_row = raw_df.loc[
                raw_df["기사제목"] == selected_title
            ].iloc[0]

            scrap = {
                "날짜": datetime.now().strftime("%Y-%m-%d"),
                "기사제목": selected_title,
                "기사링크": selected_row["기사링크"],
                "인사이트": insight.strip(),
            }

            save_scrap(scrap)
            success, message = send_to_notion(scrap)

            if success:
                st.success(message)
            else:
                st.warning(message)

with st.expander("전체 수집 기사"):
    st.dataframe(
        raw_df.drop(columns=["pub_datetime"], errors="ignore"),
        use_container_width=True,
        hide_index=True,
    )
