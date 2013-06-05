import re
import uuid

from django import forms
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.http import HttpResponse, Http404
from django.utils import simplejson
from django.views.decorators.http import require_POST
from django.forms.models import modelformset_factory
from django.forms.formsets import BaseFormSet
from django.forms.forms import BaseForm
from django.forms.models import ModelForm
from django.views.generic.edit import BaseFormView
from django.views.generic.edit import BaseCreateView
from django.views.generic import FormView
from django.views.generic.edit import FormMixin
from django.views.generic import View
from django.views.generic.edit import ModelFormMixin
from django.views.generic.edit import TemplateResponseMixin
from django.views.generic.edit import ProcessFormView
from django.views.generic.edit import SingleObjectMixin
from django.utils.safestring import mark_safe
from django.template import Context, Template
from django.template.loader import render_to_string, get_template
from django.db import models

from ajax_forms.utils import LazyEncoder
from ajax_forms import constants as C

FORM_SUBMITTED = "valid_submit"

class ValidationError(Exception):
    pass

class BaseAjaxFormSet(BaseFormSet):
    
    def __unicode__(self):
        forms = u' '.join([unicode(form) for form in self])
        return mark_safe(u'\n'.join([unicode(self.management_form), forms]))
    
@csrf_exempt
def handle_ajax_crud(request, model_name, action, **kwargs):
    """
    Redirects the standard record manipulation URLs to the appropriate form
    method.
    """
    
    form_cls = SLUG_TO_FORM_REGISTRY.get(model_name)
    if not form_cls:
        if settings.DEBUG:
            raise Exception, 'No form registered to slug: %s' % (model_name,)
        raise Http404
    if action not in C.CRUD_ACTIONS:
        if settings.DEBUG:
            raise Exception, 'Invalid action: %s' % (action,)
        raise Http404
    
    class O(object):
        pass
    form = O()
    form.__class__ = form_cls
    form.init()
    pk = kwargs.get('pk', 0)
    if action != C.CREATE:
        try:
            obj = form.get_object(pk)
            form.instance = obj
        except form.Meta.model.DoesNotExist:
            if settings.DEBUG:
                raise
            raise Http404
    
    # Enforce any model/form specific permissions rules. 
    check_perm_method = getattr(form, 'has_%s_permission' % action)
    perm_args = {}
    action_args = {}
    if action == C.DELETE or action == C.READ:
        perm_args = dict(obj=obj)
        action_args = perm_args
    elif action == C.VIEW:
        perm_args = dict(obj=obj)
        action_args = dict(obj=obj)
    elif action == C.CREATE:
        if form.method.lower() == 'post':
            action_args = request.POST
        elif form.method.lower() == 'get':
            action_args = request.GET
        else:
            action_args = request.REQUEST
    else:
        perm_args = kwargs
        perm_args['obj'] = obj
        action_args = perm_args
    if not check_perm_method(request, **perm_args):
        if settings.DEBUG:
            raise Exception, 'Permission denied.'
        raise Http404
    
    action_args = dict((str(k),v) for k,v in action_args.iteritems())
    response = getattr(form, action)(request, **action_args)
    if action == C.VIEW:
        return HttpResponse(
            response,
            content_type='text/html')
    return HttpResponse(
        simplejson.dumps(response),
        content_type='application/json')

