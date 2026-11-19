"""保守的字面引用核对；不判断语义蕴含。"""
import re
import unicodedata

REF = re.compile(r'\[片段\s*(\d+)\]')
NUM = re.compile(r'\d+|[一二三四五六七八九十百千零两]+')

def integer(s):
    if s.isascii() and s.isdigit():
        return int(s)
    digits = dict(zip('零一二三四五六七八九两', [0,1,2,3,4,5,6,7,8,9,2]))
    if not any(c in s for c in '十百千'):
        return digits.get(s)  # 两三等范围、连续中文数字宁可漏报。
    total = part = 0
    last = 10000
    for c in s:
        if c in digits:
            if part:
                return None
            part = digits[c]
        else:
            unit = {'十':10,'百':100,'千':1000}[c]
            if unit >= last:
                return None
            total += (part or 1) * unit
            part, last = 0, unit
    return total + part

def numbers(text):
    result = set()
    for m in NUM.finditer(text):
        # 不把模糊量词、小数、成语中的单字数字当成确切事实。
        if m.group() == '十' and re.match(r'分[^钟。！？，、；\s]', text[m.end():]):
            continue
        before, after = text[max(0,m.start()-1):m.start()], text[m.end():m.end()+1]
        if before in ('.','约','数') or after in ('.','几','多','余','来'):
            continue
        if not m.group().isascii() and after not in '年月日天时分秒岁个人步里米次百千万':
            continue
        value = integer(m.group())
        if value is not None:
            result.add(value)
    return result

def normalized(text):
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))

def check(answer, evidence, *, chunks=None, names=()):
    sources = {c['id']: c['text'] for c in evidence}
    context = {c['id']: c['text'] for c in (chunks or evidence)}
    failures = []
    # 句末标点后的引用仍归属于前一句。
    for match in re.finditer(r'(?:“[^”]*”|‘[^’]*’|「[^」]*」|[^。！？\n])+[。！？]?(?:[ \t]*\[片段\s*\d+\])*', answer):
        sentence = match.group()
        ids = [int(n) for n in REF.findall(sentence) if int(n) in sources]
        if '【推测】' in sentence or '【主线】' in sentence:
            if ids:
                claim = normalized(REF.sub('', sentence).replace('【推测】', '').replace('【主线】', ''))
                support = '\n'.join(sources[i] for i in ids)
                # 只识别明确的字面事实与亲属数量，不用同一个数字推断语义相同。
                counts = re.findall(r'(?:有|还有)([一二三四五六七八九十两0-9]+)个(姐姐|妹妹|哥哥|弟弟)', claim)
                source_counts = re.findall(r'(?:有|还有)([一二三四五六七八九十两0-9]+)个(姐姐|妹妹|哥哥|弟弟)', support)
                direct = len(claim) >= 4 and claim in normalized(support)
                direct = direct or any((integer(n), relation) in {(integer(v), r) for v, r in source_counts} for n, relation in counts)
                if direct:
                    failures.append(dict(sentence=sentence, id=ids[0], kind='speculation_misuse', detail='引用原文已有直接表述，请核对主体并去掉【推测】'))
                    continue
                failures.append(dict(sentence=sentence, id=ids[0], kind='speculation', detail='推测结论，未做字面核对'))
            else:
                failures.append(dict(sentence=sentence, id=None, kind='reference', detail='推测结论缺少有效片段引用'))
            continue
        if not ids:
            continue
        text = REF.sub('', sentence)
        support = '\n'.join(context.get(n, '') for i in ids for n in (i-1,i,i+1))
        def fail(kind, detail):
            failures.append(dict(sentence=sentence, id=ids[0], kind=kind, detail=detail))
        factual_text = text
        for quote in re.finditer(r'“([^”]+)”|‘([^’]+)’|「([^」]+)」', text):
            value = next(s for s in quote.groups() if s)
            # 明确否认原文包含某段文字，不属于正向引用；仅匹配紧邻引号的说明。
            if re.search(r'(?:没有|并未|未)(?:明确)?(?:写|写出|说|提到|记载)[：: ]*$', text[:quote.start()]):
                factual_text = factual_text.replace(quote.group(), '')
                continue
            # 显式省略号允许顺序节引，间隔最多80个规范化字符；不容许任意改写。
            parts = [normalized(p) for p in re.split(r'…+|\.{3,}', value)]
            parts = [p for p in parts if p]
            pattern = '.{0,80}?'.join(re.escape(p) for p in parts)
            if not parts or not re.search(pattern, normalized(support)):
                fail('quote', '引文未找到：' + value)
        for value in sorted(numbers(factual_text) - numbers(support)):
            fail('number', '数字未找到：' + str(value))
        for name in sorted(set(names)):
            if name and name in factual_text and name not in support:
                fail('name', '疑似张冠李戴：' + name)
    return failures
