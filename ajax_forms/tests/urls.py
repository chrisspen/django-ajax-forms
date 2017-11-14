from django.conf.urls import url

from .views import ContactView, ContactFormView, ContactCreateView

urlpatterns = [
    url(r'^contact/$', ContactView.as_view(), name='contact'),
    url(r'^contactform/$', ContactFormView.as_view(), name="contact_form"),
    url(r'^contactmodel/$', ContactCreateView.as_view(), name="contact_model_form"),
]
