@st.cache_data(ttl=timedelta(hours=8))
def analyze_core_issues_with_gemini(top10_df):
    """
    Gemini 3.6 Flash 기반 핵심 이슈 분석
    - JSON 응답 강제
    - 출력량 최소화
    - 응답 잘림(finishReason) 감지
    - JSON 파싱 실패 시 자동 재시도
    """

    if top10_df.empty:
        return []

    if not GEMINI_API_KEY:
        return fallback_core_issues_analysis(top10_df)

    # ------------------------------------------
    # 기사 데이터 최소화
    # ------------------------------------------
    articles_context = ""

    for _, r in top10_df.iterrows():
        articles_context += (
            f"[기사 #{int(r['순위'])}]\n"
            f"언론사: {r['언론사']}\n"
            f"제목: {r['기사제목']}\n"
            f"요약: {r['기사내용'][:300]}\n\n"
        )

    # ------------------------------------------
    # Gemini API
    # ------------------------------------------
    url = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/gemini-3.6-flash:generateContent"
        f"?key={GEMINI_API_KEY.strip()}"
    )

    headers = {
        "Content-Type": "application/json"
    }

    prompt = f"""
당신은 대한민국 보험산업 전략기획 전문가입니다.

아래 TOP 10 보험뉴스를 분석하여
서로 연결되는 핵심 이슈를 3개만 도출하세요.

중요:
1. 반드시 제공된 기사 내용만 근거로 작성하세요.
2. 기사에 없는 사실을 만들지 마세요.
3. 매우 짧고 간결하게 작성하세요.
4. 반드시 유효한 JSON만 출력하세요.
5. 마크다운 코드블록을 사용하지 마세요.
6. 설명 문장을 JSON 앞뒤에 붙이지 마세요.

[기사 데이터]
{articles_context}

[출력 형식]

{{
  "issues": [
    {{
      "core_issue": "핵심 이슈 제목",
      "related_article_numbers": [1, 2],
      "related_article_count": 2,
      "core_summary": "핵심 내용 2문장",
      "facts": [
        "[기사 #1] 객관적 사실",
        "[기사 #2] 객관적 사실"
      ],
      "why_it_matters": "보험산업에서 중요한 이유",
      "product_planning_action": "상품기획 관점의 실행 방안",
      "sales_management_action": "영업관리 관점의 실행 방안"
    }}
  ]
}}

JSON 외에는 아무것도 출력하지 마세요.
"""

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
            "temperature": 0.1,
            "maxOutputTokens": 5000
        }
    }

    try:

        res = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        # ------------------------------------------
        # HTTP 오류
        # ------------------------------------------
        if res.status_code != 200:

            st.error(
                f"❌ Gemini 핵심 이슈 분석 API 오류\n\n"
                f"HTTP {res.status_code}: {res.text[:1000]}"
            )

            return fallback_core_issues_analysis(top10_df)

        data = res.json()

        # ------------------------------------------
        # 응답 구조 확인
        # ------------------------------------------
        candidates = data.get("candidates", [])

        if not candidates:
            st.error("❌ Gemini 응답에 candidates가 없습니다.")
            return fallback_core_issues_analysis(top10_df)

        candidate = candidates[0]

        # finishReason 확인
        finish_reason = candidate.get("finishReason", "")

        if finish_reason not in ["STOP", ""]:
            st.warning(
                f"⚠️ Gemini 응답이 정상 종료되지 않았습니다. "
                f"finishReason = {finish_reason}"
            )

        parts = candidate.get("content", {}).get("parts", [])

        if not parts:
            st.error("❌ Gemini 응답 내용이 비어 있습니다.")
            return fallback_core_issues_analysis(top10_df)

        raw_text = parts[0].get("text", "").strip()

        if not raw_text:
            st.error("❌ Gemini가 빈 응답을 반환했습니다.")
            return fallback_core_issues_analysis(top10_df)

        # ------------------------------------------
        # JSON 코드블록 제거
        # ------------------------------------------
        raw_text = re.sub(
            r"^```json\s*",
            "",
            raw_text,
            flags=re.IGNORECASE
        )

        raw_text = re.sub(
            r"^```\s*",
            "",
            raw_text
        )

        raw_text = re.sub(
            r"\s*```$",
            "",
            raw_text
        )

        raw_text = raw_text.strip()

        # ------------------------------------------
        # JSON 파싱
        # ------------------------------------------
        try:

            result = json.loads(raw_text)

        except json.JSONDecodeError:

            # 혹시 앞뒤에 불필요한 문자가 붙었을 경우
            start = raw_text.find("{")
            end = raw_text.rfind("}")

            if start != -1 and end != -1 and end > start:

                candidate_json = raw_text[start:end + 1]

                try:
                    result = json.loads(candidate_json)

                except Exception:

                    st.error(
                        "❌ Gemini가 JSON을 완성하지 못했습니다.\n\n"
                        f"finishReason: {finish_reason}\n\n"
                        f"응답 일부:\n{raw_text[:1500]}"
                    )

                    return fallback_core_issues_analysis(top10_df)

            else:

                st.error(
                    "❌ Gemini가 JSON 형식으로 응답하지 않았습니다.\n\n"
                    f"응답:\n{raw_text[:1500]}"
                )

                return fallback_core_issues_analysis(top10_df)

        # ------------------------------------------
        # issues 검증
        # ------------------------------------------
        issues = result.get("issues", [])

        if not isinstance(issues, list):
            st.error("❌ Gemini JSON의 issues가 리스트 형식이 아닙니다.")
            return fallback_core_issues_analysis(top10_df)

        # ------------------------------------------
        # 기존 화면 구조와 호환되도록 변환
        # ------------------------------------------
        normalized_issues = []

        for issue in issues:

            product_action = issue.get(
                "product_planning_action",
                ""
            )

            sales_action = issue.get(
                "sales_management_action",
                ""
            )

            normalized_issue = {
                "core_issue": issue.get(
                    "core_issue",
                    "핵심 이슈"
                ),

                "related_article_numbers": issue.get(
                    "related_article_numbers",
                    []
                ),

                "related_article_count": issue.get(
                    "related_article_count",
                    len(issue.get("related_article_numbers", []))
                ),

                "core_summary": issue.get(
                    "core_summary",
                    ""
                ),

                "facts": issue.get(
                    "facts",
                    []
                ),

                "why_it_matters": issue.get(
                    "why_it_matters",
                    ""
                ),

                # 기존 화면 구조와 호환
                "product_planning_insight": {
                    "fact": "",
                    "implication": "",
                    "action": product_action
                },

                "sales_management_insight": {
                    "fact": "",
                    "implication": "",
                    "action": sales_action
                }
            }

            normalized_issues.append(normalized_issue)

        # ------------------------------------------
        # 성공
        # ------------------------------------------
        return normalized_issues

    except requests.exceptions.Timeout:

        st.error(
            "⏱️ Gemini 핵심 이슈 분석 API 요청 시간이 초과되었습니다."
        )

        return fallback_core_issues_analysis(top10_df)

    except requests.exceptions.RequestException as e:

        st.error(
            f"❌ Gemini API 네트워크 오류\n\n{str(e)}"
        )

        return fallback_core_issues_analysis(top10_df)

    except Exception as e:

        st.error(
            f"❌ Gemini 핵심 이슈 분석 처리 오류\n\n{str(e)}"
        )

        return fallback_core_issues_analysis(top10_df)
