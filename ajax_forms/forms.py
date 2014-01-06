from django import forms
from django.contrib.admin.helpers import AdminField, AdminReadonlyField

class Form(forms.Form):
    
    def __iter__(self):
        for i, field in enumerate(self.fields):
#            if field in self.readonly_fields:
#                yield AdminReadonlyField(self.form, field, is_first=(i == 0),
#                    model_admin=None #self.model_admin
#                )
#            else:
#                yield AdminField(self.form, field, is_first=(i == 0))
            yield AdminField(self, field, is_first=(i == 0))
#                
#        first = True
#        for name in self.fields:
#            yield AdminField(form=self, field=self[name], is_first=first)
#            if first:
#                first = False
            
#    def label_tag(self, contents=None, attrs=None):
##        print '$'*80
##        print 'custom.label_tag'
##        return 'hello'
#        attrs = attrs or {}
#        if self.field.required:
#            attrs['class'] = attrs.get('class', []) + ['required']
#        print 'attrs:',attrs
#        super(Form, self).label_tag(contents=contents, attrs=attrs)
        