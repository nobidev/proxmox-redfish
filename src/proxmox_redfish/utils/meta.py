from base64 import b64encode, b64decode
from json import dumps, loads
from re import findall

from ..config.settings import META_KEY


def get_description(config):
    raw = config.get("description", "")
    meta = {}
    if raw:
        try:
            raw = raw.rstrip()
            i = raw.rindex('\n')
            val = findall(fr'^<meta key="{META_KEY}" value="(.+)" />', raw[i + 1:]).pop()
            return raw[:i], loads(b64decode(val))
        except ValueError:
            return raw, meta
    return None, meta


def build_description(description, meta=None):
    s = description.rstrip() if description else ''
    meta = {k: v for k, v in meta.items() if v}
    if meta:
        s += "\n"
        s += f'<meta key="{META_KEY}" value="%s" />' % b64encode(dumps(meta).encode()).decode()
    if s:
        s += "\n"
    return s


def update_description(config, description=None, meta=None):
    v, _meta = get_description(config)
    if description:
        v = description
    _meta.update(meta)
    return build_description(v, _meta)