@csrf_exempt
def handle_ajax_etter(request, model_name, action, attr_slug, pk):
    """
    Returns single object attributes as JSON.
    """
    
    form_cls = SLUG_TO_FORM_REGISTRY.get(model_name)
    if not form_cls:
        if settings.DEBUG:
            raise Exception, 'No form registered to slug: %s' % (model_name,)
        raise Http404
    if action not in (C.SET, C.GET):
        if settings.DEBUG:
            raise Exception, 'Invalid action: %s' % (action,)
        raise Http404
    
    # Instantiate form while bypassing __init__().
    class O(object):
        pass
    form = O()
    form.__class__ = form_cls
    form.init()
    
    value = None
    try:
        obj = form.get_object(pk)
        form.instance = obj
    except form.Meta.model.DoesNotExist:
        if settings.DEBUG:
            raise
        raise Http404
    
    attr_name = form.slug_to_attr(attr_slug)
    
    permission_method = getattr(form, 'has_%s_permission' % action)
    if not permission_method(request=request, obj=obj, attr=attr_name):
        if settings.DEBUG:
            raise Exception, 'Permission denied.'
        raise Http404
    action_method_name = '%s_%s' % (action, attr_name)
    success = True
    message = None
    value = None
    try:
        if hasattr(form, action_method_name):
            value = getattr(form, action_method_name)(request=request, obj=obj)
        elif hasattr(obj, attr_name):
            if action == C.GET:
                value = getattr(obj, attr_name)
            else:
                field = form.Meta.model._meta.get_field(attr_name)
                value = request.REQUEST['value']
                if isinstance(field, models.ForeignKey):
                    value = field.rel.to.objects.get(pk=value)
                elif isinstance(field, models.BooleanField):
                    if value.lower() in ('1', 'true', 'on'):
                        value = True
                    else:
                        value = False
                setattr(obj, attr_name, value)
                obj.save()
                value = getattr(obj, attr_name)
                if hasattr(value, 'pk'):
                    value = value.pk
    except ValidationError, e:
        success = False
        message = str(e)
    response = {
        'success': success
    }
    if message:
        response['message'] = message
    if value is not None:
        response['value'] = value
    if attr_name in form.onchange_callback:
        response['callback'] = form.onchange_callback[attr_name]
    return HttpResponse(
        simplejson.dumps(response),
        content_type='application/json')

class JSONResponseMixin(object):
    def render_to_json_response(self, context):
        return self.get_json_response(self.convert_context_to_json(context))

    def get_json_response(self, content, **httpresponse_kwargs):
        return HttpResponse(content, content_type='application/json', **httpresponse_kwargs)

    def convert_context_to_json(self, context):
        return simplejson.dumps(context)

class RealSubmitMixin(object):
    def is_actual_submit(self):
        if self.request.POST.get('submit') == 'true':
            return True
        return False

class AjaxValidFormMixin(RealSubmitMixin):
    def form_valid(self, form):
        response = None
        if self.is_actual_submit():
            response = self.render_to_json_response({ 'valid': True, 'submitted': True })
        if self.is_actual_submit() and getattr(self, FORM_SUBMITTED, False):
            self.valid_submit(form)

        if not response:
            return self.render_to_json_response({ 'valid': True })
        return response

class AjaxValidModelFormMixin(RealSubmitMixin):
    def singleObjectModelToDict(self, object):
        subObject = object.__dict__
        del subObject['_state']
        return subObject

    def form_valid(self, form):
        self.object = None
        form_submit = getattr(self, FORM_SUBMITTED, False)

        if self.is_actual_submit():
            self.object = form.save()
        if form_submit and self.is_actual_submit():
            self.valid_submit(form)

        if self.object:
            return self.render_to_json_response({ 'valid': True, 'submitted': True, 'object': self.singleObjectModelToDict(self.object)})

        return self.render_to_json_response({ 'valid': True })

class AjaxInvalidFormMixin(JSONResponseMixin, TemplateResponseMixin):
    def get_form_class(self):
        """
        A form_class can either be defined by inheriting from AjaxValidatingForm and setting the 
        form_class property or by adding the form_class in the url definition.
        """
        form_class = getattr(self, "form_class", False)
        if not form_class:
            form_class = self.kwargs["form_class"]
        return form_class


    def form_invalid(self, form):
        # Get the BoundFields which contains the errors attribute 
        if isinstance(form, BaseFormSet):
            errors = {}
            formfields = {}
            for f in form.forms:
                for field in f.fields.keys():
                    formfields[f.add_prefix(field)] = f[field]
                for field, error in f.errors.iteritems():
                    errors[f.add_prefix(field)] = error
            if form.non_form_errors():
                errors['__all__'] = form.non_form_errors()
        else:
            formfields = dict([(fieldname, form[fieldname]) for fieldname in form.fields.keys()])
            errors = form.errors

        if self.request.POST.has_key('fields'):
            fields = request.POST.getlist('fields') + ['__all__']
            errors = dict([(key, val) for key, val in errors.iteritems() if key in fields])

        final_errors = {}
        for key, val in errors.iteritems():
            if '__all__' in key:
                final_errors[key] = val
            elif not isinstance(formfields[key].field, forms.FileField):
                html_id = formfields[key].field.widget.attrs.get('id') or formfields[key].auto_id
                html_id = formfields[key].field.widget.id_for_label(html_id)
                final_errors[html_id] = val
        data = {
            'valid': False or not final_errors,
            'errors': final_errors,
        }
        return self.render_to_json_response(data)

