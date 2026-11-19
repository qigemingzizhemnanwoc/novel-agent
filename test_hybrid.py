"""层 A 是对 fixture 校准的测试替身，不能证明真实模型语义效果。"""
import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from app import build_book
import config
from retriever import Embedder, VectorIndex, hybrid_search, keyword_rank, normalize

GROUPS = [('姐姐', '血亲'), ('怨恨', '咬牙'), ('离乡', '远行'), ('婚约', '订亲'),
          ('救援', '搭救'), ('辞官', '归隐'), ('失忆', '忘却'), ('重逢', '再会')]


class FakeEmbedder:
    model = 'fixture-calibrated-bigram'

    def embed(self, texts):
        rows = []
        for text in texts:
            row = [0.] * 256
            for i in range(max(1, len(text) - 1)):
                row[32 + int.from_bytes(hashlib.sha1(text[i:i+2].encode()).digest()[:2], 'big') % 224] += 1
            for i, group in enumerate(GROUPS):
                if any(term in text for term in group):
                    row[i] += 100
            rows.append(row)
        return normalize(rows)


def fixture():
    texts = [f'角色{i}记述：{group[0]}。' for i, group in enumerate(GROUPS)]
    texts += [f'档案{i}：约定于秋日交付信物。' for i in range(8, 20)]
    book = build_book('公开合成夹具', [{'text': t, 'place': f'章{i}'} for i, t in enumerate(texts)])
    cases = [([group[1]], i+1, True) for i, group in enumerate(GROUPS)]
    cases += [([f'档案{i}'], i+1, False) for i in range(8, 20)]
    return book, cases


def measure(book, cases):
    result = {key: [] for key in ('before', 'keyword', 'hybrid')}
    failures = []
    for terms, expected, semantic in cases:
        ids = [c['id'] for _, c in keyword_rank(book, terms)][:5]
        hybrid = [h['id'] for h in hybrid_search(book, terms, k=5)['hits']]
        for key, ranked in [('before', ids), ('keyword', ids), ('hybrid', hybrid)]:
            result[key].append(1 / (ranked.index(expected) + 1) if expected in ranked else 0)
        if expected not in hybrid:
            failures.append({'terms': terms, 'expected': expected, 'actual': hybrid})
    return {key: {'recall@5': sum(v > 0 for v in values)/len(values), 'MRR': sum(values)/len(values)} for key, values in result.items()}, failures


def report(layer, value):
    path = Path('.tools/hybrid-report.json')
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    data[layer] = value
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(layer, json.dumps(value, ensure_ascii=False))


class HybridChecks(unittest.TestCase):
    def test_pipeline(self):
        book, cases = fixture()
        book['_index'] = VectorIndex(book, FakeEmbedder()).build(book)
        for terms, n, semantic in cases:
            if semantic:
                self.assertTrue(all(t not in book['chunks'][n-1]['text'] for t in terms))
                self.assertEqual(keyword_rank(book, terms), [])
        metrics, failures = measure(book, cases)
        self.assertGreater(metrics['hybrid']['recall@5'], metrics['keyword']['recall@5'])
        self.assertGreaterEqual(sum(n in [h['id'] for h in hybrid_search(book, terms, k=5)['hits']] for terms,n,_ in cases[:8]), 6)
        report('A', {'scope': '仅用于离线管线验证，不代表模型效果', 'metrics': metrics, 'failures': failures})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'index.npz'
            book['_index'].save(path)
            loaded = VectorIndex(book, FakeEmbedder()).load(path)
            self.assertEqual(book['_index'].rank('血亲', 5), loaded.rank('血亲', 5))
            changed = build_book('变更', [{'text': '归隐新内容'}])
            rebuilt = VectorIndex(changed, FakeEmbedder()).load(path)
            self.assertEqual(rebuilt.ids, [1])

    def test_unanswerable_vector(self):
        book, _ = fixture()
        book['_index'] = VectorIndex(book, FakeEmbedder()).build(book)
        result = hybrid_search(book, ['宇航员登陆火星'], k=5)
        self.assertTrue(result['hits'])
        self.assertEqual(keyword_rank(book, ['宇航员登陆火星']), [])
        report('failure_case', {'query': '宇航员登陆火星', 'reason': '夹具无证据，向量仍返回近邻；相似不等于事实', 'ids': [h['id'] for h in result['hits']]})

    def test_degraded(self):
        from test_retrieval import fixture as original
        book, cases = original()
        for broken in (None, unittest.mock.Mock()):
            if broken is not None:
                broken.rank.side_effect = ValueError('故障')
            book['_index'] = broken
            for terms, evidence in cases:
                result = hybrid_search(book, terms)
                self.assertTrue(result['degraded'])
                self.assertTrue(any(evidence in c['text'] for c in result['fragments']))

    def test_numpy_cost(self):
        import numpy as np
        from test_retrieval import fixture as original
        book, _ = original()
        rng = np.random.default_rng(42)
        vectors = rng.random((len(book['chunks']), 256), dtype=np.float32)
        query = rng.random(256, dtype=np.float32)
        samples = []
        for _ in range(100):
            start = time.perf_counter()
            scores = vectors @ query
            np.argsort(-scores, kind='stable')[:30]
            samples.append((time.perf_counter()-start)*1000)
        p95 = float(np.percentile(samples, 95))
        report('performance', {'characters': book['count'], 'numpy_p95_ms': p95})
        self.assertLess(p95, 60)

    @unittest.skipUnless(config.embed_key(), '未配置 embedding key，跳过真实模型测试')
    def test_real(self):
        book, cases = fixture()
        try:
            book['_index'] = VectorIndex(book, Embedder()).build(book)
            metrics, failures = measure(book, cases)
            report('B', {'model': book['_index'].embedder.model, 'characters': book['count'], 'date': time.strftime('%Y-%m-%d'), 'metrics': metrics, 'failures': failures})
        except Exception:
            report('B', {'status': '真实服务调用失败，未测'})
            raise

if not config.embed_key():
    report('B', {'status': 'skip', 'reason': '未配置 embedding key，真实模型未测'})
