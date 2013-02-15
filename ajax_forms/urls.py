from django.conf.urls import patterns

urlpatterns = patterns('',
    (r'^/?(?P<model_name>[^/]+)/(?P<action>[^/]+)(?:/(?P<pk>[^/]+))?/?$',
        'ajax_forms.views.handle_ajax_crud'),
    (r'^/?(?P<model_name>[^/]+)/(?P<action>[^/]+)/(?P<attr_slug>[^/]+)/(?P<pk>[^/]+)/?$',
        'ajax_forms.views.handle_ajax_etter'),
)