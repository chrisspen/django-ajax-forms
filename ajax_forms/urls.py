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

_patterns = [
    url(r'^/?(?P<model_name>[^/]+)/(?P<action>[^/]+)(?:/(?P<pk>[^/]+))?/?$',
        'ajax_forms.views.handle_ajax_crud'),
    url(r'^/?(?P<model_name>[^/]+)/(?P<action>[^/]+)/(?P<attr_slug>[^/]+)/(?P<pk>[^/]+)/?$',
        'ajax_forms.views.handle_ajax_etter'),
]

if patterns is None:
    urlpatterns = _patterns
else:
    urlpatterns = patterns('', *_patterns)
