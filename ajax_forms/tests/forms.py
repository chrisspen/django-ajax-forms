from django import forms

from .models import Contact

#class ContactForm(forms.Form):
    #name = forms.CharField(max_length=50)

class ContactForm(forms.Form):
    name = forms.CharField()
    email = forms.EmailField()
    age = forms.IntegerField()

class ContactModelForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = '__all__'
