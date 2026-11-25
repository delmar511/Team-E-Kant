"""색인 없이 돌려 보는 더미 검색기 (무료 리허설·테스트용). 실제 검색과 같은 형식(RetrievedCandidate)을 돌려준다.

단어가 겹치는 비율을 점수로 쓰고, 실제 검색처럼 질문과 무관해도 항상 top_k 개(여기서는 최대 3개)를 돌려준다.
"""
import re

from schemas import CandidateSource, Chunk, Location, RetrievedCandidate

_CHUNKS = [
    ("DOC-D2#00000000a1", "DOC-D2", 44, ["유학(D-2)", "체류기간 연장허가", "다. 제출서류"],
     "유학 체류기간 연장 제출서류: 신청서, 여권, 외국인등록증, 수수료, 재학증명서."),
    ("DOC-D4#00000000b1", "DOC-D4", 120, ["일반연수(D-4)", "시간제취업", "가. 요건"],
     "어학연수 시간제취업 요건: 입국 후 6개월 경과, 출석률 90% 이상."),
    ("DOC-D2#00000000a2", "DOC-D2", 38, ["유학(D-2)", "시간제취업 활동 허가", "나. 대상"],
     "유학 시간제취업 대상: 학위과정 재학생, 주당 허용 시간 이내."),
]


def _tok(s):
    return set(re.findall(r"\w+", s))


class StubRetriever:
    def __init__(self, top_k=5):
        self.top_k = top_k

    def __call__(self, query):
        q = _tok(query)
        scored = sorted(((len(q & _tok(text)) / max(len(q), 1), i) for i, (*_, text) in enumerate(_CHUNKS)),
                        key=lambda x: (-x[0], x[1]))
        out = []
        for rank, (score, i) in enumerate(scored[: self.top_k], 1):
            cid, doc, page, path, text = _CHUNKS[i]
            chunk = Chunk(chunk_id=cid, doc_id=doc, text=text,
                          location=Location(page_start=page, page_end=page, section_path=path))
            out.append(RetrievedCandidate(chunk=chunk, score=score, rank=rank, source=CandidateSource.VECTOR,
                                          component_scores={"stub": score}))
        return out
