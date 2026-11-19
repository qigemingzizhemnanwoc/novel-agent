"""Deterministic retrieval checks; no model calls or private novels."""
import json
import time
import unittest
from pathlib import Path
from app import build_book, search_novel


def fixture():
    names = ['顾舟','林月','周宁','许川','陈雨','陆遥','苏青','秦朗','叶星','白露']
    sections = []
    cases = []
    for i, name in enumerate(names):
        # Many exact-name hits, but event and name are far apart.
        for j in range(9):
            sections.append({'place': f'干扰{i}-{j}', 'text': (name + '赶路。') * 12 + '风声。' * 170 + '盟约' + '雨声。' * 180})
        evidence = f'{name}并非亲姐姐；盟约签订于春宴结束三日后。'
        cases.append(([name, '盟约'], evidence))
        sections.append({'place': f'证据{i}', 'text': evidence})
    used = sum(len(s['text']) for s in sections)
    sections.insert(50, {'place':'长篇背景', 'text': ('山川河流，旅途往返。' * 500000)[:5000000-used]})
    return build_book('合成测试', sections), cases


class RetrievalChecks(unittest.TestCase):
    def test_evidence_and_speed(self):
        book, cases = fixture()
        self.assertEqual(book['count'], 5000000)
        samples = []
        for terms, evidence in cases:
            result = search_novel(book, terms)
            self.assertTrue(any(evidence in c['text'] for c in result['fragments']))
            self.assertEqual(len({c['id'] for c in result['fragments']}), len(result['fragments']))
            for c in result['fragments']:
                self.assertEqual(c, book['chunks'][c['id']-1])
        self.assertEqual(search_novel(book, ['不存在的皇位'])['fragments'], [])
        def baseline(book, terms):
            ranked=[]
            for chunk in book['chunks']:
                counts=[chunk['text'].count(t) for t in terms]
                score=sum(n>0 for n in counts)*100+sum(min(n,10) for n in counts)
                if score: ranked.append((score,chunk))
            ranked.sort(key=lambda row:(-row[0],row[1]['id']))
            return {'fragments':[c for _,c in ranked[:6]]}
        report = {'characters':book['count'], 'queries':100, 'evidence_cases':10}
        for label, search in [('before',baseline),('after',search_novel)]:
            durations=[]; hits=0
            for i in range(100):
                terms,evidence=cases[i%10]; start=time.perf_counter()
                result=search(book,terms); durations.append((time.perf_counter()-start)*1000)
                hits += any(evidence in c['text'] for c in result['fragments'])
            durations.sort()
            report[label]={'hits':hits,'p50_ms':round(durations[49],2),'p95_ms':round(durations[94],2),'max_ms':round(max(durations),2)}
        Path('.tools').mkdir(exist_ok=True)
        Path('.tools/retrieval-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
        self.assertLessEqual(report['after']['p95_ms'],300)

    def test_boundary_context(self):
        text='甲'*1395+'并非亲姐姐。沈月只将她当作姐姐。'+'乙'*1500
        book=build_book('边界',[{'text':text}])
        result=search_novel(book,['沈月'])
        joined=''.join(c['text'] for c in result['fragments'])
        self.assertIn('并非亲姐姐',joined)
        self.assertIn('沈月只将她当作姐姐',joined)


if __name__=='__main__':
    unittest.main()
