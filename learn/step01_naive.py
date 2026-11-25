# -*- coding: utf-8 -*-
"""1단계 — 가장 단순한 검색

질문에 들어있는 단어가 청크 본문에 있으면 1점. 그걸로 순위를 매긴다.
검색이라고 부를 수 있는 가장 단순한 방법이다.

실행: python learn/step01_naive.py
"""
import json

CHUNKS = [json.loads(l) for l in open('learn/mini_chunks.jsonl', encoding='utf-8')]

QUESTIONS = [
    ('Q1', '유학생이 알바하려면 뭘 내야 해?', 3),
    ('Q2', 'D-2 체류자격 변경 제출서류', 5),
    ('Q3', '시간제취업 대상', 1),
]


def naive_score(query, chunk):
    """질문을 띄어쓰기로 자르고, 각 조각이 본문에 들어있으면 1점씩."""
    words = query.split()
    return sum(1 for w in words if w in chunk['text'])


for qid, q, answer in QUESTIONS:
    print(f'\n{qid}  "{q}"   정답은 {answer}번')
    print('  질문을 자른 결과:', q.split())
    scored = [(naive_score(q, c), i) for i, c in enumerate(CHUNKS, 1)]
    scored.sort(reverse=True)
    for score, i in scored[:3]:
        mark = '  <-- 정답' if i == answer else ''
        loc = CHUNKS[i - 1]['location'].split(' > ', 1)[-1][:40]
        print(f'    {score}점  {i}번  {loc}{mark}')
