import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import workspace as w
from app import build_book

class WorkspaceChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=w.DATA;w.DATA=Path(self.temp.name)
        self.data=w.create('同名作品',[{'text':'序章😀。甲与乙交手。后文秘密：乙胜利。'}]);self.pid=self.data['id']
    def tearDown(self):
        w.DATA=self.old;self.temp.cleanup()
    def call(self,path,body=None,ask=None):
        return w.dispatch(path,{'project':self.pid,**(body or {})},build_book,ask)
    def test_save_reopen_and_isolation(self):
        other=w.create('同名作品',[{'text':'不同正文'}])
        self.assertNotEqual(other['id'],self.pid)
        self.assertEqual(self.call('/project/open')['sections'],self.data['sections'])
        self.assertEqual(len(w.listing()),2)
        with self.assertRaises(ValueError):w.contents('../outside')
    def test_delete_project_isolated(self):
        other=w.create('其他作品',[{'text':'保留'}])
        w.save(w.DATA / 'prompts.json', {'draft':'保留提示词'})
        self.call('/project/delete')
        self.assertEqual([x['id'] for x in w.listing()], [other['id']])
        self.assertEqual(w.contents(other['id'])['sections'][0]['text'], '保留')
        self.assertTrue(list((w.DATA / '.trash').glob('*/source.json')))
        self.assertEqual(w.read(w.DATA / 'prompts.json')['draft'], '保留提示词')
        with self.assertRaises(ValueError): self.call('/project/delete', {'project':'../outside'})
    def test_extract_approve_delete(self):
        def fake(*args,**kwargs):
            return {'answer':json.dumps({'fields':[{'label':'身份','value':'高手','source':1,'quote':'甲与乙交手。'},{'label':'出生地','value':'京城','source':1,'quote':'捏造'}]}), 'evidence':[{'id':1,'text':'甲与乙交手。','place':'正文'}]}
        result=self.call('/character/extract',{'name':'甲','key':'test'},fake)
        card=result['characters'][0];self.assertEqual(len(card['fields']),1)
        args={'card':card['id'],'field':card['fields'][0]['id'],'accept':True}
        self.assertTrue(self.call('/character/review',args)['characters'][0]['fields'][0]['accepted'])
        args['accept']=False
        self.assertEqual(self.call('/character/review',args)['characters'][0]['fields'],[])
        self.call('/preferences',{'skip_delete_warning':True})
        self.assertTrue(w.preferences()['skip_delete_warning'])
    def test_blind_scope_materials_and_rewrites(self):
        full=self.data['sections'][0]['text'];prefix=full.split('后文秘密')[0];pos=len(prefix.encode('utf-16-le'))//2
        card=w.record(self.pid,'characters',{'name':'甲','scope_end':999,'fields':[{'accepted':True,'label':'身份','value':'自动人设泄漏'}]})
        setting=w.record(self.pid,'settings',{'name':'作者设定','text':'明确允许的外部设定'})
        requests=[]
        def fake(book,key,prompt,history,model,**kwargs):
            self.assertEqual(history,[])
            self.assertNotIn('后文秘密',json.dumps(book,ensure_ascii=False)+prompt)
            self.assertNotIn('自动人设泄漏',prompt)
            self.assertIn('明确允许的外部设定',prompt)
            requests.append(prompt)
            return {'answer':'测试候选稿'}
        body={'mode':'draft','position':pos,'future':False,'materials':[card['id'],setting['id']],'key':'test'}
        self.call('/writing/generate',body,fake)
        result=self.call('/writing/generate',{**body,'adjustment':'更加克制'},fake)
        self.assertEqual(len(result['drafts']),2)
        self.assertIn('更加克制',requests[-1])
        self.call('/record/delete',{'kind':'drafts','id':result['drafts'][0]['id']})
        self.assertEqual(len(w.contents(self.pid)['drafts']),1)
    def test_future_opt_in_and_three_ideas(self):
        def fake(book,*args,**kwargs):
            self.assertIn('后文秘密',str(book))
            return {'answer':json.dumps({'ideas':['方案甲','方案乙','方案丙']})}
        result=self.call('/writing/generate',{'mode':'inspiration','position':2,'future':True},fake)
        self.assertEqual(len(result['inspirations']),3)
        with self.assertRaises(ValueError):w.scope_text('😀',1)

if __name__=='__main__':unittest.main()
