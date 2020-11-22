import datetime

from .settings import is_development
import json


def info(msg):
    print("[tabnine] {} | {}".format(_time(), msg))


def debug(msg, if_development=True):
    if if_development and is_development():
        info(msg)


def jsonstr(obj):
    debug(json.dumps(obj, indent=2))


def _time():
    return datetime.datetime.now().strftime("%m/%d/%y %H:%M:%S.%f")[:-3]
