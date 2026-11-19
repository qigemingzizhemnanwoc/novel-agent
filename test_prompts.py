import json,tempfile,unittest
from pathlib import Path
import workspace as w
from app import build_book
class PromptChecks(unittest.TestCase):
 def test_saved_prompts_routed_without_future(self):
  with tempfile.TemporaryDirectory() as folder:
   old=w.DATA;w.DATA=Path(folder)
   try:
    call=lambda path,body,ask=None:w.dispatch(path,body,build_book,ask)
    call('/prompts/save',{'inspiration':'灵感专用要求','draft':'写作专用要求'})
    self.assertEqual(call('/prompts/get',{})['draft'],'写作专用要求')
    project=w.create('测试',[{'text':'已发生。秘密结局'}])
    for mode in ['inspiration','draft']:
     def fake(book,key,prompt,*args,**kwargs):
      self.assertEqual(json.loads(prompt)['长期创作要求'],w.prompts()[mode])
      self.assertNotIn('秘密结局',str(book))
      return {'answer':json.dumps({'ideas':['一','二','三']}) if mode=='inspiration' else '正文'}
     result=call('/writing/generate',{'project':project['id'],'mode':mode,'position':4,'future':False},fake)
    self.assertEqual(result['drafts'][0]['custom_prompt'],'写作专用要求')
    with self.assertRaises(ValueError):call('/prompts/save',{'draft':'字'*10001})
    self.assertEqual(w.prompts()['draft'],'写作专用要求')
    call('/prompts/save',{'draft':'','inspiration':''});self.assertEqual(w.prompts()['draft'],'')
   finally:w.DATA=old
if __name__=='__main__':unittest.main()
