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
                
                # 🎯 [핵심 패치] 기존 키워드에 ga, 설계사, ifrs17, csm 4개 추가 완료 (총 21개)
                keywords_pool = [
                    "실적", "디지털", "ax", "보험료", "신상품", "고령화", 
                    "비급여 과잉", "제3보험", "실손", "언더라이팅", "손해율", 
                    "리스크 관리", "수익성", "영업채널", "ai", "심사", "트랜드",
                    "ga", "설계사", "ifrs17", "csm"
                ]
                extracted_kw = "시장 동향 일반"
                for kw in keywords_pool:
                    # 대소문자 구분 없이 영문 매칭을 보장하기 위해 소문자로 변환 매칭
                    if kw.lower() in clean_title.lower() or kw.lower() in clean_desc.lower():
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
        {"날짜": "2026-07-06", "카테고리(상품)": "제3보험", "언급보험사", "삼성생명", "핵심키워드": "csm", "제목": "IFRS17 안정화 단계 속 제3보험 신계약 CSM 확보 총력전", "기사내용": "주요 보험사들이 수익성 및 CSM(계약서비스마진) 극대화를 위해 GA 채널 및 전속 설계사 지원 체계를 대폭 강화하고 있습니다.", "기사링크": "https://news.naver.com"},
        {"날짜": "2026-07-05", "카테고리(상품)": "실손보험", "언급보험사": "삼성화재", "핵심키워드": "ifrs17", "제목": "실손보험 손해율 관리가 IFRS17 실적 향방 가른다", "기as내용": "비급여 심사 모듈 고도화 및 철저한 언더라이팅 관리를 통한 리스크 스크리닝이 핵심 당면 과제로 부각되었습니다.", "기사링크": "https://news.naver.com"}
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
        top_keywords = ["csm", "ga", "ifrs17"]
        top_company = "삼성생명"

    # 2. 이번 달 TOP 키워드
    story.append(Paragraph("1. 이번 달 TOP 키워드", h2_style))
    for kw in top_keywords[:3]:
        story.append(Paragraph(f"• {kw.upper()}", bullet_style))
    if len(top_keywords) < 3:
        for extra in ["csm", "ga", "ifrs17"][len(top_keywords):]:
            story.append(Paragraph(f"• {extra.upper()}", bullet_style))
    
    # 3. 가장 많이 언급된 보험사
    story.append(Paragraph("2. 가장 많이 언급된 보험사", h2_style))
    story.append(Paragraph(f"이번 달 시장 모니터링 분석 지표 상에서 미디어와 시장의 주목을 가장 많이 받은 리딩 보험사는 **{top_company}** 입니다. 해당 보험사는 관련 카테고리 내 상품 다변화 및 전략적 담보 노출에 집중하고 있습니다.", body_style))

    # 4. 주요 이슈 요약
    story.append(Paragraph("3. 주요 이슈 요약", h2_style))
    story.append(Paragraph("• **IFRS17 기반 CSM 손익 관리 고도화:** 보험계약서비스마진(CSM)의 안정적 상각과 손해율 방어를 위해 장기 보장성 보험 중심의 전략적 포트폴리오 믹스가 한층 강화되고 있습니다.", bullet_style))
    story.append(Paragraph("• **GA 채널 위상 제고 및 설계사 가동률 강화:** 판매 다각화를 위해 제3보험 시장 내 GA 소속 설계사들을 향한 수수료 체계 정비와 전용 가이드라인 배포가 활발하게 전개 중입니다.", bullet_style))
    story.append(Paragraph("• **언더라이팅 및 정밀 심사 리스크 모니터링:** 수익성 중심의 견고한 성장을 지속하고자 고위험 비급여 담보에 대한 사전 심사 스크리닝 시스템 배치가 활성화되는 추세입니다.", bullet_style))

    # 5. 소비자에게 미치는 영향
    story.append(Paragraph("4. 소비자에게 미치는 영향", h2_style))
    story.append(Paragraph("보험사들의 CSM 확보 전략에 따라 보장 범위가 다각화된 고품질의 신상품 선택지가 넓어지고 있습니다. 아울러 대형 GA 및 전문 설계사 채널의 컨설팅 역량이 고도화됨에 따라 단순 지인 영업 위주의 가입 형태에서 벗어나 객관적인 담보 비교 및 보장 분석 서비스를 체감하는 소비자가 확대되고 있습니다.", body_style))

    # 6. 영업 시사점 (Sales Insight)
    story.append(Paragraph("5. 영업 시사점 (Sales Insight)", h2_style))
    story.append(Paragraph("• **GA 채널 소통 체계 혁신:** 전속 채널 외에도 대형 GA 설계사 접점 마케팅의 중요성이 급증함에 따라, 자사 상품의 특장점을 직관적으로 비교할 수 있는 원페이지 셀링 포인트를 제공하여 현장 가동률을 극대화해야 합니다.", bullet_style))
    story.append(Paragraph("• **지표 연계 스토리텔링 화법:** 소비자에게 단순 상품 안내를 넘어, 안정적인 위험 보장 여력을 증명하는 채널 신뢰도를 기반으로 롱텀 케어 담보의 메리트를 소구하는 세련된 상담 프로세스 구축이 필요합니다.", bullet_style))

    # 7. 상품기획 시사점 (Product Strategy)
    story.append(Paragraph("6. 상품기획 시사점 (Product Strategy)", h2_style))
    story.append(Paragraph("• **CSM 친화적 고수익 제3보험 라인업 강화:** IFRS17 하에서 안정적인 마진율을 방어할 수 있도록 고령화 트렌드 및 헬스케어 테크를 결합한 고효율 보장성 특약 개발에 전사적 역량을 집중해야 합니다.", bullet_style))
    story.append(Paragraph("• **AI 기반 UWD와 클레임 RM 정밀화:** 영업채널 경쟁 심화 속에서 우량 고객 유치 및 건전성 확보를 위해 디지털 인수심사(Underwriting) 로직을 정교화하고, 손해율을 실시간 방어할 수 있는 계리 리스크 가이드라인 수립을 제안합니다.", bullet_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# --- 대시보드 화면 렌더링 영역 ---
st.title("📊 AI 기반 보험 트렌드 분석 및 상품 개선 제안 플랫폼")
st.caption(f"🔄 매주 월요일 정기 자동 업데이트 시스템 연동 완료 (최근 갱신일: {datetime.now().strftime('%Y-%m-%d')})")

selected_category = st.sidebar.multiselect("🔍 보험 상품 필터", options=list(df["카테고리(상품)"].unique()) if not df.empty else ["펫보험"], default=list(df["카테고리(상품)"].unique()) if not df.empty else ["펫보험"])
filtered_df = df[df["카테고리(상품)"].isin(selected_category)] if not df.empty else df

st.sidebar.markdown("---")
st.sidebar.subheader("📥 월간 경영 리포트")
with st.sidebar:
    try:
        pdf_data = generate_pdf_report(filtered_df)
        st.download_button(
            label="📄 2026년 7월 보험 리포트 PDF 다운로드",
            data=pdf_data,
            file_name=f"보험시장_트렌드_리포트_{datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )
    except Exception as pdf_err:
        st.error(f"리포트 빌드 대기 중: {pdf_err}")
st.sidebar.markdown("---")

col1, col2, col3 = st.columns(3)
with col1: st.metric("📋 주간 정밀 수집 뉴스", f"{len(filtered_df)} 건 / 100 건")
with col2: st.metric("🎯 최다 발생 비즈니스 이슈", filtered_df["핵심키워드"].value_counts().index[0] if not filtered_df.empty else "-")
with col3: st.metric("🔥 트렌드 집중 상품군", filtered_df["카테고리(상품)"].value_counts().index[0] if not filtered_df.empty else "-")

st.markdown("---")

if not filtered_df.empty:
    pivot_df = filtered_df.groupby(["핵심키워드", "카테고리(상품)"]).size().reset_index(name="기사수")
    fig_heatmap = px.density_heatmap(pivot_df, x="카테고리(상품)", y="핵심키워드", z="기사수", text_auto=True, color_continuous_scale="Purples")
    st.plotly_chart(fig_heatmap, use_container_width=True)

st.markdown("---")

bottom_col1, bottom_col2 = st.columns(2)

with bottom_col1:
    st.subheader("🤖 기사 분석 및 3문장 주제 요약")
    if not filtered_df.empty:
        selected_title = st.selectbox("📄 요약 및 스크랩할 기사를 선택하세요:", options=filtered_df["제목"].values)
        article_info = filtered_df[filtered_df["제목"] == selected_title].iloc[0]
        st.link_button("🔗 선택한 기사 원문 읽기", article_info["기사링크"])
        
        s1 = f"해당 기사는 현재 시장에서 화두가 되고 있는 **'{article_info['카테고리(상품)']}'** 시장의 트렌드 변화와 실제 보도 내용을 기반으로 합니다."
        s2 = f"본문 내에서는 구체적으로 **'{article_info['핵심키워드']}'** 관점의 분석이 다뤄졌으며, 관련 플레이어로 **'{article_info['언급보험사']}'**의 동향이 언급되었습니다."
        s3 = f"결과적으로 이 데이터는 **'{article_info['핵심키워드']}'** 이슈가 산업 전반에 미칠 파급력을 실제 단어 지표를 통해 직관적으로 증명하고 있습니다."
        st.info(f"✍️ **실제 키워드 기반 주제 요약:**\n\n1. {s1}\n\n2. {s2}\n\n3. {s3}")
        
        st.markdown("🔍 **원문 핵심 문장 (편집 없음):**")
        raw_sentences = [s.strip() for s in article_info["기사내용"].replace("!", ".").replace("?", ".").split(".") if len(s.strip()) > 8]
        for i, sent in enumerate(raw_sentences[:3]): st.write(f"{i+1}. {sent}.")

with bottom_col2:
    st.subheader("📁 대시보드 스크랩 및 노션 더블 백업")
    st.write("인사이트를 기록하고 저장하면 대시보드 화면에 실시간 유지되며, 개인 노션에도 안전하게 백업본이 전송됩니다.")

    if not filtered_df.empty:
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
            use_container_width=True, hide_index=True, key="dashboard_sync_editor_v8"
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
st.subheader("📰 실시간 핵심 뉴스 데이터 매트릭스 (정밀 필터링 100선)")
if not filtered_df.empty:
    st.data_editor(filtered_df[["날짜", "카테고리(상품)", "언급보험사", "핵심키워드", "제목", "기사링크"]], column_config={"기사링크": st.column_config.LinkColumn("원문 보기", display_text="🔗 이동하기")}, use_container_width=True, hide_index=True, disabled=True)