class AjaxFormView(AjaxValidFormMixin, AjaxInvalidFormMixin, FormView):
    pass

class AjaxModelFormView(AjaxValidModelFormMixin, AjaxInvalidFormMixin, BaseCreateView):
    pass

SLUG_TO_FORM_REGISTRY = {}

def register_ajax_cls(cls, slug):
    if slug in SLUG_TO_FORM_REGISTRY and SLUG_TO_FORM_REGISTRY[slug] != cls:
        raise Exception, ('Form slug conflict! Forms %s and %s ' + \
            'both use the same slug "%s"!') \
                % (cls, SLUG_TO_FORM_REGISTRY[slug], slug)
    SLUG_TO_FORM_REGISTRY[slug] = cls
    for sf in cls.sub_forms:
        sf.parent_form_cls = cls

#class SubclassTracker(ModelForm.__metaclass__):
class SubclassTracker(type(ModelForm)):
    """
    Allows for tracking ajax form subclasses and associating them with
    a unique slug for referencing via ajax calls.
    """
    def __init__(cls, name, bases, dct):
        slug = None
        if name != 'BaseAjaxModelForm' and issubclass(cls, BaseAjaxModelForm) \
        and cls.__module__ != forms.models.__name__:
            if hasattr(cls, 'ajax_slug'):
                slug = cls.ajax_slug
            elif hasattr(cls, 'Meta') and hasattr(cls.Meta, 'ajax_slug'):
                slug = cls.Meta.ajax_slug.__name__.lower().strip()
            elif hasattr(cls, 'model'):
                slug = cls.model.__name__.lower().strip()
            elif hasattr(cls, 'Meta') and hasattr(cls.Meta, 'model'):
                slug = cls.Meta.model.__name__.lower().strip()
            if slug:
                register_ajax_cls(cls, slug)
        super(SubclassTracker, cls).__init__(name, bases, dct)
        
class BaseAjaxModelForm(ModelForm):
    
    __metaclass__ = SubclassTracker

    required_fields = ()

    ajax_getters = ()
    
    ajax_setters = ()
    
    verbose_names = {}
    
    validation_rules = {}
    
    onchange_callback = {}
    
    method = 'post'
    
    submit_value = 'Save'
    
    template = None
    
    submit_button_classes = ''
    
    can_create = False
    
    can_read = False
    
    can_update = False
    
    can_delete = False
    
    can_view = False
    
    insert_element = 'body'
    
    js_extra = {} # {field name: [js template]}
                
    sub_forms = ()
    
    slug = None
    
    parent_form_cls = None

    def __init__(self, *args, **kwargs):
        
        self.id = str(uuid.uuid4()).replace('-', '')
        if 'prefix' not in kwargs:
            kwargs['prefix'] = 'form-%s' % (self.id,)
        
        super(BaseAjaxModelForm, self).__init__(*args, **kwargs)
        
        self._validation_rules = {} # {field:rules}
        self.init()
        self.form_field_names = []
        self.checkbox_fields = []
        self.model_field_name_to_form_field_name = {}
        self.js_extra_rendered = []
        
        assert self.prefix
        
        for fn in self.fields:

            # Load client-side form field validation rules.
            vkey = self.prefix + '-' + fn
            self.form_field_names.append(vkey)
            self._validation_rules[vkey] = self.get_validation_rules(fn)
            self.model_field_name_to_form_field_name[fn] = vkey
            
            for js_template in self.js_extra.get(fn, []):
                self.js_extra_rendered.append(js_template % dict(
                    id='id_'+self.model_field_name_to_form_field_name[fn],
                    name=self.model_field_name_to_form_field_name[fn],
                ))
            
            # Set custom labels.
            if fn in self.verbose_names:
                self.fields[fn].label = self.verbose_names.get(fn).title()
            
