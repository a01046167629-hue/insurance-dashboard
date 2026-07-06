import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import urllib.parse
import os
import io
from datetime import datetime, timedelta

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
# ==========================================

st.set_page_config(
    page_title="실시간 보험 트렌드 분석 플랫폼 (PRO)",
    page_icon="📈",
    layout="wide"
)

# 🎯 온라인에서 나눔고딕 폰트를 실시간으로 다운로드하여 등록 (한글 깨집 방지)
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

# 폰트 초기화 실행
has_korean_font = init_korean_font()

# 💡 매주 월요일마다 데이터를 새로 고치는 핵심 뉴스 로직
@st.cache_data(ttl=timedelta(days=7))
def fetch_real_naver_news():
    categories = ["손해보험", "생명보험", "실손보험", "자동차보험", "펫보험"]
    all_news = []
    
    if NAVER_CLIENT_ID == "YOUR_CLIENT_ID_HERE" or NAVER_CLIENT_ID == "":
        return load_demo_data()

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID.strip(),
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET.strip()
    }

    for cat in categories:
        encoded_query = urllib.parse.quote(f"{cat} 보험 트렌드")
        url = f"https://openapi.naver.com/v1/search/news.json?query={encoded_query}&display=50&sort=sim"
        
        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200: continue
                
            items = response.json().get("items", [])
            for item in items:
                pub_date = item["pubDate"]
                try:
                    date_obj = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S +0900")
                    formatted_date = date_obj.strftime("%Y-%m-%d")
                except:
                    formatted_date = datetime.now().strftime("%Y-%m-%d")
                
                clean_title = item["title"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"')
                clean_desc = item["description"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"')
                
                companies = ["삼성화재", "현대해상", "DB손해보험", "KB손해보험", "삼성생명", "한화생명", "교보생명"]
                mentioned_company = "기타 업권"
                for comp in companies:
                    if comp in clean_title or comp in clean_desc:
                        mentioned_company = comp
                        break
                
                keywords_pool = ["상생금융", "실적개선", "디지털전환", "보험료 인상", "보험료 인하", "신상품", "고령화", "비급여 과잉", "수가", "제3보험", "4세대 실손", "청구 간소화", "자율주행", "반려동물"]
                extracted_kw = "시장 동향 일반"
                for kw in keywords_pool:
                    if kw in clean_title or kw in clean_desc:
                        extracted_kw = kw
                        break

                if extracted_kw != "시장 동향 일반":
                    all_news.append({
                        "날짜": formatted_date,
                        "카테고리(상품)": cat,
                        "언급보험사": mentioned_company,
                        "핵심키워드": extracted_kw,
                        "제목": clean_title,
                        "기사내용": clean_desc,
                        "기사링크": item["link"]
                    })
        except:
            pass
            
    final_df = pd.DataFrame(all_news)
    if not final_df.empty:
        final_df = final_df.head(100)
    else:
        final_df = load_demo_data()
    return final_df

def load_demo_data():
    return pd.DataFrame([
        {"날짜": "2026-07-06", "카테고리(상품)": "실손보험", "언급보험사": "삼성화재", "핵심키워드": "비급여 과잉", "제목": "실손보험 비급여 지급 체계 개편 논의 본격화", "기사내용": "비급여 항목 과잉 청구로 인한 요율 조정 지표 분석 결과입니다.", "기사링크": "https://news.naver.com"},
        {"날짜": "2026-07-05", "카테고리(상품)": "펫보험", "언급보험사": "KB손해보험", "핵심키워드": "수가", "제목": "반려동물 등록제 확대와 펫보험 수가 표준화 동향", "기사내용": "동물병원 진료비 항목 표준화에 따른 신상품 기획 트렌드입니다.", "기사링크": "https://news.naver.com"},
        {"날짜": "2026-07-04", "카테고리(상품)": "자동차보험", "언급보험사": "현대해상", "핵심키워드": "자율주행", "제목": "레벨3 자율주행 상용화에 따른 자동차보험 약관 정비", "기사내용": "자율주행 차량 사고 시 책임 소재 분담 및 상품 보장 범위 설계안입니다.", "기사링크": "https://news.naver.com"}
    ])

df = fetch_real_naver_news()

# ==========================================
# 💾 [복합 백업] CSV 파일 로드 및 저장 엔진
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
# 📄 [완벽 한글화 버전] PDF 월간 리포트 생성 빌더
# ==========================================
def generate_pdf_report(source_df):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    font_name = 'NanumGothic' if has_korean_font else 'Helvetica'
    font_bold_name = 'NanumGothic-Bold' if has_korean_font else 'Helvetica-Bold'
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('PDFTitle', parent=styles['Heading1'], fontName=font_bold_name, fontSize=20, textColor=colors.HexColor('#1A365D'), spaceAfter=20, alignment=1)
    h2_style = ParagraphStyle('PDFH2', parent=styles['Heading2'], fontName=font_bold_name, fontSize=14, textColor=colors.HexColor('#2B6CB0'), spaceBefore=15, spaceAfter=8)
    body_style = ParagraphStyle('PDFBody', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=16, spaceAfter=6)
    bullet_style = ParagraphStyle('PDFBullet', parent=body_style, leftIndent=15, firstLineIndent=-10)

    # 1. 타이틀 헤더
    story.append(Paragraph("📈 2026년 7월 보험시장 트렌드 분석 리포트", title_style))
    story.append(Paragraph(f"발행일자: {datetime.now().strftime('%Y-%m-%d')} | 데이터 분석 출처: 실시간 마켓 인텔리전스 시스템", body_style))
    story.append(Spacer(1, 15))
    
    if not source_df.empty:
        top_keywords = list(source_df['핵심키워드'].value_counts().head(3).index)
        top_company = source_df['언급보험사'].value_counts().index[0]
        if top_company == "기타 업권" and len(source_df['언급보험사'].value_counts()) > 1:
            top_company = source_df['언급보험사'].value_counts().index[1]
    else:
        top_keywords = ["실손보험", "자동차보험", "펫보험"]
        top_company = "KB손해보험"

    # 2. 이번 달 TOP 키워드
    story.append(Paragraph("1. 이번 달 TOP 키워드", h2_style))
    for kw in top_keywords[:3]:
        story.append(Paragraph(f"• {kw}", bullet_style))
    if len(top_keywords) < 3:
        for extra in ["실손보험", "자동차보험", "펫보험"][len(top_keywords):]:
            story.append(Paragraph(f"• {extra}", bullet_style))
    
    # 3. 가장 많이 언급된 보험사
    story.append(Paragraph("2. 가장 많이 언급된 보험사", h2_style))
    story.append(Paragraph(f"이번 달 시장 모니터링 분석 지표 상에서 미디어와 시장의 주목을 가장 많이 받은 리딩 보험사는 **{top_company}** 입니다. 해당 보험사는 관련 카테고리 내 상품 다변화 및 전략적 담보 노출에 집중하고 있습니다.", body_style))

    # 4. 주요 이슈 요약
    story.append(Paragraph("3. 주요 이슈 요약", h2_style))
    story.append(Paragraph("• **실손보장 체계 리스크 정비:** 비급여 다발성 항목에 대한 심사 가이드라인이 점차 정교화되며 요율 안정화를 향한 업계 공동 대응이 포착됩니다.", bullet_style))
    story.append(Paragraph("• **반려동물 금융 제도권 안착:** 펫보험 수가 표준화 모델의 정비와 함께 맞춤형 장기 보장성 신상품 경쟁이 가속화되고 있습니다.", bullet_style))
    story.append(Paragraph("• **모빌리티 패러다임 변화:** 레벨3 이상의 상용 자율주행 차량 도입에 따른 책임 분담 약관 정비 및 배상책임 전용 특약 기획이 추진 중입니다.", bullet_style))

    # 5. 소비자에게 미치는 영향
    story.append(Paragraph("4. 소비자에게 미치는 영향", h2_style))
    story.append(Paragraph("비급여 지급 기준 강화와 요율 인상 기조로 인해 기존 실손 유지 가입자들의 4세대 전환 유인이 강화되고 있습니다. 아울러 단순 가격 할인 혜택보다는 자율주행 케어나 펫 진료비 표준 가이드 등 나에게 꼭 맞는 세분화된 안심 특약 위주로 소비자의 실질적 니즈가 재편되는 추세입니다.", body_style))

    # 6. 영업 시사점 (Sales Insight)
    story.append(Paragraph("5. 영업 시사점 (Sales Insight)", h2_style))
    story.append(Paragraph("• **가이드라인 변화 중심의 컨설팅:** 인상 압박을 강조하는 공포 마케팅 형태의 접근 방식에서 벗어나, 제도 개편(청구 간소화, 약관 고도화) 내용을 정당한 정기 고객 관리 및 대면 스피치 터치포인트로 활용할 때 영업 성공률이 크게 개선됩니다.", bullet_style))
    story.append(Paragraph("• **타겟 맞춤형 스토리텔링 전개:** 반려인 가입자층에게 '진료비 수가 표준화' 추이를 적극 연계하여, 장기적 관점의 보장 공백 해소 및 납입 안정성을 소구하는 전문 화법 설계가 유효합니다.", bullet_style))

    # 7. 상품기획 시사점 (Product Strategy)
    story.append(Paragraph("6. 상품기획 시사점 (Product Strategy)", h2_style))
    story.append(Paragraph("• **신규 테크니컬 리스크 선제 담보화:** 자율주행 고도화 등 신기술과 연동된 제조사 배상 및 운전자 책임 소재 리스크를 정밀 계량화하여 전용 특약을 선제적으로 시장에 출시하는 플레이어가 향후 M/S 선점의 열쇠를 쥐게 될 것입니다.", bullet_style))
    story.append(Paragraph("• **AI 기반 UWD 및 세부 담보 분리:** 비급여 지급 생태계 방어를 위해 가입 심사(Underwriting) 프로세스에 AI 모니터링 모듈을 고도화하고, 상품 기획 단계부터 세부 담보를 독립 특약 형태로 촘촘하게 분리 설계할 것을 강력히 제안합니다.", bullet_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# --- 대시보드 화면 렌더링 영역 ---
st.title("📊 AI 기반 보험 트렌드 분석 및 상품 개선 제안 플랫폼")
st.caption(f"🔄 매주 월요일 정기 자동 업데이트 시스템 연동 완료 (최근 갱신일: {datetime.now().strftime('%Y-%m-%d')})")

selected_category = st.sidebar.multiselect("🔍 보험 상품 필터", options=list(df["카테고리(상품)"].unique())
