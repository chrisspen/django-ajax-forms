#from django.views.generic.edit import FormView, BaseCreateView, ModelFormMixin

from ajax_forms.views import AjaxModelFormView
from ajax_forms.views import AjaxFormView

from .forms import ContactForm, ContactModelForm
from .models import Contact

class ContactView(AjaxFormView):
    template_name = "contact.html"
    form_class = ContactForm

class ContactFormView(AjaxFormView):
    template_name = "contact-form.html"
    form_class = ContactForm

class ContactCreateView(AjaxModelFormView):
    template_name = "contact-model-form.html"
    form_class = ContactModelForm
    model = Contact