#            if isinstance(self.fields[fn].widget, forms.widgets.CheckboxInpt):
#                self.checkbox_fields.append(fn)
#                self.fields[fn].is_checkbox = True
#            else:
#                self.fields[fn].is_checkbox = False
            
            # Tag each field with the primary key of the record it belongs to.
            if self.instance.pk:
                self.fields[fn].widget.attrs['pk'] = self.instance.pk
                
            # Tag each field with it's vanilla field name.
            self.fields[fn].widget.attrs['field-name'] = fn
            
            # Set optional AJAX setter server-side callbacks.
            if self.instance.pk and fn in self.ajax_setters:
                self.fields[fn].widget.attrs['ajax-set-url'] = self.set_url(fn)
        
        # Confirm that each sub-form has a field that references
        # the current form's model.
        parent_field_names = set(f.name for f in self.Meta.model._meta.fields)
        self.sub_formset_instances = [] # [(sf,formset)]
        for sf in self.sub_forms:
            #assert isinstance(sf, AjaxSubForm)
            sf.parent_form_cls = type(self)
            
            fk_name_to_model = dict(
                (f.name, f.rel.to)
                for f in sf.Meta.model._meta.fields
                if isinstance(f, models.ForeignKey)
            ) # {name:model}
            fk_model_to_name = dict((v,k) for k,v in fk_name_to_model.iteritems())
            fk_models = fk_name_to_model.values()
            fk_models_set = set(fk_name_to_model.values())
            
            # Identify a ForeignKey field in the sub-form whose model
            # matches the parent form's model.
            if sf.fk:
                assert sf.fk in fk_name_to_model, \
                    ('Sub-form %s refers to foreign key field "%s" which ' + \
                     'does not exist.') % (sf, sf.fk)
            else:
                _count = fk_models.count(self.Meta.model)
                assert _count > 0, ('Sub-form %s could not be correlated ' + \
                    'with parent model %s.') % (sf, self.Meta.model.__name__)
                assert _count == 1, ('Sub-form %s correlated to multiple ' + \
                    'fields in parent model %s. Use fk to specify which ' + \
                    'field to use.') % (sf, self.Meta.model.__name__)
                sf.fk = fk_model_to_name[self.Meta.model]
        
            if self.instance.pk:
                #q = sf.Meta.model.objects.filter(**{sf.fk:self.instance})
                q = sf.get_child_queryset(self.instance)
                formset_cls = modelformset_factory(
                    sf.Meta.model,
                    form=sf,
                    extra=sf.extra,#number of empty forms to show
                )
                formset = formset_cls(
                    queryset=q,
                    initial=[{sf.fk:self.instance.pk}],
                    prefix=self.prefix+'-'+sf.prefix,
                )
                self.sub_formset_instances.append((sf, formset))
                for form in formset:
                    self._validation_rules.update(form._validation_rules)
                    self.js_extra_rendered.extend(form.js_extra_rendered)
    
    def init(self):
        self.__attr_to_slug = {}
        self.__slug_to_attr = {}
        for fn in self.Meta.model._meta.fields:
            # Register per-attribute slugs.
            self._attr_to_slug(fn.name)
    
    def get_action_url(self):
        if self.instance:
            return self.create_url
        else:
            return '?'
    
    def get_ajax_getters(self):
        return self.ajax_getters
    
    def get_ajax_setters(self):
        return self.ajax_setters
    
    @property
    def delete_id(self):
        return self.instance.id
    
    @property
    def delete_model(self):
        return self.Meta.model.__name__
    
    def delete_link(self):
        t = Template(u"""<a
            href="#"
            ajax-url="{{ form.delete_url }}"
            class="ajax-delete-link"
            ajax-model="{{ form.delete_model }}"
            onclick="return "
            alt="delete"
            title="delete">x</a>""")
        c = Context(dict(
            form_id=self.id,
            form=self,
        ))
        return t.render(c)
    
    def create_button(self):
        t = Template(u"""<input
        type="submit"
        value="Create"
        create_button="true"
        ajax-prefix="{{ form.prefix }}"
        ajax-url="{{ form.create_url }}"
        onclick="return false;" />""")
        c = Context(dict(
            form_id=self.id,
            form=self,
        ))
        return t.render(c)
    
    def __unicode__(self):
        if self.template:
            c = Context(dict(
                form=self,
                form_id=self.id,
            ))
            t = get_template(self.template)
            return t.render(c)
        else:
            return self.as_p_complete()
    
    def get_submit_value(self):
        return self.submit_value
    
    def get_validation_rules(self, fn):
        from django.db import models
        field_def = self.Meta.model._meta.get_field(fn)
        
        rules = {}
        
        if self.is_field_required(fn):
            rules['required'] = True
            
        if isinstance(field_def, models.CharField):
            rules['maxlength'] = self.fields[fn].max_length
        elif isinstance(field_def, models.IntegerField):
            rules['digits'] = True
        elif isinstance(field_def, models.FloatField):
            rules['number'] = True
        elif isinstance(field_def, models.URLField):
            rules['url'] = True
        elif isinstance(field_def, models.EmailField):
            rules['email'] = True
        elif isinstance(field_def, models.DateField):
            rules['date'] = True
        rules.update(self.validation_rules.get(fn, {}))
            
        return rules
    
    def is_field_required(self, fn):
        return fn in self.required_fields
    
    @property
    def model_name(self):
        return self.Meta.model.__name__
    
    @property
    def model_name_slug(self):
        if self.slug:
            return self.slug
        s = self.Meta.model.__name__.lower().strip()
        s = re.sub('[^a-z0-9]+', '-', s)
        return s
    
    def get_container_class(self):
        return self.model_name_slug+'-container'
    
    def get_object(self, pk):
        return self.Meta.model.objects.get(pk=pk)
    
    def as_p_complete(self, *args, **kwargs):
        rules = self._validation_rules
        validate_options_str = mark_safe(simplejson.dumps({'rules':rules}))
        
        t = Template(u"""
<form
    id="{{ form_id }}"
    action="{{ action_url }}"
    method="{{ method }}"
    container_class="{{ form.get_container_class }}"
    insert_element="{{ form.insert_element }}"
    {% if delete_id %}delete_id="{{ delete_id }}" delete_model="{{ delete_model }}"{% endif %}
    {% if form.is_multipart %}enctype="multipart/form-data"{% endif %}>
    {{ form.as_p }}
    <p class="submit-button-section {{ submit_button_classes }}">
        <input
            type="submit"
            value="{{ submit_value }}"
            {% if not form.instance.pk %}
            create_button="true"
            ajax-prefix="{{ form.prefix }}"
            ajax-url="{{ form.create_url }}"
            {% endif %}
            onclick="return false;" />
    </p>
    {{ form.render_sub_forms }}
</form>
<script type="text/javascript">
(function($){
    $(document).ready(function(){
        var options = {{ validate_options_str }};
        $('#{{ form_id }}').django_ajax_form(options);
        {{ js_extra }}
    });
})(jQuery);
</script>
""")
        c = Context(dict(
            debug=settings.DEBUG,
            form_id=self.id,
            instance=self.instance,
            action_url=self.get_action_url(),
            method=self.method,
            form=self,
            delete_id=self.instance.pk if self.instance else 0,
            delete_model=self.Meta.model.__name__,
            onchange_callback=self.onchange_callback,
            validate_options_str=validate_options_str,
            submit_value=self.get_submit_value(),
            submit_button_classes=self.submit_button_classes,
            #form_field_names=self.form_field_names,
            form_ajax_setter_names=self.get_ajax_setters(),
            js_extra=mark_safe(u'\n'.join(self.js_extra_rendered)),
        ))
        return t.render(c)
    
    def as_p(self, *args, **kwargs):
        resp = super(BaseAjaxModelForm, self).as_p(*args, **kwargs)
        return resp
    
    def _attr_to_slug(self, attr):
        attr = attr.strip()
        self.__attr_to_slug[attr] = slug = re.sub('[^0-9a-zA-Z_]+', '-', attr)
        self.__slug_to_attr[slug] = attr
        return self.__attr_to_slug[attr]
        
    def slug_to_attr(self, slug):
        return self.__slug_to_attr.get(slug, slug)

    def clean_data(self, data):
        from django.db import models
        cleaned = {}
        valid_field_names = set(self.Meta.fields)
        for _k in data.iterkeys():
            fn = re.sub('^[a-zA-Z0-9\-]+\-', '', _k)
            if fn not in valid_field_names:
                continue
            
            field = self.Meta.model._meta.get_field(fn)
            value = data[_k]
            if isinstance(value, (tuple, list)) and len(value) == 1:
                value = value[0]
            
            if isinstance(field, models.ForeignKey):
                value = field.rel.to.objects.get(pk=value)
            elif isinstance(field, models.BooleanField):
                if value.lower() in ('1', 'true', 'on'):
                    value = True
                else:
                    value = False
                    
            cleaned[fn] = value
        return cleaned

    def create(self, request, **kwargs):
        data = self.clean_data(kwargs)
        obj = self.model.objects.create(**data)
        return obj
