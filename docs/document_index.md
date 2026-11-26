# 문서 대장 (document_index.md)

> 평가표 **3번**(출처 확인)과 **10번**(데이터 이용)의 증빙.
> 발제 요건: 문서 ID, 제목, 출처, 이용 조건, 버전 또는 수집 시점, 원문 위치를 기록한다.
> 문서 ID·쪽 범위·청크 수는 `docs/corpus/*.md` 머리말과 `data/chunks.jsonl` 에서 뽑았다. `[확인 필요]` 칸은 팀이 채운다.

## 원본

| 항목 | 값 |
|---|---|
| 원본 | 법무부 출입국·외국인정책본부 「체류민원 자격별 안내 매뉴얼」 (PDF, 795쪽) |
| 판 | 2026. 11. (파일명 261116, 머리말 `version: 2026-11-16`) → `configs/base.toml` `doc_version = "MAN-STAY-261116"` |
| 원본 링크 | https://www.hikorea.go.kr (하이코리아 > 공지사항/자료실 > 체류자격별 안내 매뉴얼) |
| 수집일 | 2026-11-16 (파일명 261116, 발행판 기준) |
| 이용 조건 | 공공누리 제1유형(출처표시) — 공개 공공 문서, 개인정보 없음. 비상업적 학습 목적, 출처 표시 |
| 외부 모델 전송 | 공개 문서이므로 임베딩(OpenAI)·생성(Anthropic) API 로 청크를 보낸다 `[팀 확인 필요]` |
| 원본 파일 | 저장소에 커밋하지 않음 (`data/raw/`, .gitignore). 변환 결과 `docs/corpus/*.md` 와 `data/chunks.jsonl` 은 커밋 |
| 재생성 | `docs/conversion_notes.md` 참조. `src/ingest/pdf_to_md.py`(본문 장), `src/ingest/intro_to_md.py`(DOC-INTRO) → `src/ingest/chunk.py` |

## 문서 목록 (장 단위 doc_id)

모든 문서의 출처·판·이용 조건은 위 원본과 같다. 원문 위치는 청크마다 `page` 와 `location`(절 경로)으로 기록된다.

