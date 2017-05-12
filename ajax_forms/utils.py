from __future__ import print_function

from json import JSONEncoder

from django.utils.functional import Promise
from django.utils.encoding import force_unicode

class LazyEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Promise):
            return force_unicode(obj)
        return obj
