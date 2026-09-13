from __future__ import annotations

"""Local retrieval over an EDA knowledge corpus.

The user pointed at OpenROAD-Assistant/EDA-Corpus as the reference question set.
We do not bundle it and we do not require it: if the corpus is present on disk we
index it, otherwise retrieval degrades to "no corpus" instead of hallucinating.

Supported shapes: ``.jsonl`` / ``.json`` (list or ``{"data": [...]}``) / ``.md`` /
``.txt``.  Retrieval is a dependency-free BM25-lite over the concatenated
question+answer text; it is deliberately simple and inspectable.
"""

import json
import math
import os
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
QUESTION_KEYS = ("question", "query", "prompt", "instruction", "title", "input")
ANSWER_KEYS = ("answer", "response", "output", "completion", "content", "text", "script")
MAX_RECORDS = 20000

STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "of", "in", "on", "for", "and", "or",
    "with", "how", "what", "why", "can", "i", "you", "it", "this", "that", "do",
}


def tokenize(text: str) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "") if token.lower() not in STOPWORDS]


class Corpus:
    def __init__(self, root: Optional[str] = None) -> None:
        self.root = root
        self.records: List[Dict[str, str]] = []
        self._tokens: List[Counter] = []
        self._df: Counter = Counter()
        self.loaded_at: Optional[float] = None
        self.sources: List[str] = []
        self.error: Optional[str] = None

    # ------------------------------------------------------------------ load
    def available(self) -> bool:
        return bool(self.records)

    def load(self) -> int:
        if not self.root or not os.path.isdir(self.root):
            self.error = "corpus path not found: %s" % self.root
            return 0
        records: List[Dict[str, str]] = []
        sources: List[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != ".git"]
            for filename in sorted(filenames):
                path = os.path.join(dirpath, filename)
                ext = os.path.splitext(filename)[1].lower()
                try:
                    if ext == ".jsonl":
                        records.extend(self._from_jsonl(path))
                    elif ext == ".json":
                        records.extend(self._from_json(path))
                    elif ext in (".md", ".txt"):
                        records.extend(self._from_text(path))
                    else:
                        continue
                    sources.append(path)
                except Exception as exc:
                    self.error = "%s: %s" % (path, exc)
                if len(records) >= MAX_RECORDS:
                    break
            if len(records) >= MAX_RECORDS:
                break
        self.records = records[:MAX_RECORDS]
        self.sources = sources
        self._index()
        self.loaded_at = __import__("time").time()
        return len(self.records)

    def _record(self, question: str, answer: str, source: str, **extra: Any) -> Dict[str, str]:
        data = {"question": question.strip(), "answer": answer.strip(), "source": source}
        for key, value in extra.items():
            if isinstance(value, str):
                data[key] = value[:400]
        return data

    def _from_jsonl(self, path: str) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(self._normalise(json.loads(line), path))
                except Exception:
                    continue
        return out

    def _from_json(self, path: str) -> List[Dict[str, str]]:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            data = json.load(handle)
        items: Iterable[Any]
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("data", "items", "records", "qa", "questions"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
            else:
                items = [data]
        else:
            return []
        out = []
        for item in items:
            try:
                out.append(self._normalise(item, path))
            except Exception:
                continue
        return out

    def _from_text(self, path: str) -> List[Dict[str, str]]:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
        out = []
        for index, chunk in enumerate(chunks):
            if len(chunk) < 40:
                continue
            head, _, rest = chunk.partition("\n")
            out.append(self._record(head or ("%s #%d" % (os.path.basename(path), index)), rest or chunk, path))
        return out

    def _normalise(self, item: Any, path: str) -> Dict[str, str]:
        if isinstance(item, str):
            return self._record(item[:200], item, path)
        if not isinstance(item, dict):
            raise ValueError("unsupported record")
        question = ""
        answer = ""
        for key in QUESTION_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                question = value
                break
        for key in ANSWER_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                answer = value
                break
        if not question and not answer:
            raise ValueError("no usable fields")
        return self._record(question or "(untitled)", answer or question, path,
                            category=str(item.get("category") or item.get("type") or ""))

    def _index(self) -> None:
        self._tokens = []
        self._df = Counter()
        for record in self.records:
            tokens = Counter(tokenize(record.get("question", "") + " " + record.get("answer", "")))
            self._tokens.append(tokens)
            for token in tokens:
                self._df[token] += 1

    # -------------------------------------------------------------- retrieve
    def retrieve(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.records:
            return []
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        total = len(self.records)
        avg_len = sum(sum(counter.values()) for counter in self._tokens) / max(1, total)
        scored: List[Any] = []
        k1, b = 1.5, 0.75
        for index, counter in enumerate(self._tokens):
            length = sum(counter.values()) or 1
            score = 0.0
            for token in query_tokens:
                freq = counter.get(token, 0)
                if not freq:
                    continue
                df = self._df.get(token, 0) or 1
                idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
                score += idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * length / max(1.0, avg_len)))
            if score > 0:
                scored.append((score, index))
        scored.sort(reverse=True)
        results = []
        for score, index in scored[:limit]:
            record = dict(self.records[index])
            record["score"] = round(score, 3)
            results.append(record)
        return results

    def stats(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "records": len(self.records),
            "sources": len(self.sources),
            "loaded_at": self.loaded_at,
            "error": self.error,
        }
