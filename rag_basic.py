#!/usr/bin/env python3
"""대조군 — BM25 로 문서를 뽑아 원문 그대로 답하는 basic RAG.

GraphRAG 와 **같은 코퍼스 · 같은 모델 · 같은 채점**을 쓴다.
다른 것은 하나뿐이다: 그래프를 타지 않고 문서 조각을 top-k 로 뽑아 던진다.
그래야 차이가 '그래프 때문' 이라고 말할 수 있다.

  python rag_basic.py "질문"
"""
import json
import os
import re
import sys

from dotenv import load_dotenv
from rank_bm25 import BM25Okapi

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))


def tokenize(s):
    """한국어 형태소 분석기 없이 — 공백 + 2-gram. BM25 대조군에는 이 정도면 된다."""
    words = re.findall(r"[가-힣A-Za-z0-9]+", s)
    grams = []
    for w in words:
        grams.append(w)
        if len(w) > 2:
            grams += [w[i:i + 2] for i in range(len(w) - 1)]
    return grams


class BasicRAG:
    def __init__(self, cfg=None, chunk_chars=900, top_k=6):
        self.cfg = cfg or json.load(
            open(os.path.join(HERE, "config.json"), encoding="utf-8"))
        self.top_k = top_k
        self._client = None
        self.token_in = self.token_out = 0

        ddir = os.path.join(HERE, self.cfg["corpus"]["dir"])
        self.chunks = []
        for f in sorted(os.listdir(ddir)):
            if not f.endswith(".md"):
                continue
            text = open(os.path.join(ddir, f), encoding="utf-8").read()
            title = f[:-3].replace("_", " ")
            for i in range(0, len(text), chunk_chars):
                piece = text[i:i + chunk_chars].strip()
                if piece:
                    self.chunks.append({"doc": title, "text": piece})
        self.bm25 = BM25Okapi([tokenize(c["text"]) for c in self.chunks])

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI()
        return self._client

    def retrieve(self, question):
        scores = self.bm25.get_scores(tokenize(question))
        idx = sorted(range(len(scores)), key=lambda i: -scores[i])[: self.top_k]
        return [self.chunks[i] for i in idx]

    def ask(self, question, log=False):
        hits = self.retrieve(question)
        ctx = "\n\n".join(f"[{i+1}] ({h['doc']})\n{h['text']}" for i, h in enumerate(hits))
        system = (
            "너는 주어진 문서 조각만 보고 질문에 답하는 도구다.\n"
            "- 조각에 있는 것만 쓴다. 상식·추측을 보태지 않는다.\n"
            "- 조각으로 답할 수 없으면 sufficient 를 false 로 두고 answer 는 비운다.\n"
            "- 질문이 어떤 사실을 전제해도, 조각에 없으면 전제를 따르지 않는다.\n"
            "- answer 는 한국어 두세 문장.\n"
            '출력은 JSON 하나로만 한다: {"answer": "...", "sufficient": true/false, '
            '"used": [조각 번호]}'
        )
        try:
            r = self.client.chat.completions.create(
                model=self.cfg["llm"]["answer_model"],
                temperature=self.cfg["llm"]["temperature"],
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": f"질문: {question}\n\n문서 조각:\n{ctx}"}],
            )
            self.token_in += r.usage.prompt_tokens
            self.token_out += r.usage.completion_tokens
            out = json.loads(r.choices[0].message.content)
        except Exception as e:
            return {"question": question, "answer": "", "refused": True,
                    "sources": [], "error": str(e)}

        sufficient = bool(out.get("sufficient"))
        answer = out.get("answer", "")
        if not sufficient:
            answer = "문서 조각에서 답할 근거를 찾지 못했습니다."
        return {
            "question": question,
            "answer": answer,
            "refused": not sufficient,
            "sources": sorted({h["doc"] for h in hits}),
            "retrieved": [h["doc"] for h in hits],
        }


if __name__ == "__main__":
    rag = BasicRAG()
    q = " ".join(sys.argv[1:]) or input("질문> ")
    r = rag.ask(q)
    print(f"\n{r['answer']}\n")
    print(f"  뽑은 문서: {', '.join(r['retrieved'])}")
