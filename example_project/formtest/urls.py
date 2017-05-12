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

from formtest.views import ContactFormView
from formtest.views import ContactCreateView

_patterns = [
    url(r'^contact/$', ContactFormView.as_view(), name="contact_form"),
    url(r'^contactmodel/$', ContactCreateView.as_view(), name="contact_model_form"),
]

if patterns is None:
    urlpatterns = _patterns
else:
    urlpatterns = patterns('', *_patterns)
