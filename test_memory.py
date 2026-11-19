import unittest
from unittest.mock import patch
import app

class MemoryTests(unittest.TestCase):
    def setUp(self):
        app.MEMORY.clear()

    def test_incremental_and_failure(self):
        history = []
        summaries = []
        def compress(key, model, messages):
            text = '月考第41名' if any('41' in m['content'] for m in messages) else '用户讨论月考'
            summaries.append(text)
            return text
        with patch.object(app, 'summarize', side_effect=compress) as mock:
            for turn in range(1, 41):
                history.extend([{'role':'user', 'content': ('月考第41名' if turn == 2 else '讨论月考') + '。' * 1000}, {'role':'assistant', 'content':'已记录' + '。' * 1000}])
                state = app.conversation_memory('test', 'key', 'model', history, '月考排名？')
                messages = [{'role':'system', 'content':app.SYSTEM}] + app.conversation_messages(history, state) + [{'role':'user', 'content':'月考排名？'}]
                total = sum(len(m['content']) for m in messages)
                full = len(app.SYSTEM) + len('月考排名？') + sum(len(m['content']) for m in history)
                print(f'round={turn:02} chars={total} full={full} ratio={total/full:.2%} summaries={mock.call_count} compressed={bool(state)}')
                if state:
                    self.assertLessEqual(total/full, .5, f"round={turn}")
                if turn in (20, 40):
                    self.assertIn('41', str(messages))
            self.assertLessEqual(mock.call_count, 7)
            self.assertLessEqual(total/full, .25)
            before = mock.call_count
            app.conversation_memory('test', 'key', 'model', history, '月考排名？')
            self.assertEqual(before, mock.call_count)
        print('摘要样本（模拟器输出，不是实际模型）：', summaries[:5])
        with patch.object(app, 'summarize', side_effect=TimeoutError):
            self.assertIsNone(app.conversation_memory('failure', 'key', 'model', history, '月考排名？'))
        self.assertEqual(len(app.conversation_messages(history)), 12)

    @unittest.skipUnless(__import__("importlib.util", fromlist=["find_spec"]).find_spec("eval"), "公开仓库不包含版权评测模块")
    def test_failed_eval_preserves_previous_report(self):
        import tempfile
        from pathlib import Path
        from eval.run import save_report
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            previous = directory / 'report.json'
            previous.write_text('previous valid evidence', encoding='utf-8')
            failed = {'broken': ['network unavailable'], 'vector_skip': '', 'rows': []}
            self.assertEqual(save_report(failed, directory).name, 'report.failed.json')
            self.assertEqual(previous.read_text('utf-8'), 'previous valid evidence')

    def test_optional_summary_both_paths(self):
        history = [{'role':'user', 'content':str(i)} for i in range(20)]
        state = {'summary':'月考第41名', 'covered':12}
        seen = []
        def caller(key, model, messages, choice):
            seen.append(list(messages))
            return {'content':'已记录'}
        def stream(*args):
            yield 'done', caller(*args)
        app.ask({'chunks':[]}, 'key', '问题', history, 'model', caller=caller, system_prompt='测试', summary=state)
        list(app.ask_stream({'chunks':[]}, 'key', '问题', history, 'model', caller=stream, system_prompt='测试', summary=state))
        self.assertEqual(seen[0], seen[1])
        self.assertIn('41', seen[0][1]['content'])
        self.assertEqual(seen[0][2]['content'], '12')

if __name__ == '__main__':
    unittest.main()
