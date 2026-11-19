"""Offline checks; model replies below are fixtures, not real API validation."""
import unittest
from app import LIMIT, ask, build_book, search_novel


class ReaderChecks(unittest.TestCase):
    def test_five_million_and_end_of_book(self):
        ending = '终章：沈月是沈舟的姐姐。'
        text = '甲' * (LIMIT - len(ending)) + ending
        book = build_book('容量测试', [{'text': text}])
        self.assertEqual(book['count'], LIMIT)
        matches = search_novel(book, ['沈月'])['fragments']
        self.assertTrue(any(ending in c['text'] for c in matches))
        with self.assertRaises(ValueError):
            build_book('超限测试', [{'text': text + '乙'}])

    def test_tools_and_evidence(self):
        book = build_book('测试', [{'text': '第一章\n沈月是沈舟的姐姐。'}])
        def model(key, name, messages, choice):
            if not any(m['role'] == 'tool' for m in messages):
                self.assertEqual(choice, 'required')
                return {'content': None, 'tool_calls': [{'id': 't1', 'type': 'function',
                        'function': {'name': 'search_novel', 'arguments': '{"terms":["沈月"]}'}}]}
            self.assertIn('沈月是沈舟的姐姐', messages[-1]['content'])
            return {'content': '沈月是沈舟的姐姐。[片段 1]'}
        result = ask(book, 'fixture-key', '他们什么关系？', [], 'deepseek-flash', model)
        self.assertEqual(result['evidence'][0]['id'], 1)
        self.assertEqual(len(result['trace']), 1)

    def test_invalid_citation_rejected(self):
        book = build_book('测试', [{'text': '沈月是姐姐。'}])
        with self.assertRaises(ValueError):
            ask(book, 'fixture-key', '什么关系？', [], 'deepseek-flash',
                lambda *args: {'content': '姐姐。[片段 999]'})

    def test_no_evidence_and_missing_key(self):
        book = build_book('测试', [{'text': '沈月是姐姐。'}])
        self.assertEqual(search_novel(book, ['皇帝'])['total'], 0)
        with self.assertRaises(ValueError):
            ask(book, '', '什么关系？', [], 'deepseek-flash')


if __name__ == '__main__':
    unittest.main()
