"""混合检索：保留关键词排序和相邻片段行为。"""
import time

NEIGHBOURS = 2  # 按阶段2实现要求保留；收益验收仍未通过。


def keyword_rank(book, terms):
    ranked = []
    for chunk in book['chunks']:
        text = chunk['text']
        hits = sum(term in text for term in terms)
        if hits:
            local = max(sum(term in text[i:i + 240] for term in terms)
                        for i in range(0, len(text), 120))
            ranked.append((hits * 9 + local, chunk))
    return sorted(ranked, key=lambda row: (-row[0], row[1]['id']))


def hybrid_search(book, terms, offset=0, k=None, pool=30, query=None):
    if k is None:
        k = config.top_k()
    if not isinstance(terms, list):
        raise ValueError('terms 需要是关键词数组。')
    terms = list(dict.fromkeys(t.strip() for t in terms if isinstance(t, str) and t.strip()))[:8]
    if any(len(t) > 80 for t in terms):
        raise ValueError('请使用人物名或短语，不要用整段问题作为关键词。')
    query = query if isinstance(query, str) and query.strip() and len(query) <= 500 else ' '.join(terms)
    started = time.perf_counter()
    keyword = keyword_rank(book, terms)
    vector = []
    reason = '向量索引尚未就绪，当前仅用关键词。'
    try:
        if query and book.get('_index') is not None:
            vector = book['_index'].rank(query, pool)
            reason = ''
    except Exception:
        reason = '向量检索暂不可用，当前仅用关键词。'
    kw_scores = {c['id']: score for score, c in keyword}
    vec_scores = dict(vector)
    scores = {}
    for ranking in ([c['id'] for _, c in keyword[:pool]], [n for n, _ in vector]):
        for rank, n in enumerate(ranking, 1):
            scores[n] = scores.get(n, 0) + 1 / (60 + rank)
    ranked = sorted(scores, key=lambda n: (-scores[n], n)) if vector else [c['id'] for _, c in keyword]
    if vector:
        ranked.extend(c['id'] for _, c in keyword if c['id'] not in scores)
    selected, seen = [], set()
    for n in ranked:
        chunk = book['chunks'][n - 1]
        if chunk['text'] not in seen:
            selected.append(chunk)
            seen.add(chunk['text'])
    offset = max(0, int(offset))
    direct = selected[offset:offset + k]
    fragments = {}
    for chunk in direct:
        n = chunk['id']
        for context in book['chunks'][max(0, n - NEIGHBOURS - 1):n + NEIGHBOURS]:
            fragments[context['id']] = context
    return {'total': len(selected), 'offset': offset,
            'fragments': [fragments[n] for n in sorted(fragments)],
            'retrieval_ms': round((time.perf_counter() - started) * 1000, 2),
            'channels': {'keyword': len(keyword), 'vector': len(vector)},
            'degraded': not bool(vector), 'reason': reason,
            'hits': [{'id': c['id'], 'place': c['place'], 'score': scores.get(c['id'], 0),
                      'kw_score': kw_scores.get(c['id'], 0), 'vec_score': vec_scores.get(c['id'], 0)} for c in direct]}

import hashlib
import json
import math
import config
from pathlib import Path
from urllib.request import Request, urlopen


def normalize(rows):
    result = []
    for row in rows:
        values = [float(v) for v in row]
        norm = math.sqrt(sum(v * v for v in values))
        if not values or not math.isfinite(norm) or not norm:
            raise ValueError('向量数据无效。')
        result.append([v / norm for v in values])
    if len({len(row) for row in result}) > 1:
        raise ValueError('向量维度不一致。')
    return result


