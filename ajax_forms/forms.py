from __future__ import print_function

from django import forms
from django.contrib.admin.helpers import AdminField#, AdminReadonlyField

class Form(forms.Form):

    def __iter__(self):
        for i, field in enumerate(self.fields):
            yield AdminField(self, field, is_first=(i == 0))
