from django.conf.urls import url

from ajax_forms import views

urlpatterns = [
    url(r'^/?(?P<model_name>[^/]+)/(?P<action>[^/]+)(?:/(?P<pk>[^/]+))?/?$', views.handle_ajax_crud),
    url(r'^/?(?P<model_name>[^/]+)/(?P<action>[^/]+)/(?P<attr_slug>[^/]+)/(?P<pk>[^/]+)/?$', views.handle_ajax_etter),
]
