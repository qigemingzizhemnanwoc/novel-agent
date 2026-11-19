import tempfile,unittest
from pathlib import Path
import workspace as w
from app import build_book
class ExperimentCheck(unittest.TestCase):
 def test_optional_and_blind(self):
  with tempfile.TemporaryDirectory() as d:
   old=w.DATA;w.DATA=Path(d)
   try:
    p=w.create('测试',[{'text':'前文已经决斗。后文秘密'}]);calls=[]
    def summarize(key,model,messages,choice):
     calls.append(messages);self.assertNotIn('后文秘密',str(messages));self.assertEqual(choice,'none');return {'content':'决斗已经结束。'}
    def write(book,key,prompt,*args,**kwargs):
     self.assertNotIn('后文秘密',str(book));return {'answer':prompt}
    body={'project':p['id'],'mode':'draft','position':8,'future':False,'key':'fixture'}
    r=w.dispatch('/writing/generate',body,build_book,write,summarize)
    self.assertEqual(calls,[]);self.assertIsNone(r['drafts'][0]['experiment'])
    r=w.dispatch('/writing/generate',{**body,'event_check':True},build_book,write,summarize)
    self.assertEqual(len(calls),1);self.assertIn('决斗已经结束',r['drafts'][-1]['text']);self.assertTrue(r['drafts'][-1]['experiment'])
   finally:w.DATA=old
if __name__=='__main__':unittest.main()
