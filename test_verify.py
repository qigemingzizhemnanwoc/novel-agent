import unittest
import verify

CASES = [
 ('三十分[片段 1]', '二十分', (), 'number'),
 ('“从未说过”[片段 1]', '他说你好', (), 'quote'),
 ('张三来了[片段 1]', '李四来了', ('张三',), 'name'),
 ('他十分开心[片段 1]', '他很高兴', (), None),
 ('他离开了[片段 1]', '他走了', (), None),
 ('十几天[片段 1]', '多日', (), None),
 ('两三步[片段 1]', '几步', (), None),
 ('“你好，朋友！”[片段 1]', '你好朋友', (), None),
 ('30分[片段 1]', '三十分', (), None),
 ('张三来了[片段 1]', '李四来了', (), None),
 ('「你好」[片段 1]', '你好', (), None),
 ('二十天[片段 1]', '20天', (), None),
]
class VerifyTests(unittest.TestCase):
    def test_cases(self):
        for answer, source, names, kind in CASES:
            with self.subTest(answer=answer):
                checks = verify.check(answer, [{'id':1,'text':source}], names=names)
                self.assertEqual([c['kind'] for c in checks], [kind] if kind else [])
    def test_neighbor(self):
        self.assertEqual(verify.check('“你好”[片段 2]', [{'id':2,'text':'别的'}], chunks=[{'id':1,'text':'你好'}]), [])


class RealRegressionTests(unittest.TestCase):
    def test_negative_quote(self):
        self.assertEqual(verify.check('没有明确写“第一次月考”[片段 1]', [{'id':1,'text':'月考'}]), [])
        self.assertEqual(verify.check('明确写“第一次月考”[片段 1]', [{'id':1,'text':'月考'}])[0]['kind'], 'quote')

    def test_explicit_ellipsis(self):
        evidence = [{'id':1,'text':'“嗯，中戏。”他说，“大一。”'}]
        self.assertEqual(verify.check('“嗯，中戏……大一。”[片段 1]', evidence), [])
        self.assertEqual(verify.check('“嗯，中戏……大二。”[片段 1]', evidence)[0]['kind'], 'quote')
        self.assertEqual(verify.check('“大一……中戏”[片段 1]', evidence)[0]['kind'], 'quote')


class SpeculationTests(unittest.TestCase):
    def test_cited(self):
        result = verify.check('【推测】张三说“虚构”，相差99岁[片段 1]', [{'id':1,'text':'年龄未知'}], names=['张三'])
        self.assertEqual([c['kind'] for c in result], ['speculation'])

    def test_uncited(self):
        result = verify.check('【推测】相差99岁', [{'id':1,'text':'年龄未知'}])
        self.assertTrue(result)
        self.assertNotIn('speculation', [c['kind'] for c in result])

    def test_ordinary(self):
        self.assertEqual(verify.check('相差99岁[片段 1]', [{'id':1,'text':'年龄未知'}])[0]['kind'], 'number')

    def test_invalid_reference(self):
        import app
        with self.assertRaises(ValueError):
            app.ask({'chunks':[]}, 'key', '问题', [], 'model', system_prompt='测试', caller=lambda *a: {'content':'【推测】99岁[片段 999]'})


class DirectFactTests(unittest.TestCase):
    def test_direct_family_count(self):
        result = verify.check('【推测】测试角色有三个姐姐[片段 1]', [{'id':1,'text':'我有三个姐姐，还有一个妹妹。'}])
        self.assertEqual(result[0]['kind'], 'speculation_misuse')

    def test_same_number_different_relation(self):
        result = verify.check('【推测】测试角色有三个姐姐[片段 1]', [{'id':1,'text':'我有三个妹妹。'}])
        self.assertEqual(result[0]['kind'], 'speculation')

    def test_verbatim_fact(self):
        result = verify.check('【推测】他住在南京[片段 1]', [{'id':1,'text':'他住在南京。'}])
        self.assertEqual(result[0]['kind'], 'speculation_misuse')