#    
#    def read(self, request, obj, *args, **kwargs):
#        try:
#            obj = self.model.objects.get(pk=pk)
#            return obj
#        except self.model.DoesNotExist:
#            return
#    
#    def update(self, request, obj, **kwargs):
#        try:
#            obj = self.model.objects.get(pk=pk)
#            for k, v in kwargs.iteritems():
#                setattr(obj, k, v)
#            obj.save()
#            return obj
#        except self.model.DoesNotExist:
#            return
#    
    def delete(self, request, obj):
        success = False
        delete_model = self.delete_model
        delete_id = self.delete_id
        if self.can_delete:
            try:
                self.model.objects.get(pk=pk).delete()
                obj.delete()
                success = True
            except self.model.DoesNotExist:
                pass
        if success:
            return {
                'success':success,
                'delete_model':delete_model,
                'delete_id':delete_id
            }
        else:
            return {
                'success':success
            }
    
    def has_view_permission(self, request, obj):
        return self.can_view
    
    def has_create_permission(self, request):
        return self.can_create
    
    def has_read_permission(self, request, obj):
        return self.can_read
    
    def has_update_permission(self, request, obj):
        return self.can_update
    
    def has_delete_permission(self, request, obj):
        return self.can_delete
    
    def has_set_permission(self, request, obj, attr):
        for _attr in self.ajax_setters:
            if _attr.startswith('set_'):
                _attr = _attr[4:]
            if _attr == attr:
                return True
        return False
    
    def has_get_permission(self, request, obj, attr):
        for _attr in self.ajax_getters:
            if _attr.startswith('get_'):
                _attr = _attr[4:]
            if _attr == attr:
                return True
        return False
    
    @property
    def view_url(self):
        return '/%s/%s/%s' % (
            C.AJAX_URL_PREFIX,
            self.model_name_slug,
            C.VIEW,
        )
    
    @property
    def create_url(self):
        return '/%s/%s/%s' % (
            C.AJAX_URL_PREFIX,
            self.model_name_slug,
            C.CREATE,
        )
        
    @property
    def read_url(self):
        if not hasattr(self, 'instance') or not self.instance:
            return
        return '/%s/%s/%s/%s' % (
            C.AJAX_URL_PREFIX,
            self.model_name_slug,
            C.READ,
            self.instance.pk,
        )
        
    @property
    def update_url(self):
        if not hasattr(self, 'instance') or not self.instance:
            return
        return '/%s/%s/%s/%s' % (
            C.AJAX_URL_PREFIX,
            self.model_name_slug,
            C.UPDATE,
            self.instance.pk,
        )
        
    @property
    def delete_url(self):
        if not hasattr(self, 'instance') or not self.instance:
            return
        return '/%s/%s/%s/%s' % (
            C.AJAX_URL_PREFIX,
            self.model_name_slug,
            C.DELETE,
            self.instance.pk,
        )
    
    def get_parent_obj(self, obj):
        """
        Returns the parent object for the parent form associated with
        the current child object and form.
        This must be defined for any form used as a sub-form.
        """
        override
    
    @classmethod
    def get_child_queryset(cls, parent_obj):
        return cls.Meta.model.objects.filter(**{cls.fk:parent_obj})
        
    def view(self, request, obj):
        """
        Returns the partial view markup for the object and form.
        """
        if self.parent_form_cls:
            obj = self.get_parent_obj(obj)
            form = self.parent_form_cls(instance=obj)
        else:
            form = type(self)(instance=obj)
        return unicode(form)
    
    def get_url(self, attr):
        if not hasattr(self, 'instance') or not self.instance:
            return
        return '/%s/%s/%s/%s/%s' % (
            C.AJAX_URL_PREFIX,
            self.model_name_slug,
            C.GET,
            attr,
            self.instance.pk,
        )
    
    def set_url(self, attr):
        if not hasattr(self, 'instance') or not self.instance:
            return
        return '/%s/%s/%s/%s/%s' % (
            C.AJAX_URL_PREFIX,
            self.model_name_slug,
            C.SET,
            attr,
            self.instance.pk,
        )
    
    def render_sub_forms(self):
        if not self.instance.pk:
            return ''
        try:
            c = []
            for sf, formset in self.sub_formset_instances:
