"""每次读取本地配置；不记录配置内容。"""
import json
import os
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'config.json'


def load():
    try:
        value = json.loads(PATH.read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict) or any(not isinstance(v, str) for k, v in value.items() if k not in ('top_k', 'prefix_chars')):
            return {}
        return value
    except (OSError, ValueError):
        return {}


def get(field, variable, default=''):
    return os.environ.get(variable, load().get(field, default)).strip()


def deepseek_key():
    return get('deepseek_key', 'DEEPSEEK_KEY')


def top_k():
    value = load().get('top_k', 6)
    return value if type(value) is int and value > 0 else 6


def prefix_chars():
    value = os.environ.get('NOVEL_PREFIX_CHARS', load().get('prefix_chars', 0))
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        value = int(value.strip())
    return value if type(value) is int and value >= 0 else 0


def deepseek_model():
    return get('deepseek_model', 'DEEPSEEK_MODEL', 'deepseek-flash')


def embed_key():
    return get('embed_key', 'NOVEL_EMBED_KEY')


def embed_base():
    return get('embed_base', 'NOVEL_EMBED_BASE', 'https://api.siliconflow.cn/v1')


def embed_model():
    return get('embed_model', 'NOVEL_EMBED_MODEL', 'BAAI/bge-m3')
