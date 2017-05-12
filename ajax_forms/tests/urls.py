try:
    # Removed in Django 1.6
    from django.conf.urls.defaults import url
except ImportError:
    from django.conf.urls import url

try:
    # Relocated in Django 1.6
    from django.conf.urls.defaults import patterns
except ImportError:
    # Completely removed in Django 1.10
    try:
        from django.conf.urls import patterns
    except ImportError:
        patterns = None

from .views import ContactView

_patterns = [
    url(r'^contact/$', ContactView.as_view(), name='contact')
]

if patterns is None:
    urlpatterns = _patterns
else:
    urlpatterns = patterns('', *_patterns)