#            for sf in self.sub_forms:
#                q = sf.Meta.model.objects.filter(**{sf.fk:self.instance})
#                
#                formset_cls = modelformset_factory(
#                    sf.Meta.model,
#                    form=sf,
#                    extra=sf.extra,#number of empty forms to show
#                )
#                formset = formset_cls(
#                    queryset=q,
#                    initial=[{sf.fk:self.instance}],
#                    prefix=sf.prefix,
#                )
#                self.sub_formset_instances.append(formset)
                
                t = Template(u"""
{% for form in formset %}{{ form }}{% endfor %}
                """)
                _c = t.render(Context(dict(
                    formset=formset
                )))
                if not c:
                    if hasattr(sf.Meta.model._meta, 'verbose_name_plural'):
                        vn = sf.Meta.model._meta.verbose_name_plural
                    else:
                        vn = sf.Meta.model.__name__+'s'
                    c.append(u'<div class="sub-form-container"><h3 class="sub-forms">%s</h3>' % (vn.title(),))
                c.append(_c + u'</div>')
            return mark_safe(u'<br/>'.join(c))
        except Exception, e:
            if settings.DEBUG:
                return '[%s]' % str(e)

def AjaxSubForm(form_cls, slug, **kwargs):
    """
    Helper method for modifying one form to act as a sub-form to a parent-form.
    """
    id = str(uuid.uuid4()).replace('-', '')
    new_cls = type(
        "_%s_%s" % (form_cls.__name__, id),
        (form_cls,),
        {
            'extra':kwargs.get('extra', 0),
            #'__metaclass__': SubclassTracker,#FIX:is never called?
        },
    )
    new_cls.fk = None
    new_cls.prefix = 'subform-%s' % new_cls.Meta.model.__name__.lower()
    new_cls.slug = slug
    for k, v in kwargs.iteritems():
        setattr(new_cls, k, v)
    register_ajax_cls(new_cls, slug)
    return new_cls
