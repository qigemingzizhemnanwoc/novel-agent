"""流式协议、工具循环和断开清理；全部离线，不使用真实模型。"""
import contextlib
import io
import http.client
import json
import threading
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from unittest.mock import patch

import app


def sse(delta=None, finish=None):
    return ('data: ' + json.dumps({'choices': [{'delta': delta or {}, 'finish_reason': finish}]}, ensure_ascii=False) + '\n\n').encode()


def tool(n, terms):
    return {'id': f't{n}', 'type': 'function', 'function': {'name': 'search_novel',
            'arguments': json.dumps({'terms': terms})}}


class StreamChecks(unittest.TestCase):
    def setUp(self):
        self.book = app.build_book('合成', [{'text': '甲在河边。乙在山上。'}])

    def test_incremental_content_and_close(self):
        response = io.BytesIO(sse({'content': '你好'}) + sse({'content': '世界'}) + sse(finish='stop') + b'data: [DONE]\n\n')
        with patch.object(app, 'urlopen', return_value=response) as opened:
            events = app.complete_stream('fixture', 'model', [], 'none')
            self.assertEqual(next(events), ('delta', '你好'))
            self.assertFalse(response.closed)
            self.assertLess(response.tell(), len(response.getvalue()))
            rest = list(events)
            self.assertEqual(rest[0], ('delta', '世界'))
            self.assertEqual(rest[-1][1]['content'], '你好世界')
            self.assertTrue(response.closed)
            self.assertTrue(json.loads(opened.call_args.args[0].data)['stream'])

    def test_interleaved_tool_arguments_by_index(self):
        chunks = [
            {'tool_calls': [{'index': 1, 'id': 'b', 'function': {'name': 'read_', 'arguments': '{"id":'}},
                            {'index': 0, 'id': 'a', 'function': {'name': 'search_', 'arguments': '{"terms":["'}}]},
            {'tool_calls': [{'index': 0, 'function': {'name': 'novel', 'arguments': '甲"]}'}},
                            {'index': 1, 'function': {'name': 'context', 'arguments': '1}'}}]}]
        response = io.BytesIO(b''.join(sse(x) for x in chunks) + sse(finish='tool_calls') + b'data: [DONE]\n\n')
        with patch.object(app, 'urlopen', return_value=response):
            events = list(app.complete_stream('fixture', 'model', [], 'required'))
        calls = events[0][1]
        self.assertEqual(events[0][0], 'tool_calls')
        self.assertEqual([x['id'] for x in calls], ['a', 'b'])
        self.assertEqual(calls[0]['function'], {'name': 'search_novel', 'arguments': '{"terms":["甲"]}'})
        self.assertEqual(json.loads(calls[1]['function']['arguments']), {'id': 1})
        self.assertEqual(events[-1][1]['tool_calls'], calls)

    def test_eof_preserves_delta_and_does_not_finalize(self):
        response = io.BytesIO(sse({'content': '已收到'}))
        with patch.object(app, 'urlopen', return_value=response):
            events = app.complete_stream('fixture', 'model', [], 'none')
            self.assertEqual(next(events), ('delta', '已收到'))
            with self.assertRaisesRegex(ValueError, '连接中断，回答可能不完整'):
                next(events)
        self.assertTrue(response.closed)

    def test_upstream_errors_and_malformed_data(self):
        for failure, message in [(HTTPError('https://example.invalid', 401, '', {}, None), 'API Key 无效'),
                                 (URLError('fixture'), '连接 DeepSeek 失败')]:
            with self.subTest(message=message), patch.object(app, 'urlopen', side_effect=failure):
                with self.assertRaisesRegex(ValueError, message):
                    list(app.complete_stream('fixture', 'model', [], 'none'))
        for body, message in [(b'data: invalid\n\n', '格式无效'),
                              (sse(finish='length'), '长度限制'),
                              (b'data: [DONE]\n\n', '连接中断')]:
            with self.subTest(message=message), patch.object(app, 'urlopen', return_value=io.BytesIO(body)):
                with self.assertRaisesRegex(ValueError, message):
                    list(app.complete_stream('fixture', 'model', [], 'none'))

    def test_two_tool_rounds_match_nonstream_result(self):
        replies = [{'content': None, 'tool_calls': [tool(1, ['甲'])]},
                   {'content': None, 'tool_calls': [tool(2, ['乙'])]},
                   {'content': '甲在河边。[片段 1]'}]
        plain = iter(replies)
        expected = app.ask(self.book, 'fixture', '位置？', [], 'model', caller=lambda *a: next(plain))
        rounds = []
        def caller(key, model, messages, choice):
            rounds.append(choice)
            reply = replies[len(rounds) - 1]
            if reply.get('tool_calls'):
                yield 'tool_calls', reply['tool_calls']
            else:
                for char in reply['content']:
                    yield 'delta', char
            yield 'done', reply
        events = list(app.ask_stream(self.book, 'fixture', '位置？', [], 'model', caller=caller))
        self.assertEqual(rounds, ['required', 'auto', 'auto'])
        self.assertEqual([e['text'] for e in events if e['type'] == 'tool'], expected['trace'])
        self.assertEqual(''.join(e['text'] for e in events if e['type'] == 'delta'), expected['answer'])
        result = events[-1]['payload']
        for key in ['answer', 'evidence', 'trace', 'notice', 'degraded']:
            self.assertEqual(result[key], expected[key])
        self.assertEqual(set(result), set(expected))
        self.assertEqual([r['hits'] for r in result['retrievals']], [r['hits'] for r in expected['retrievals']])

    def test_invalid_parameters_and_citation(self):
        for key, question in [('', '位置？'), ('fixture', '')]:
            with self.assertRaises(ValueError):
                list(app.ask_stream(self.book, key, question, [], 'model'))
        def caller(*args):
            yield 'delta', '错误引用[片段 999]'
            yield 'done', {'content': '错误引用[片段 999]'}
        events = app.ask_stream(self.book, 'fixture', '位置？', [], 'model', caller=caller)
        self.assertEqual(next(events)['type'], 'delta')
        with self.assertRaisesRegex(ValueError, '无法核对'):
            list(events)

    def handler(self, writer):
        handler = object.__new__(app.Handler)
        handler.wfile = writer
        handler.send_response = lambda *args: None
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        return handler

    def test_ndjson_error_preserves_partial_text(self):
        def events():
            yield {'type': 'delta', 'text': '第一行\n第二行'}
            raise ValueError('连接中断，回答可能不完整')
        output = io.BytesIO()
        with contextlib.redirect_stdout(io.StringIO()):
            self.handler(output).send_stream(events())
        rows = [json.loads(line) for line in output.getvalue().decode().splitlines()]
        self.assertEqual(rows, [{'type': 'delta', 'text': '第一行\n第二行'},
                                {'type': 'error', 'message': '连接中断，回答可能不完整'}])

    def test_client_disconnect_closes_upstream(self):
        closed = []
        def caller(*args):
            try:
                yield 'delta', '片段'
                self.fail('客户端断开后不应继续取模型流')
            finally:
                closed.append(True)
        class Disconnected:
            def write(self, data):
                raise BrokenPipeError()
        self.handler(Disconnected()).send_stream(app.ask_stream(self.book, 'fixture', '位置？', [], 'model', caller=caller))
        self.assertEqual(closed, [True])

    def test_http_stream_and_origin_guard(self):
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        def events(*args):
            yield {'type': 'delta', 'text': '内容'}
            yield {'type': 'final', 'payload': {'answer': '内容'}}
        try:
            with patch.object(app, 'URL', url), patch.object(app, 'ask_stream', side_effect=events), contextlib.redirect_stdout(io.StringIO()):
                headers = {'Content-Type': 'application/json', 'Accept': 'application/x-ndjson', 'Origin': url}
                request = Request(url + '/ask', data=b'{"key":"fixture","question":"test"}', headers=headers)
                with urlopen(request, timeout=3) as response:
                    self.assertIn('application/x-ndjson', response.headers['Content-Type'])
                    self.assertEqual(json.loads(response.readline())['type'], 'delta')
                    self.assertEqual(json.loads(response.readline())['type'], 'final')
                request.headers['Origin'] = 'https://example.invalid'
                with self.assertRaises(HTTPError) as error:
                    urlopen(request, timeout=3)
                self.assertEqual(error.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())

    def test_disconnect_during_silent_upstream(self):
        self.check_silent_disconnect(False)

    def test_disconnect_before_upstream_headers(self):
        self.check_silent_disconnect(True)

    def check_silent_disconnect(self, before_headers):
        release = threading.Event()
        finished = threading.Event()
        received = threading.Event()
        class Upstream(app.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                received.set()
                if before_headers:
                    release.wait(5)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                self.wfile.write(sse({'content': '已显示'}))
                self.wfile.flush()
                release.wait(5)
        class Local(app.Handler):
            def finish(self):
                try:
                    super().finish()
                finally:
                    finished.set()
        upstream = app.ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), Local)
        threads = [threading.Thread(target=s.serve_forever) for s in (upstream, server)]
        original = app.open_stream
        def redirect(request, timeout):
            return original(Request(f'http://127.0.0.1:{upstream.server_port}', data=request.data), timeout)
        url = f'http://127.0.0.1:{server.server_port}'
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        logs = io.StringIO()
        try:
            with patch.object(app, 'open_stream', side_effect=redirect), patch.object(app, 'URL', url), \
                 patch.object(app, 'BOOK', self.book), contextlib.redirect_stdout(logs), contextlib.redirect_stderr(logs):
                for thread in threads:
                    thread.start()
                connection.request('POST', '/ask', json.dumps({'key': 'fixture', 'question': '位置？'}),
                                   headers={'Origin': url, 'Accept': 'application/x-ndjson'})
                response = connection.getresponse()
                self.assertTrue(received.wait(2))
                if not before_headers:
                    self.assertEqual(json.loads(response.readline())['text'], '已显示')
                response.close()
                connection.close()
                self.assertTrue(finished.wait(2), '上游静默时客户端断开未结束请求线程')
                self.assertFalse(any(t.name == 'stream-disconnect' and t.is_alive() for t in threading.enumerate()))
                self.assertNotIn('Traceback', logs.getvalue())
        finally:
            release.set()
            connection.close()
            for s in (server, upstream):
                s.shutdown()
                s.server_close()
            for thread in threads:
                thread.join(timeout=3)
