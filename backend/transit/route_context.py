"""Bounded short-lived contexts containing actual provider paths, not client claims."""
import secrets
import time
from collections import OrderedDict
from copy import deepcopy
from fastapi import HTTPException

_contexts=OrderedDict()
TTL=900
MAX_CONTEXTS=128

def remember(routes,origin,destination,goal,recorded_demo,selected=None):
    now=time.monotonic()
    for token in list(_contexts):
        if _contexts[token]['expires']<=now:
            del _contexts[token]
    if len(_contexts)>=MAX_CONTEXTS:
        _contexts.popitem(last=False)
    token=secrets.token_urlsafe(24)
    _contexts[token]={'routes':deepcopy(routes),'origin':origin,'destination':destination,
                      'goal':goal,'recorded_demo':recorded_demo,'selected':selected,'expires':now+TTL}
    return token

def resolve(token):
    value=_contexts.get(token)
    if not value or value['expires']<=time.monotonic():
        _contexts.pop(token,None)
        raise HTTPException(409,'Route context expired. Find road routes again to refresh the assistant.')
    value['expires']=time.monotonic()+TTL
    _contexts.move_to_end(token)
    return deepcopy(value)

def selection(token,selected):
    resolve(token)
    _contexts[token]['selected']=selected