| 문서 ID | 제목 | 원본 쪽 | 청크 수 | 변환 파일 |
|---|---|---|---|---|
| DOC-INTRO | 유의사항 및 공통사항(INTRO) | p.3–8, 12–13 | 7 | `docs/corpus/DOC-INTRO_유의사항및공통사항.md` |
| DOC-A1 | 외교(A-1) | p.14–17 | 11 | `docs/corpus/DOC-A1_외교.md` |
| DOC-A2 | 공무(A-2) | p.18–20 | 9 | `docs/corpus/DOC-A2_공무.md` |
| DOC-A3 | 협정(A-3) | p.21–23 | 10 | `docs/corpus/DOC-A3_협정.md` |
| DOC-B1 | 사증면제(B-1) | p.24–24 | 1 | `docs/corpus/DOC-B1_사증면제.md` |
| DOC-B2 | 관광통과(B-2) | p.25–25 | 1 | `docs/corpus/DOC-B2_관광통과.md` |
| DOC-C1 | 일시취재(C-1) | p.26–26 | 2 | `docs/corpus/DOC-C1_일시취재.md` |
| DOC-C3 | 단기방문(C-3) | p.27–28 | 4 | `docs/corpus/DOC-C3_단기방문.md` |
| DOC-C4 | 단기취업(C-4) | p.29–31 | 8 | `docs/corpus/DOC-C4_단기취업.md` |
| DOC-D1 | 문화예술(D-1) | p.32–34 | 17 | `docs/corpus/DOC-D1_문화예술.md` |
| DOC-D2 | 유학(D-2) | p.35–55 | 30 | `docs/corpus/DOC-D2_유학.md` |
| DOC-D3 | 기술연수(D-3) | p.56–82 | 50 | `docs/corpus/DOC-D3_기술연수.md` |
| DOC-D4 | 일반연수(D-4) | p.83–101 | 48 | `docs/corpus/DOC-D4_일반연수.md` |
| DOC-D5 | 취재(D-5) | p.102–104 | 14 | `docs/corpus/DOC-D5_취재.md` |
| DOC-D6 | 종교(D-6) | p.105–107 | 17 | `docs/corpus/DOC-D6_종교.md` |
| DOC-D7 | 주재(D-7) | p.108–114 | 22 | `docs/corpus/DOC-D7_주재.md` |
| DOC-D8 | 기업투자(D-8) | p.115–129 | 32 | `docs/corpus/DOC-D8_기업투자.md` |
| DOC-D9 | 무역경영(D-9) | p.130–142 | 33 | `docs/corpus/DOC-D9_무역경영.md` |
| DOC-D10 | 구직(D-10) | p.144–166 | 37 | `docs/corpus/DOC-D10_구직.md` |
| DOC-E1 | 교수(E-1) | p.167–185 | 72 | `docs/corpus/DOC-E1_교수.md` |
| DOC-E3 | 연구(E-3) | p.186–195 | 51 | `docs/corpus/DOC-E3_연구.md` |
| DOC-E4 | 기술지도(E-4) | p.196–200 | 25 | `docs/corpus/DOC-E4_기술지도.md` |
| DOC-E5 | 전문직업(E-5) | p.201–205 | 19 | `docs/corpus/DOC-E5_전문직업.md` |
| DOC-E6 | 예술흥행(E-6) | p.206–212 | 33 | `docs/corpus/DOC-E6_예술흥행.md` |
| DOC-E7 | 특정활동(E-7) | p.214–323 | 177 | `docs/corpus/DOC-E7_특정활동.md` |
| DOC-E8 | 계절근로(E-8) | p.324–325 | 4 | `docs/corpus/DOC-E8_계절근로.md` |
| DOC-E9 | 비전문취업(E-9) | p.326–335 | 29 | `docs/corpus/DOC-E9_비전문취업.md` |
| DOC-E10 | 선원취업(E-10) | p.336–340 | 17 | `docs/corpus/DOC-E10_선원취업.md` |
| DOC-F1 | 방문동거(F-1) | p.341–364 | 88 | `docs/corpus/DOC-F1_방문동거.md` |
| DOC-F2 | 거주(F-2) | p.365–421 | 117 | `docs/corpus/DOC-F2_거주.md` |
| DOC-F3 | 동반(F-3) | p.422–473 | 132 | `docs/corpus/DOC-F3_동반.md` |
| DOC-F6 | 결혼이민(F-6) | p.474–497 | 45 | `docs/corpus/DOC-F6_결혼이민.md` |
| DOC-G1 | 기타(G-1) | p.498–513 | 67 | `docs/corpus/DOC-G1_기타.md` |
| DOC-H1 | 관광취업(H-1) | p.515–527 | 24 | `docs/corpus/DOC-H1_관광취업.md` |
| DOC-F4F5 | 재외동포·영주 특례(F-4F-5) | p.528–662 | 264 | `docs/corpus/DOC-F4F5_재외동포영주특례.md` |
| DOC-ANNEX | 붙임 서식 및 취업제한분야(ANNEX) | p.663–704 | 32 | `docs/corpus/DOC-ANNEX_붙임서식및취업제한분야.md` |
| DOC-WIDE | 광역형 비자 시범사업(WIDE) | p.706–796 | 104 | `docs/corpus/DOC-WIDE_광역형비자시범사업.md` |

합계: 문서 37개, 청크 1653개.

## 색인에 없는 쪽

청크가 하나도 없는 쪽: 1–2, 9–11, 143, 213, 514, 705.

- p.1–2 는 표지·목차, p.9–11 은 외국인 직업 신고서 빈 서식이라 검색 노이즈로 보고 뺐다.
- p.3–8, 12–13(유의사항·공통사항)은 `DOC-INTRO` 로 추가했다 (`docs/conversion_notes.md` 수정 11). DEV-009 의 p.3 참고 근거가 `DOC-INTRO#5f777614b7` 로 연결됐다.
- 나머지 빈 쪽(p.143, 213, 514, 705)은 각각 D-9/D-10, E-6/E-7, G-1/H-1, ANNEX/WIDE 경계에 위치하는 장 구분 간지로 판단하여 색인에서 제외했다.