class Embedder:
    @property
    def model(self):
        return config.embed_model()

    def request(self, texts):
        key = config.embed_key()
        if not key:
            raise ValueError('未配置向量服务，当前仅用关键词。')
        for attempt in range(3):
            try:
                request = Request(config.embed_base().rstrip('/') + '/embeddings',
                    data=json.dumps({'model': self.model, 'input': texts}).encode(),
                    headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
                with urlopen(request, timeout=30) as response:
                    data = sorted(json.load(response)['data'], key=lambda x: x['index'])
                if [x['index'] for x in data] != list(range(len(texts))):
                    raise ValueError()
                return normalize([x['embedding'] for x in data])
            except Exception:
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise ValueError('向量服务暂不可用，当前仅用关键词。') from None

    def embed(self, texts):
        result = []
        for start in range(0, len(texts), 32):
            batch = [text[:2000] for text in texts[start:start + 32]]
            try:
                result.extend(self.request(batch))
            except ValueError:
                for small in range(0, len(batch), 8):
                    result.extend(self.request(batch[small:small + 8]))
        return result


def digest(book):
    return hashlib.sha1(json.dumps({'chunks': [(c['id'], c['text']) for c in book['chunks']],
                                   'sources': book.get('source_texts', [])}, ensure_ascii=False).encode()).hexdigest()


class VectorIndex:
    def __init__(self, book, embedder=None, progress=None):
        self.book = book
        self.embedder = embedder or Embedder()
        self.progress = progress or (lambda n: None)

    def build(self, book):
        started = time.perf_counter()
        prefix_chars = config.prefix_chars()
        self.book = book
        rows = []
        for start in range(0, len(book['chunks']), 32):
            # 从原文坐标取片段起点之前的文字，排除相邻片段的重叠区。
            texts = [(book['source_texts'][c['source_index']][max(0, c['start'] - prefix_chars):c['start']]
                      if prefix_chars else '') + c['text']
                     for c in book['chunks'][start:start + 32]]
            rows.extend(self.embedder.embed(texts))
            self.progress(len(rows))
        self.vectors = normalize(rows)
        self.ids = [c['id'] for c in book['chunks']]
        if len(rows) != len(self.ids) or not rows:
            raise ValueError('向量数量不一致。')
        self.meta = {'model': self.embedder.model, 'dimension': len(rows[0]), 'count': len(rows), 'digest': digest(book), 'built_at': time.time(),
                     'prefix_chars': prefix_chars, 'prefix_mode': 'source_before_start_v2',
                     'build_seconds': time.perf_counter() - started}
        self.rebuilt = True
        return self

    def save(self, path):
        import numpy as np
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix('.tmp').open('wb') as stream:
            np.savez(stream, vectors=np.asarray(self.vectors, dtype=np.float32), ids=np.asarray(self.ids, dtype=np.int32))
        path.with_suffix('.tmp').replace(path)
        path.with_suffix('.json').write_text(json.dumps(self.meta), encoding='utf-8')

    def load(self, path):
        self.rebuilt = False
        try:
            import numpy as np
            meta = json.loads(Path(path).with_suffix('.json').read_text(encoding='utf-8'))
            with np.load(path, allow_pickle=False) as data:
                vectors, ids = data['vectors'], data['ids']
            if (meta['model'] != self.embedder.model or meta['digest'] != digest(self.book)
                    or meta.get('prefix_chars') != config.prefix_chars()
                    or meta.get('prefix_mode') != 'source_before_start_v2'
                    or meta['count'] != len(self.book['chunks'])
                    or vectors.shape != (meta['count'], meta['dimension'])
                    or ids.tolist() != [c['id'] for c in self.book['chunks']]
                    or not np.isfinite(vectors).all()
                    or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)):
                raise ValueError()
            self.vectors, self.ids, self.meta = vectors, ids.tolist(), meta
            return self
        except Exception:
            return self.build(self.book)

    def rank(self, text, pool):
        if self.embedder.model != self.meta['model']:
            raise ValueError('向量模型已更换，请重建索引。')
        query = normalize(self.embedder.embed([text]))[0]
        if len(query) != self.meta['dimension']:
            raise ValueError('向量维度不一致。')
        try:
            import numpy as np
            scores = np.asarray(self.vectors, dtype=np.float32) @ np.asarray(query, dtype=np.float32)
        except ImportError:
            scores = [sum(a * b for a, b in zip(row, query)) for row in self.vectors]
        return sorted(zip(self.ids, map(float, scores)), key=lambda x: (-x[1], x[0]))[:pool]
