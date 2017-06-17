from __future__ import print_function

import warnings
import json
import re
import uuid
from datetime import date
from collections import namedtuple
from functools import update_wrapper

from django.contrib import admin
from django.views.generic.edit import FormView
from django.db import models
from django.contrib.admin.options import ModelAdmin
from django.views.generic import ListView, TemplateView
from django.db.models import Q
from django.core.exceptions import PermissionDenied
from django.contrib.contenttypes.models import ContentType
from django.template import Context, Template
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.utils.html import escape, escapejs
from django.template.loader import render_to_string
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.safestring import mark_safe
from django.forms.formsets import all_valid
from django.contrib.admin.templatetags.admin_static import static
try:
    from django.contrib.admin.util import unquote, get_deleted_objects, quote
except ImportError:
    from django.contrib.admin.utils import unquote, get_deleted_objects, quote
from django.core.urlresolvers import reverse
from django.forms.models import modelformset_factory
from django.http import Http404
from django import forms
from django.views.decorators.csrf import csrf_exempt
from django.contrib.contenttypes import views as contenttype_views
from django.utils import six
from django.conf import settings
from django.contrib.admin import helpers
from django.db import models, transaction, router
from django.http import HttpResponse, Http404
from django.template.response import SimpleTemplateResponse, TemplateResponse
#from django.views.decorators.http import require_POST
from django.forms.models import modelformset_factory
from django.forms.formsets import BaseFormSet
#from django.forms.forms import BaseForm
from django.forms.models import ModelForm
#from django.views.generic.edit import BaseFormView
from django.views.generic.edit import BaseCreateView
from django.views.generic import FormView
#from django.views.generic.edit import FormMixin
#from django.views.generic import View
#from django.views.generic.edit import ModelFormMixin
from django.views.generic.edit import TemplateResponseMixin
#from django.views.generic.edit import ProcessFormView
#from django.views.generic.edit import SingleObjectMixin
from django.utils.translation import ugettext as _
from django.utils.translation import ungettext
from django.utils.safestring import mark_safe
from django.template import Context, Template
from django.template.loader import render_to_string, get_template
from django.db import models
from django.utils.encoding import force_text
from django.contrib.admin.options import csrf_protect_m, IncorrectLookupParameters
from django.contrib.admin.views.main import SEARCH_VAR
from django.contrib.admin.sites import AdminSite
from django.contrib.admin.options import ModelAdmin
from django.contrib.admin.options import InlineModelAdmin as _InlineModelAdmin
from django.contrib.admin.views.main import ChangeList
from django.core.urlresolvers import reverse

try:
    # Removed in Django 1.6
    from django.conf.urls.defaults import url, include
except ImportError:
    from django.conf.urls import url, include

try:
    # Relocated in Django 1.6
    from django.conf.urls.defaults import patterns
except ImportError:
    # Completely removed in Django 1.10
    try:
        from django.conf.urls import patterns
    except ImportError:
        patterns = None

#from ajax_forms.utils import LazyEncoder
from ajax_forms import constants as C
from ajax_forms.templatetags.daf_help import sort_link, clean_title

from six import string_types, text_type

SLUG_TO_FORM_REGISTRY = {}

FORM_SUBMITTED = "valid_submit"

try:
    # >= Django 1.8
    commit_on_success = transaction.atomic
except AttributeError:
    # < Django 1.8
    commit_on_success = transaction.commit_on_success

# We need to monkeypatch Changelist.url_for_result because it hardcodes
# the sitename...
def _url_for_result(self, result):
    pk = getattr(result, self.pk_attname)
    return reverse('%s:%s_%s_change' % (self.model_admin.admin_site.name,
                                        self.opts.app_label,
                                        self.opts.module_name),
                   args=(quote(pk),),
                   current_app=self.model_admin.admin_site.name)
ChangeList.url_for_result = _url_for_result

class Button(object):

    def __init__(self, **kwargs):
        self.__dict__.update(dict(
            url=None,
            view=None,
            classes='btn btn-default',
            short_description='button',
            help_text=None,
            model_view=None,
        ))
        self.__dict__.update(kwargs)

    def get_url(self, obj=None, get_reverse_args=None):
        url_str = None
        try:
            opts = self.model_view.model._meta
            if self.url:
                url_str = self.url
            elif isinstance(self.view, string_types):
                view_name = self.view.format(
                    site_name=self.model_view.admin_site.name,
                    app_label=opts.app_label,
                    module_name=opts.module_name)
                args = []
                if callable(get_reverse_args):
                    args = get_reverse_args(self.model_view, obj)
                elif obj:
                    args.append(obj.id)
                url_str = reverse(view_name, args=args)
            else:
                raise NotImplementedError
        except Exception as e:
            print('error:', e)
        return url_str

class InlineModelAdmin(_InlineModelAdmin):

    can_add_ajax = False

    can_change_ajax = False

    def get_formset(self, request, obj=None, **kwargs):
        formset = super(InlineModelAdmin, self).get_formset(request, obj=obj, **kwargs)
        return formset

    def get_ajax_channel(self):
        return self.model.__name__.lower()

    def add_view_ajax(self, request, parent_object_id):
        raise NotImplementedError

    def change_view_ajax(self, request, parent_object_id, object_id):
        raise NotImplementedError

class TabularInline(InlineModelAdmin):

    template = 'ajax_forms/edit_inline/tabular.html'

class SiteView(AdminSite):
    """
    Represents a generic Admin-based site that does not require
    staff permissions to use.
    """

    def __init__(self, *args, **kwargs):
        super(SiteView, self).__init__(*args, **kwargs)
        self._path_registry = {} # {model,(app_name, module_name)}

    def register(self, model_or_iterable, admin_class=None, app_name=None, module_name=None, **options):
        super(SiteView, self).register(model_or_iterable=model_or_iterable, admin_class=admin_class, **options)
        app_name = app_name or model_or_iterable._meta.app_label
        module_name = module_name or model_or_iterable._meta.module_name
        self._path_registry[model_or_iterable] = (app_name, module_name)

    def has_permission(self, request):
        """
        Returns True if the given HttpRequest has permission to view
        *at least one* page in the admin site.
        """
        return request.user.is_active

    def get_post_logout_path(self, request):
        """
        Returns the URL to redirect to when the user logs out.
        """
        index_path = reverse('%s:index' % (self.admin_site.name,), current_app=self.name)
        return index_path

    def admin_view(self, view, cacheable=False):
        """
        Decorator to create an admin view attached to this ``AdminSite``. This
        wraps the view and provides permission checking by calling
        ``self.has_permission``.

        You'll want to use this from within ``AdminSite.get_urls()``:

            class MyAdminSite(AdminSite):

                def get_urls(self):
                    from django.conf.urls import patterns, url

                    urls = super(MyAdminSite, self).get_urls()
                    urls += patterns('',
                        url(r'^my_view/$', self.admin_view(some_view))
                    )
                    return urls

        By default, admin_views are marked non-cacheable using the
        ``never_cache`` decorator. If the view can be safely cached, set
        cacheable=True.
        """

        def inner(request, *args, **kwargs):
            if not self.has_permission(request):
                if request.path == reverse('%s:logout' % (self.name,), current_app=self.name):
                    index_path = self.get_post_logout_path()
                    return HttpResponseRedirect(index_path)
                return self.login(request)
            return view(request, *args, **kwargs)

        if not cacheable:
            inner = never_cache(inner)
        # We add csrf_protect here so this function can be used as a utility
        # function for any view, without having to repeat 'csrf_protect'.
        if not getattr(view, 'csrf_exempt', False):
            inner = csrf_protect(inner)
        return update_wrapper(inner, view)

    def get_urls(self):

        if settings.DEBUG:
            self.check_dependencies()

        def wrap(view, cacheable=False):
            def wrapper(*args, **kwargs):
                return self.admin_view(view, cacheable)(*args, **kwargs)
            return update_wrapper(wrapper, view)

        # Admin-site-wide views.
        urlpatterns = patterns('',
            url(r'^$',
                wrap(self.index),
                name='index'),
            url(r'^logout/$',
                wrap(self.logout),
                name='logout'),
            url(r'^password_change/$',
                wrap(self.password_change, cacheable=True),
                name='password_change'),
            url(r'^password_change/done/$',
                wrap(self.password_change_done, cacheable=True),
                name='password_change_done'),
            url(r'^jsi18n/$',
                wrap(self.i18n_javascript, cacheable=True),
                name='jsi18n'),
            url(r'^r/(?P<content_type_id>\d+)/(?P<object_id>.+)/$',
                wrap(contenttype_views.shortcut),
                name='view_on_site'),
            url(r'^(?P<app_label>\w+)/$',
                wrap(self.app_index),
                name='app_list')
        )

        # Add in each model's views.
        for model, model_admin in six.iteritems(self._registry):
            app_label, module_name = self._path_registry[model]
            url_str = r'^%s/%s/' % (app_label, module_name)
            urlpatterns += patterns('',
                url(url_str,
                    include(model_admin.urls))
            )
        return urlpatterns

class ModelView(ModelAdmin):

    change_list_template = 'ajax_forms/change_list.html'

    delete_confirmation_template = 'ajax_forms/delete_confirmation.html'

    delete_selected_confirmation_template = 'ajax_forms/delete_selected_confirmation.html'

    show_add_button = True

    add_form_template = 'ajax_forms/change_form.html'

    change_form_template = 'ajax_forms/change_form.html'

    object_id_kwargs_field = 'object_id'

    save_on_top = True

    verbose_name = None

    verbose_name_plural = None

    add_button_name_template = 'Add %(verbose_name)s'

    app_label = None

    module_name = None

    extra_buttons = []

    @property
    def media(self):
        extra = '' if settings.DEBUG else '.min'
        js = [
            'admin/js/core.js',
            'admin/js/admin/RelatedObjectLookups.js',
            'admin/js/jquery%s.js' % extra,
            'admin/js/jquery.init.js'
        ]
        if self.actions is not None:
            js.append('ajax_forms/js/daf-actions%s.js' % extra)
        if self.prepopulated_fields:
            js.extend(['admin/js/urlify.js', 'admin/js/prepopulate%s.js' % extra])
        if self.opts.get_ordered_objects():
            js.extend(['admin/js/getElementsBySelector.js', 'admin/js/dom-drag.js', 'admin/js/admin/ordering.js'])
        return forms.Media(js=[static(_url) for _url in js])

    def get_title(self, request, obj=None):
        return

    def get_urls(self):

        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)
            return update_wrapper(wrapper, view)

        def wrap_inline(view):
            def wrapper(*args, **kwargs):
                kwargs['modelview'] = self
                return self.admin_site.admin_view(view)(*args, **kwargs)
            return update_wrapper(wrapper, view)

        info = (
            self.app_label or self.model._meta.app_label,
            self.module_name or self.model._meta.module_name,
        )

        urlpatterns = patterns('',
            url(r'^$', wrap(self.changelist_view), name='%s_%s_changelist' % info),
            url(r'^add/$', wrap(self.add_view), name='%s_%s_add' % info),
            url(r'^(.+)/history/$', wrap(self.history_view), name='%s_%s_history' % info),
            url(r'^(.+)/delete/$', wrap(self.delete_view), name='%s_%s_delete' % info),
            url(r'^([0-9]+)/$', wrap(self.change_view), name='%s_%s_change' % info),
        )
        inlines = self.get_inline_instances(request=None)
        for inline in inlines:
            channel_name = inline.get_ajax_channel()
            info = (
                self.app_label or self.model._meta.app_label,
                self.module_name or self.model._meta.module_name,
                channel_name,
            )
            if inline.can_add_ajax:
                name = '%s_%s_%s_add_ajax' % info
                urlpatterns += patterns('',
                    url(r'^([0-9]+)/%s/add/ajax/$' % (channel_name,),
                        wrap_inline(inline.add_view_ajax),
                        name=name)
                )
            if inline.can_change_ajax:
                name = '%s_%s_%s_change_ajax' % info
                urlpatterns += patterns('',
                    url(r'^([0-9]+)/%s/([0-9]+)/ajax/$' % (channel_name,),
                        wrap_inline(inline.change_view_ajax),
                        name=name)
                )

        return urlpatterns

    def get_extra_buttons(self, request, obj=None):
        lst = list()
        for _btn in self.extra_buttons:
            btn = Button(**_btn.__dict__)
            btn.model_view = self
            lst.append(btn)
        return lst

    def get_extra_context(self, request, obj=None):
        context = {}

        opts = self.model._meta

        context['search_var'] = SEARCH_VAR
        context['extra_buttons'] = self.get_extra_buttons(request, obj)

        list_display = self.get_list_display(request)
        list_display_links = self.get_list_display_links(request, list_display)
        list_filter = self.get_list_filter(request)

        context['show_add_button'] = self.show_add_button

        context['verbose_name'] = self.verbose_name or opts.verbose_name
        context['verbose_name_plural'] = self.verbose_name_plural or opts.verbose_name_plural

        context['add_button_name'] = self.add_button_name_template % dict(verbose_name=context['verbose_name'])

        title = self.get_title(request, obj=obj)
        if title:
            context['title'] = title

        # Check actions to see if any are available on this changelist
        actions = self.get_actions(request)
        if actions:
            # Add the action checkboxes if there are any actions available.
            list_display = ['action_checkbox'] +  list(list_display)

        _ChangeList = self.get_changelist(request)
        try:
            cl = _ChangeList(request, self.model, list_display,
                list_display_links, list_filter, self.date_hierarchy,
                self.search_fields, self.list_select_related,
                self.list_per_page, self.list_max_show_all, self.list_editable,
                self)
            context['pagination_required'] = (not cl.show_all or not cl.can_show_all) and cl.multi_page
        except IncorrectLookupParameters as e:
            pass
        return context

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        opts = self.model._meta
        app_label = opts.app_label
        ordered_objects = opts.get_ordered_objects()
        context.update({
            'add': add,
            'change': change,
            'has_add_permission': self.has_add_permission(request),
            'has_change_permission': self.has_change_permission(request, obj),
            'has_delete_permission': self.has_delete_permission(request, obj),
            'has_file_field': True, # FIXME - this should check if form or formsets have a FileField,
            'has_absolute_url': hasattr(self.model, 'get_absolute_url'),
            'ordered_objects': ordered_objects,
            'form_url': form_url,
            'opts': opts,
            'content_type_id': ContentType.objects.get_for_model(self.model).id,
            'save_as': self.save_as,
            'save_on_top': self.save_on_top,
            'site': self.admin_site,
        })
        title = self.get_title(request, obj=obj)
        if title:
            context['title'] = title
        if add and self.add_form_template is not None:
            form_template = self.add_form_template
        else:
            form_template = self.change_form_template

        return TemplateResponse(request, form_template or [
            "admin/%s/%s/change_form.html" % (app_label, opts.object_name.lower()),
            "admin/%s/change_form.html" % app_label,
            "admin/change_form.html"
        ], context, current_app=self.admin_site.name)

    def response_add(self, request, obj, post_url_continue=None):
        """
        Determines the HttpResponse for the add_view stage.
        """
        opts = obj._meta
        pk_value = obj._get_pk_val()

        msg_dict = {'name': force_text(opts.verbose_name), 'obj': force_text(obj)}
        # Here, we distinguish between different save types by checking for
        # the presence of keys in request.POST.
        if "_continue" in request.POST:
            msg = _('The %(name)s "%(obj)s" was added successfully. You may edit it again below.') % msg_dict
            self.message_user(request, msg)
            if post_url_continue is None:
                post_url_continue = reverse('%s:%s_%s_change' %
                                            (self.admin_site.name, opts.app_label, opts.module_name),
                                            args=(pk_value,),
                                            current_app=self.admin_site.name)
            else:
                try:
                    post_url_continue = post_url_continue % pk_value
                    warnings.warn(
                        "The use of string formats for post_url_continue "
                        "in ModelAdmin.response_add() is deprecated. Provide "
                        "a pre-formatted url instead.",
                        DeprecationWarning, stacklevel=2)
                except TypeError:
                    pass
            if "_popup" in request.POST:
                post_url_continue += "?_popup=1"
            return HttpResponseRedirect(post_url_continue)

        if "_popup" in request.POST:
            return HttpResponse(
                '<!DOCTYPE html><html><head><title></title></head><body>'
                '<script type="text/javascript">opener.dismissAddAnotherPopup(window, "%s", "%s");</script></body></html>' % \
                # escape() calls force_text.
                (escape(pk_value), escapejs(obj)))
        elif "_addanother" in request.POST:
            msg = _('The %(name)s "%(obj)s" was added successfully. You may add another %(name)s below.') % msg_dict
            self.message_user(request, msg)
            return HttpResponseRedirect(request.path)
        msg = _('The %(name)s "%(obj)s" was added successfully.') % msg_dict
        self.message_user(request, msg)
        return self.response_post_save_add(request, obj)

    def response_change(self, request, obj):
        """
        Determines the HttpResponse for the change_view stage.
        """
        opts = self.model._meta

        pk_value = obj._get_pk_val()

        msg_dict = {'name': force_text(opts.verbose_name), 'obj': force_text(obj)}
        if "_continue" in request.POST:
            msg = _('The %(name)s "%(obj)s" was changed successfully. You may edit it again below.') % msg_dict
            self.message_user(request, msg)
            if "_popup" in request.REQUEST:
                return HttpResponseRedirect(request.path + "?_popup=1")
            return HttpResponseRedirect(request.path)
        elif "_saveasnew" in request.POST:
            msg = _('The %(name)s "%(obj)s" was added successfully. You may edit it again below.') % msg_dict
            self.message_user(request, msg)
            return HttpResponseRedirect(reverse('%s:%s_%s_change' %
                                        (self.admin_site.name, opts.app_label, opts.module_name),
                                        args=(pk_value,),
                                        current_app=self.admin_site.name))
        elif "_addanother" in request.POST:
            msg = _('The %(name)s "%(obj)s" was changed successfully. You may add another %(name)s below.') % msg_dict
            self.message_user(request, msg)
            return HttpResponseRedirect(reverse('%s:%s_%s_add' %
                                        (self.admin_site.name, opts.app_label, opts.module_name),
                                        current_app=self.admin_site.name))
        msg = _('The %(name)s "%(obj)s" was changed successfully.') % msg_dict
        self.message_user(request, msg)
        return self.response_post_save_change(request, obj)

    def response_post_save_add(self, request, obj):
        """
        Figure out where to redirect after the 'Save' button has been pressed
        when adding a new object.
        """
        opts = self.model._meta
        if self.has_change_permission(request, None):
            post_url = reverse(
                '%s:%s_%s_changelist' % (self.admin_site.name, opts.app_label, opts.module_name),
                current_app=self.admin_site.name)
        else:
            post_url = reverse('%s:index' % self.admin_site.name, current_app=self.admin_site.name)
        return HttpResponseRedirect(post_url)

    def response_post_save_change(self, request, obj):
        """
        Figure out where to redirect after the 'Save' button has been pressed
        when editing an existing object.
        """
        opts = self.model._meta
        if self.has_change_permission(request, None):
            post_url = reverse(
                '%s:%s_%s_changelist' % (self.admin_site.name, opts.app_label, opts.module_name),
                current_app=self.admin_site.name)
        else:
            post_url = reverse('%s:index' % (self.admin_site.name,),
                               current_app=self.admin_site.name)
        return HttpResponseRedirect(post_url)

    def response_action(self, request, queryset):
        """
        Handle an admin action. This is called if a request is POSTed to the
        changelist; it returns an HttpResponse if the action was handled, and
        None otherwise.
        """

        # There can be multiple action forms on the page (at the top
        # and bottom of the change list, for example). Get the action
        # whose button was pushed.
        try:
            action_index = int(request.POST.get('index', 0))
        except ValueError:
            action_index = 0

        # Construct the action form.
        data = request.POST.copy()
        data.pop(helpers.ACTION_CHECKBOX_NAME, None)
        data.pop("index", None)

        # Use the action whose button was pushed
        try:
            data.update({'action': data.getlist('action')[action_index]})
        except IndexError:
            # If we didn't get an action from the chosen form that's invalid
            # POST data, so by deleting action it'll fail the validation check
            # below. So no need to do anything here
            pass

        action_form = self.action_form(data, auto_id=None)
        action_form.fields['action'].choices = self.get_action_choices(request)

        # If the form's valid we can handle the action.
        if action_form.is_valid():
            action = action_form.cleaned_data['action']
            select_across = action_form.cleaned_data['select_across']
            func, name, description = self.get_actions(request)[action]

            # Get the list of selected PKs. If nothing's selected, we can't
            # perform an action on it, so bail. Except we want to perform
            # the action explicitly on all objects.
            selected = request.POST.getlist(helpers.ACTION_CHECKBOX_NAME)
            if not selected and not select_across:
                # Reminder that something needs to be selected or nothing will happen
                msg = _("Items must be selected in order to perform "
                        "actions on them. No items have been changed.")
                self.message_user(request, msg)
                return

            if not select_across:
                # Perform the action only on the selected objects
                queryset = queryset.filter(pk__in=selected)

            response = func(self, request, queryset)

            # Actions may return an HttpResponse, which will be used as the
            # response from the POST. If not, we'll be a good little HTTP
            # citizen and redirect back to the changelist page.
            if isinstance(response, HttpResponse):
                return response
            return HttpResponseRedirect(request.get_full_path())
        else:
            msg = _("No action selected.")
            self.message_user(request, msg)
            return

    def get_add_view_initial(self, request):
        model = self.model
        opts = model._meta
        initial = dict(request.GET.items())
        for k in initial:
            try:
                f = opts.get_field(k)
            except models.FieldDoesNotExist:
                continue
            if isinstance(f, models.ManyToManyField):
                initial[k] = initial[k].split(",")
        return initial

    @csrf_protect_m
    @commit_on_success
    def add_view(self, request, form_url='', extra_context=None):
        "The 'add' admin view for this model."
        model = self.model
        opts = model._meta

        if not self.has_add_permission(request):
            raise PermissionDenied

        _ModelForm = self.get_form(request)
        formsets = []
        inline_instances = self.get_inline_instances(request, None)
        if request.method == 'POST':
            form = _ModelForm(request.POST, request.FILES)
            if form.is_valid():
                new_object = self.save_form(request, form, change=False)
                form_validated = True
            else:
                form_validated = False
                new_object = self.model()
            prefixes = {}
            for FormSet, inline in zip(self.get_formsets(request), inline_instances):
                prefix = FormSet.get_default_prefix()
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
                if prefixes[prefix] != 1 or not prefix:
                    prefix = "%s-%s" % (prefix, prefixes[prefix])
                formset = FormSet(data=request.POST, files=request.FILES,
                                  instance=new_object,
                                  save_as_new="_saveasnew" in request.POST,
                                  prefix=prefix, queryset=inline.queryset(request))
                formsets.append(formset)
            if all_valid(formsets) and form_validated:
                self.save_model(request, new_object, form, False)
                self.save_related(request, form, formsets, False)
                self.log_addition(request, new_object)
                return self.response_add(request, new_object)
        else:
            # Prepare the dict of initial data from the request.
            # We have to special-case M2Ms as a list of comma-separated PKs.
            initial = self.get_add_view_initial(request)
            form = _ModelForm(initial=initial)
            prefixes = {}
            for FormSet, inline in zip(self.get_formsets(request), inline_instances):
                prefix = FormSet.get_default_prefix()
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
                if prefixes[prefix] != 1 or not prefix:
                    prefix = "%s-%s" % (prefix, prefixes[prefix])
                formset = FormSet(instance=self.model(), prefix=prefix,
                                  queryset=inline.queryset(request))
                formsets.append(formset)

        adminForm = helpers.AdminForm(form, list(self.get_fieldsets(request)),
            self.get_prepopulated_fields(request),
            self.get_readonly_fields(request),
            model_admin=self)
        media = self.media + adminForm.media

        inline_admin_formsets = []
        for inline, formset in zip(inline_instances, formsets):
            fieldsets = list(inline.get_fieldsets(request))
            readonly = list(inline.get_readonly_fields(request))
            prepopulated = dict(inline.get_prepopulated_fields(request))
            inline_admin_formset = helpers.InlineAdminFormSet(inline, formset,
                fieldsets, prepopulated, readonly, model_admin=self)
            inline_admin_formsets.append(inline_admin_formset)
            media = media + inline_admin_formset.media

        context = {
            'title': _('Add %s') % force_text(opts.verbose_name),
            'adminform': adminForm,
            'is_popup': "_popup" in request.REQUEST,
            'media': media,
            'inline_admin_formsets': inline_admin_formsets,
            'errors': helpers.AdminErrorList(form, formsets),
            'app_label': opts.app_label,
        }
        context.update(extra_context or {})
        return self.render_change_form(request, context, form_url=form_url, add=True)

    @csrf_protect_m
    @commit_on_success
    def change_view(self, request, object_id, form_url='', extra_context=None):
        "The 'change' admin view for this model."
        model = self.model
        opts = model._meta

        obj = self.get_object(request, unquote(object_id))

        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        if obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') % {'name': force_text(opts.verbose_name), 'key': escape(object_id)})

        if request.method == 'POST' and "_saveasnew" in request.POST:
            return self.add_view(request, form_url=reverse('%s:%s_%s_add' %
                                    (self.admin_site.name, opts.app_label, opts.module_name),
                                    current_app=self.admin_site.name))

        _ModelForm = self.get_form(request, obj)
        formsets = []
        inline_instances = self.get_inline_instances(request, obj)
        if request.method == 'POST':
            form = _ModelForm(request.POST, request.FILES, instance=obj)
            if form.is_valid():
                form_validated = True
                new_object = self.save_form(request, form, change=True)
            else:
                form_validated = False
                new_object = obj
            prefixes = {}
            for FormSet, inline in zip(self.get_formsets(request, new_object), inline_instances):
                prefix = FormSet.get_default_prefix()
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
                if prefixes[prefix] != 1 or not prefix:
                    prefix = "%s-%s" % (prefix, prefixes[prefix])
                formset = FormSet(request.POST, request.FILES,
                                  instance=new_object, prefix=prefix,
                                  queryset=inline.queryset(request))

                formsets.append(formset)

            if all_valid(formsets) and form_validated:
                self.save_model(request, new_object, form, True)
                self.save_related(request, form, formsets, True)
                change_message = self.construct_change_message(request, form, formsets)
                self.log_change(request, new_object, change_message)
                return self.response_change(request, new_object)

        else:
            form = _ModelForm(instance=obj)
            prefixes = {}
            for FormSet, inline in zip(self.get_formsets(request, obj), inline_instances):
                prefix = FormSet.get_default_prefix()
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
                if prefixes[prefix] != 1 or not prefix:
                    prefix = "%s-%s" % (prefix, prefixes[prefix])
                formset = FormSet(instance=obj, prefix=prefix,
                                  queryset=inline.queryset(request))
                formsets.append(formset)

        adminForm = helpers.AdminForm(form, self.get_fieldsets(request, obj),
            self.get_prepopulated_fields(request, obj),
            self.get_readonly_fields(request, obj),
            model_admin=self)
        media = self.media + adminForm.media

        inline_admin_formsets = []
        for inline, formset in zip(inline_instances, formsets):
            fieldsets = list(inline.get_fieldsets(request, obj))
            readonly = list(inline.get_readonly_fields(request, obj))
            prepopulated = dict(inline.get_prepopulated_fields(request, obj))
            inline_admin_formset = helpers.InlineAdminFormSet(inline, formset,
                fieldsets, prepopulated, readonly, model_admin=self)
            inline_admin_formsets.append(inline_admin_formset)
            media = media + inline_admin_formset.media

        context = {
            'title': _('Change %s') % force_text(opts.verbose_name),
            'adminform': adminForm,
            'object_id': object_id,
            'original': obj,
            'is_popup': "_popup" in request.REQUEST,
            'media': media,
            'inline_admin_formsets': inline_admin_formsets,
            'errors': helpers.AdminErrorList(form, formsets),
            'app_label': opts.app_label,
        }

        extra_context = extra_context or {}
        extra_context.update(self.get_extra_context(request, obj))
        context.update(extra_context)
        #print 'eb:',context['extra_buttons']

        return self.render_change_form(
            request, context, change=True, obj=obj, form_url=form_url)

    @csrf_protect_m
    def changelist_view(self, request, extra_context=None):
        """
        The 'change list' admin view for this model.
        """
        from django.contrib.admin.views.main import ERROR_FLAG
        opts = self.model._meta
        app_label = opts.app_label
        if not self.has_change_permission(request, None):
            raise PermissionDenied

        extra_context = extra_context or {}
        extra_context.update(self.get_extra_context(request))

        list_display = self.get_list_display(request)
        list_display_links = self.get_list_display_links(request, list_display)
        list_filter = self.get_list_filter(request)

        # Check actions to see if any are available on this changelist
        actions = self.get_actions(request)
        if actions:
            # Add the action checkboxes if there are any actions available.
            list_display = ['action_checkbox'] +  list(list_display)

        _ChangeList = self.get_changelist(request)
        try:
            cl = _ChangeList(request, self.model, list_display,
                list_display_links, list_filter, self.date_hierarchy,
                self.search_fields, self.list_select_related,
                self.list_per_page, self.list_max_show_all, self.list_editable,
                self)
        except IncorrectLookupParameters:
            # Wacky lookup parameters were given, so redirect to the main
            # changelist page, without parameters, and pass an 'invalid=1'
            # parameter via the query string. If wacky parameters were given
            # and the 'invalid=1' parameter was already in the query string,
            # something is screwed up with the database, so display an error
            # page.
            if ERROR_FLAG in request.GET.keys():
                return SimpleTemplateResponse('admin/invalid_setup.html', {
                    'title': _('Database error'),
                })
            return HttpResponseRedirect(request.path + '?' + ERROR_FLAG + '=1')

        # If the request was POSTed, this might be a bulk action or a bulk
        # edit. Try to look up an action or confirmation first, but if this
        # isn't an action the POST will fall through to the bulk edit check,
        # below.
        action_failed = False
        selected = request.POST.getlist(helpers.ACTION_CHECKBOX_NAME)

        # Actions with no confirmation
        if (actions and request.method == 'POST' and
                'index' in request.POST and '_save' not in request.POST):
            if selected:
                response = self.response_action(request, queryset=cl.get_query_set(request))
                if response:
                    return response
                else:
                    action_failed = True
            else:
                msg = _("Items must be selected in order to perform "
                        "actions on them. No items have been changed.")
                self.message_user(request, msg)
                action_failed = True

        # Actions with confirmation
        if (actions and request.method == 'POST' and
                helpers.ACTION_CHECKBOX_NAME in request.POST and
                'index' not in request.POST and '_save' not in request.POST):
            if selected:
                response = self.response_action(request, queryset=cl.get_query_set(request))
                if response:
                    return response
                else:
                    action_failed = True

        # If we're allowing changelist editing, we need to construct a formset
        # for the changelist given all the fields to be edited. Then we'll
        # use the formset to validate/process POSTed data.
        formset = cl.formset = None

        # Handle POSTed bulk-edit data.
        if (request.method == "POST" and cl.list_editable and
                '_save' in request.POST and not action_failed):
            FormSet = self.get_changelist_formset(request)
            formset = cl.formset = FormSet(request.POST, request.FILES, queryset=cl.result_list)
            if formset.is_valid():
                changecount = 0
                for form in formset.forms:
                    if form.has_changed():
                        obj = self.save_form(request, form, change=True)
                        self.save_model(request, obj, form, change=True)
                        self.save_related(request, form, formsets=[], change=True)
                        change_msg = self.construct_change_message(request, form, None)
                        self.log_change(request, obj, change_msg)
                        changecount += 1

                if changecount:
                    if changecount == 1:
                        name = force_text(opts.verbose_name)
                    else:
                        name = force_text(opts.verbose_name_plural)
                    msg = ungettext("%(count)s %(name)s was changed successfully.",
                                    "%(count)s %(name)s were changed successfully.",
                                    changecount) % {'count': changecount,
                                                    'name': name,
                                                    'obj': force_text(obj)}
                    self.message_user(request, msg)

                return HttpResponseRedirect(request.get_full_path())

        # Handle GET -- construct a formset for display.
        elif cl.list_editable:
            FormSet = self.get_changelist_formset(request)
            formset = cl.formset = FormSet(queryset=cl.result_list)

        # Build the list of media to be used by the formset.
        if formset:
            media = self.media + formset.media
        else:
            media = self.media

        # Build the action form and populate it with available actions.
        if actions:
            action_form = self.action_form(auto_id=None)
            action_form.fields['action'].choices = self.get_action_choices(request)
        else:
            action_form = None

        selection_note_all = ungettext('%(total_count)s selected',
            'All %(total_count)s selected', cl.result_count)
        context = {
            'module_name': force_text(opts.verbose_name_plural),
            'selection_note': _('0 of %(cnt)s selected') % {'cnt': len(cl.result_list)},
            'selection_note_all': selection_note_all % {'total_count': cl.result_count},
            'title': cl.title,
            'site': self.admin_site,
            'is_popup': cl.is_popup,
            'cl': cl,
            'media': media,
            'has_add_permission': self.has_add_permission(request),
            'app_label': app_label,
            'action_form': action_form,
            'actions_on_top': self.actions_on_top,
            'actions_on_bottom': self.actions_on_bottom,
            'actions_selection_counter': self.actions_selection_counter,
        }
        context.update(extra_context or {})

        return TemplateResponse(request, self.change_list_template or [
            'admin/%s/%s/change_list.html' % (app_label, opts.object_name.lower()),
            'admin/%s/change_list.html' % app_label,
            'admin/change_list.html'
        ], context, current_app=self.admin_site.name)

    @csrf_protect_m
    @commit_on_success
    def delete_view(self, request, object_id, extra_context=None):
        "The 'delete' admin view for this model."
        opts = self.model._meta
        app_label = opts.app_label

        obj = self.get_object(request, unquote(object_id))

        if not self.has_delete_permission(request, obj):
            raise PermissionDenied

        if obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') % {'name': force_text(opts.verbose_name), 'key': escape(object_id)})

        using = router.db_for_write(self.model)

        # Populate deleted_objects, a data structure of all related objects that
        # will also be deleted.
        (deleted_objects, perms_needed, protected) = get_deleted_objects(
            [obj], opts, request.user, self.admin_site, using)

        if request.POST: # The user has already confirmed the deletion.
            if perms_needed:
                raise PermissionDenied
            obj_display = force_text(obj)
            self.log_deletion(request, obj, obj_display)
            self.delete_model(request, obj)

            self.message_user(
                request,
                _('The %(name)s "%(obj)s" was deleted successfully.') \
                    % {'name': force_text(opts.verbose_name), 'obj': force_text(obj_display)})

            if not self.has_change_permission(request, None):
                return HttpResponseRedirect(reverse('%s:index' % self.admin_site.name,
                                                    current_app=self.admin_site.name))
            return HttpResponseRedirect(reverse('%s:%s_%s_changelist' %
                                        (self.admin_site.name, opts.app_label, opts.module_name),
                                        current_app=self.admin_site.name))

        object_name = force_text(opts.verbose_name)

        if perms_needed or protected:
            title = _("Cannot delete %(name)s") % {"name": object_name}
        else:
            title = _("Are you sure?")

        context = {
            "title": title,
            "object_name": object_name,
            "object": obj,
            "deleted_objects": deleted_objects,
            "perms_lacking": perms_needed,
            "protected": protected,
            "opts": opts,
            "app_label": app_label,
            "site": self.admin_site,
        }
        context.update(extra_context or {})

        return TemplateResponse(request, self.delete_confirmation_template or [
            "admin/%s/%s/delete_confirmation.html" % (app_label, opts.object_name.lower()),
            "admin/%s/delete_confirmation.html" % app_label,
            "admin/delete_confirmation.html"
        ], context, current_app=self.admin_site.name)


class ValidationError(Exception):
    pass

class BaseAjaxFormSet(BaseFormSet):

    def __unicode__(self):
        _forms = u' '.join([text_type(form) for form in self])
        return mark_safe(u'\n'.join([text_type(self.management_form), _forms]))

@csrf_exempt
def handle_ajax_crud(request, model_name, action, **kwargs):
    """
    Redirects the standard record manipulation URLs to the appropriate form
    method.
    """

    form_cls = SLUG_TO_FORM_REGISTRY.get(model_name)
    if not form_cls:
        if settings.DEBUG:
            raise Exception('No form registered to slug: %s' % (model_name,))
        raise Http404
    if action not in C.CRUD_ACTIONS:
        if settings.DEBUG:
            raise Exception('Invalid action: %s' % (action,))
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
            raise Exception('Permission denied.')
        raise Http404

    action_args = dict((str(k), v) for k, v in action_args.iteritems())
    response = getattr(form, action)(request, **action_args)
    if action == C.VIEW:
        return HttpResponse(
            response,
            content_type='text/html')
    return HttpResponse(
        json.dumps(response),
        content_type='application/json')

@csrf_exempt
def handle_ajax_etter(request, model_name, action, attr_slug, pk):
    """
    Returns single object attributes as JSON.
    """

    form_cls = SLUG_TO_FORM_REGISTRY.get(model_name)
    if not form_cls:
        if settings.DEBUG:
            raise Exception('No form registered to slug: %s' % (model_name,))
        raise Http404
    if action not in (C.SET, C.GET):
        if settings.DEBUG:
            raise Exception('Invalid action: %s' % (action,))
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
            raise Exception('Permission denied.')
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
                    value = bool(value.lower() in ('1', 'true', 'on'))
                setattr(obj, attr_name, value)
                obj.save()
                value = getattr(obj, attr_name)
                if hasattr(value, 'pk'):
                    value = value.pk
    except ValidationError as e:
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
        json.dumps(response),
        content_type='application/json')

class JSONResponseMixin(object):
    def render_to_json_response(self, context):
        return self.get_json_response(self.convert_context_to_json(context))

    def get_json_response(self, content, **httpresponse_kwargs):
        return HttpResponse(content, content_type='application/json', **httpresponse_kwargs)

    def convert_context_to_json(self, context):
        return json.dumps(context)

class RealSubmitMixin(object):
    def is_actual_submit(self):
        if self.request.POST.get('submit') == 'true':
            return True
        return False

class AjaxValidFormMixin(RealSubmitMixin):
    def form_valid(self, form):
        response = None
        if self.is_actual_submit():
            response = self.render_to_json_response({'valid': True, 'submitted': True})
        if self.is_actual_submit() and getattr(self, FORM_SUBMITTED, False):
            self.valid_submit(form)

        if not response:
            return self.render_to_json_response({'valid': True})
        return response

class AjaxValidModelFormMixin(RealSubmitMixin):
    def singleObjectModelToDict(self, object): # pylint: disable=redefined-builtin
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
            return self.render_to_json_response({
                'valid': True,
                'submitted': True,
                'object': self.singleObjectModelToDict(self.object)
            })

        return self.render_to_json_response({'valid': True})

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
            fields = self.request.POST.getlist('fields') + ['__all__']
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

def register_ajax_cls(cls, slug):
    if slug in SLUG_TO_FORM_REGISTRY and SLUG_TO_FORM_REGISTRY[slug] != cls:
        raise Exception(('Form slug conflict! Forms %s and %s ' + \
            'both use the same slug "%s"!') \
                % (cls, SLUG_TO_FORM_REGISTRY[slug], slug))
    SLUG_TO_FORM_REGISTRY[slug] = cls
    for sf in cls.sub_forms:
        sf.parent_form_cls = cls

#class SubclassTracker(ModelForm.__metaclass__):
class SubclassTracker(type(ModelForm)):
    """
    Allows for tracking ajax form subclasses and associating them with
    a unique slug for referencing via ajax calls.
    """
    def __init__(cls, name, bases, dct): # pylint: disable=no-self-argument
        slug = None
        if name != 'BaseAjaxModelForm' and issubclass(cls, BaseAjaxModelForm) and \
                cls.__module__ != forms.models.__name__ and cls.__module__ != forms.widgets.__name__:
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
        self.sub_formset_instances = [] # [(sf, formset)]
        for sf in self.sub_forms:
            #assert isinstance(sf, AjaxSubForm)
            sf.parent_form_cls = type(self)

            fk_name_to_model = dict(
                (f.name, f.rel.to)
                for f in sf.Meta.model._meta.fields
                if isinstance(f, models.ForeignKey)
            ) # {name:model}
            fk_model_to_name = dict((v, k) for k, v in fk_name_to_model.iteritems())
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
        return self.as_p_complete()

    def get_submit_value(self):
        return self.submit_value

    def get_validation_rules(self, fn):
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
        validate_options_str = mark_safe(json.dumps({'rules':rules}))

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
        self.__attr_to_slug[attr] = slug = re.sub(r'[^0-9a-zA-Z_]+', '-', attr)
        self.__slug_to_attr[slug] = attr
        return self.__attr_to_slug[attr]

    def slug_to_attr(self, slug):
        return self.__slug_to_attr.get(slug, slug)

    def clean_data(self, data):
        cleaned = {}
        valid_field_names = set(self.Meta.fields)
        for _k in data.iterkeys():
            fn = re.sub(r'^[a-zA-Z0-9\-]+\-', '', _k)
            if fn not in valid_field_names:
                continue

            field = self.Meta.model._meta.get_field(fn)
            value = data[_k]
            if isinstance(value, (tuple, list)) and len(value) == 1:
                value = value[0]

            if isinstance(field, models.ForeignKey):
                value = field.rel.to.objects.get(pk=value)
            elif isinstance(field, models.BooleanField):
                value = bool(value.lower() in ('1', 'true', 'on'))

            cleaned[fn] = value
        return cleaned

    def create(self, request, **kwargs):
        data = self.clean_data(kwargs)
        obj = self.model.objects.create(**data)
        return obj

    def delete(self, request, obj):
        success = False
        delete_model = self.delete_model
        delete_id = self.delete_id
        if self.can_delete:
            try:
                self.model.objects.get(pk=delete_id).delete()
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
        raise NotImplementedError

    @classmethod
    def get_child_queryset(cls, parent_obj):
        return cls.Meta.model.objects.filter(**{cls.fk:parent_obj})

    def view(self, request, obj):
        """
        Returns the partial view markup for the object and form.
        """
        if self.parent_form_cls:
            obj = self.get_parent_obj(obj)
            form = self.parent_form_cls(instance=obj) # pylint: disable=not-callable
        else:
            form = type(self)(instance=obj)
        return text_type(form)

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
        except Exception as e:
            if settings.DEBUG:
                return '[%s]' % str(e)

def AjaxSubForm(form_cls, slug, **kwargs):
    """
    Helper method for modifying one form to act as a sub-form to a parent-form.
    """
    _id = str(uuid.uuid4()).replace('-', '')
    new_cls = type("_%s_%s" % (form_cls.__name__, _id), form_cls, {'extra': kwargs.get('extra', 0)})
    new_cls.fk = None
    new_cls.prefix = 'subform-%s' % new_cls.Meta.model.__name__.lower()
    new_cls.slug = slug
    for k, v in kwargs.iteritems():
        setattr(new_cls, k, v)
    register_ajax_cls(new_cls, slug)
    return new_cls

class B(object):

    def __init__(self, inline, object, request): # pylint: disable=redefined-builtin
        self.inline = inline
        self.object = object
        self.request = request

    def __iter__(self):
        for fn in self.inline.list_display:
            if hasattr(self.object, fn):
                value = getattr(self.object, fn)
            elif hasattr(self.inline, fn):
                func = getattr(self.inline, fn)
                value = func(request=self.request, obj=self.object)
                if hasattr(func, 'allow_tags') and func.allow_tags:
                    value = mark_safe(value)
            yield value

Action = namedtuple('Action', ['name', 'short_description'])

class A(object):

    def __init__(self, inline, objects, request):
        self.inline = inline
        self.objects = objects
        self.request = request

    def __iter__(self):
        for obj in self.objects:
            yield B(inline=self.inline, object=obj, request=self.request)

class BaseInlineView(object):

    template_name = 'ajax_forms/generic_edit_inline.html'
    template_row_name = 'ajax_forms/generic_edit_inline_row.html'

    model = None

    fk_name = None

    list_display = ()

    collapsable = True

    collapsed = False

    can_add = True

    add_form = None

    can_delete = True

    def get_ajax_channel(self):
        return self.model.__name__.lower()

    def process_ajax_add(self, request, obj):
        raise NotImplementedError

    def get_context_data(self, *args, **kwargs):
        return dict()

    def get_queryset(self, object): # pylint: disable=redefined-builtin
        if not object:
            return
        if self.fk_name:
            return getattr(object, self.fk_name).all()
        matching_fields = [(_.get_accessor_name(), _.model) for _ in object._meta.get_all_related_objects() if _.model == self.model]
        if len(matching_fields) > 1:
            raise Exception('Ambiguous relation. Please specify fk_name.')
        elif not matching_fields:
            raise Exception('No matching field related to model %s.' % (self.model,))
        name = matching_fields[0][0]
        return getattr(object, name).all()

    def get_field_titles(self):
        for fn in self.list_display:
            if hasattr(self, fn) and hasattr(getattr(self, fn), 'short_description'):
                yield getattr(getattr(self, fn), 'short_description')
            elif self.model._meta.get_field(fn) and self.model._meta.get_field(fn).verbose_name:
                yield self.model._meta.get_field(fn).verbose_name
            else:
                yield fn

    def get_title(self, request, obj=None):
        if isinstance(self.model._meta.verbose_name_plural, string_types):
            return self.model._meta.verbose_name_plural
        return self.model.__name__ + 's'

    def get_add_form(self):
        return self.add_form

    def render(self, request, obj):

        data = self.get_context_data()
        data['object'] = obj
        data['request'] = request
        data['object_list'] = self.get_queryset(obj)
        data['field_titles'] = self.get_field_titles()
        data['inline_title'] = self.get_title(request, obj=obj)
        data['object_list'] = A(inline=self, objects=data['object_list'], request=request)
        data['can_add'] = self.can_add
        data['can_delete'] = self.can_delete
        data['add_form'] = self.get_add_form()
        data['form_uuid'] = '_'+str(uuid.uuid4()).replace('-', '')
        data['ajax_channel'] = self.get_ajax_channel()
        data['ajax_url'] = request.path
        content = render_to_string(self.template_name, data)
        return content

class _CommonViewMixin(object):
    """
    Contains variables and methods used by both edit and list views.
    """

    model = None

    model_name = None

    verb = None

    def get_model_name(self):
        if self.model_name:
            s = self.model_name.strip()
        elif self.model:
            if self.model._meta.verbose_name:
                s = self.model._meta.verbose_name.strip()
            else:
                s = type(self.model).__name__.strip()
        else:
            raise NotImplementedError('No model name defined.')
        return s[0].upper() + s[1:]

    def get_verb(self):
        return self.verb

    def get_breadcrumbs(self):
        return [self.get_model_name(), self.get_verb()]

class BaseEditView(TemplateView, _CommonViewMixin):

    template_name = 'ajax_forms/generic_edit.html'

    object_id_kwargs_field = 'object_id'

    form = None

    inlines = ()

    extra_buttons = []

    def get_form(self):
        """
        Returns the form class to instantiate.
        """
        if not self.form:
            raise NotImplementedError("A form class is not defined.")
        return self.form

    def get_form_initial(self):
        return {}

    def get_form_params(self):
        request = self.request
        args = []
        kwargs = dict(
            initial=self.get_form_initial(),
        )
        if request.POST:
            kwargs['data'] = request.POST
            kwargs['files'] = request.FILES
        return args, kwargs

    def get_form_instance(self):
        args, kwargs = self.get_form_params()
        form = self.get_form()(*args, **kwargs) # pylint: disable=not-callable
        return form

    def get_extra_buttons(self):
        lst = list()
        obj = self.get_object()
        for _btn in self.extra_buttons:
            lst.append(_btn)
        return lst

    @property
    def object_id(self):
        return self.kwargs.get(self.object_id_kwargs_field)

    def get_object(self):
        if self.object_id:
            try:
                return self.model.objects.get(id=self.object_id)
            except self.model.DoesNotExist:
                raise Http404

    def get_verb(self):
        if self.object_id:
            return 'Edit'
        return 'Create'

    def get_context_data(self, *args, **kwargs):
        ctx = super(TemplateView, self).get_context_data(*args, **kwargs)
        ctx['breadcrumbs'] = self.get_breadcrumbs()
        ctx['object'] = self.get_object()
        ctx['form'] = self.get_form_instance()
        ctx['inlines'] = []
        ctx['extra_buttons'] = self.get_extra_buttons()
        if ctx['object']:
            ctx['inlines'] = [
                _().render(request=self.request, obj=ctx['object'])
                for _ in self.inlines
            ]
        return ctx

    def process_ajax(self, *args, **kwargs):
        ajax_channel = self.request.REQUEST['ajax_channel']
        for inline in self.inlines:
            obj = inline()
            if obj.get_ajax_channel() == ajax_channel:
                ajax_action = self.request.REQUEST.get('ajax_action', '')
                if ajax_action:
                    return obj.process_ajax_add(request=self.request, obj=self.get_object())
        raise Http404

    def check_access(self):
        """
        Called at the beginning of both get() and post().
        Returns a response object if the remaining of get() and post()
        should be aborted.
        Useful for performing various permission checks that redirect
        to special pages.
        """
        #e.g.
        #if not self.request.user.is_staff:
        #    return HttpResponseRedirect(urlresolvers.reverse('permission_denied'))

    def get(self, *args, **kwargs):
        resp = self.check_access()
        if resp:
            return resp
        if self.request.REQUEST.get('ajax_channel'):
            return self.process_ajax(*args, **kwargs)
        return super(BaseEditView, self).get(*args, **kwargs)

    def post(self, *args, **kwargs):
        resp = self.check_access()
        if resp:
            return resp
        if self.request.REQUEST.get('ajax_channel'):
            return self.process_ajax(*args, **kwargs)
        request = self.request
        form = self.get_form_instance()
        if request.POST and form.is_valid():
            resp = form.save()
            if resp:
                return resp
            return HttpResponseRedirect(request.META.get('HTTP_REFERER'))
        return super(BaseEditView, self).get(*args, **kwargs)

class ColumnField(object):

    def __init__(self, request, name, label, param, default, sort_field):
        self.request = request
        self.name = name
        self.label = label
        self.param = param
        self.default = default
        self.sort_field = sort_field

    def as_link(self):
        if self.sort_field:
            return sort_link(
                self.request,
                param_name=self.param,
                field_name=self.name,
                default=self.default,
                label=clean_title(self.label),
                #label=self.sort_field,
            )
        return clean_title(self.label)


class BaseListView(ListView, _CommonViewMixin):

    paginate_by = 15

    title = None

    search_fields = ()

    list_display = ()

    list_display_links = ()

    list_filter = ()

    filter_templates = {}

    actions = ()

    verb = 'List'

    ordering = []

    ordering_param = 'o'

    @property
    def template_name(self):
        if self.ajax:
            return 'ajax_forms/generic_listview_results.html'
        return 'ajax_forms/generic_listview.html'

    @property
    def q(self):
        return self.request.GET.get('q', '').strip()

    @property
    def ajax(self):
        return self.request.REQUEST.get('ajax', '').lower() in ('1', 'true')

    def get_actions(self):
        return self.actions

    def get_filter_dict(self):
        if hasattr(self, '_filter_dict') and self._filter_dict:
            return self._filter_dict
        d = self._filter_dict = {}
        request = self.request
        for lf_name, lf_query, lf_filter, lf_func, lf_func_value_name, lf_func_order_by in self.list_filter:
            try:
                d[lf_name] = request.GET.get(lf_name, '')
                clean_name = 'clean_%s' % lf_name
                if hasattr(self, clean_name):
                    d[lf_name] = getattr(self, clean_name)(d[lf_name])
            except Exception as e:
                raise
        return d

    def get_queryset_all(self):
        return self.model.objects.all()

    def get_order_by(self):
        ordering = self.request.GET.get('o', ','.join(self.ordering or []))
        ordering = ordering.replace(' ', '').split(',')
        return [_ for _ in ordering if _.strip()]

    def get_queryset(self):
        q = self.get_queryset_all()
        qtext = self.q
        subq = None
        if qtext:
            #TODO:support __search with fulltext index?
            for sf in self.search_fields:
                _subq = Q(**{sf+'__icontains': qtext})
                if subq is None:
                    subq = _subq
                else:
                    subq |= _subq
            if subq:
                q = q.filter(subq)

        filter_dict = self.get_filter_dict()
        for lf_name, lf_query, lf_field, lf_func, lf_func_value_name, lf_func_order_by in self.list_filter:
            v = filter_dict.get(lf_name)
            if v is None or v == '':
                continue
            q = q.filter(**{lf_query: v})

        order_by = self.get_order_by()
        if order_by:
            order_by_helper = [((o[1:], 'desc') if o.startswith('-') else (o, 'asc')) for o in order_by]
            q = q.order_by(*order_by)

        return q

    def get_object_url(self, obj):
        raise NotImplementedError

    def get_single_name(self):
        return self.model.__name__

    def get_plural_name(self):
        return self.model.__name__ + 's'

    def get_context_data(self, *args, **kwargs):

        self._filter_dict = {}

        ctx = super(BaseListView, self).get_context_data(*args, **kwargs)
        ctx['breadcrumbs'] = self.get_breadcrumbs()
        ctx['search_fields'] = self.search_fields
        ctx['list_filter'] = self.list_filter
        ctx['list_display'] = self.list_display
        ctx['filter_templates'] = self.filter_templates
        actions = []
        verbose_name = self.get_single_name().lower()
        verbose_name_plural = self.get_plural_name().lower()
        for action in self.get_actions():
            func = None
            name = None
            if isinstance(action, string_types) and hasattr(self, action):
                func = getattr(self, action)
                name = action
                short_description = getattr(func, 'short_description', action) % dict(verbose_name_plural=verbose_name_plural)
                actions.append(Action(
                    name=action,
                    short_description=short_description,
                ))
        ctx['actions'] = actions
        ctx['q'] = self.q

        queryset = kwargs.get('object_list')
        request = self.request
        filter_dict = self.get_filter_dict()
        page_size = self.get_paginate_by(queryset)

        field_titles = []
        all_model_field_names = set(self.model._meta.get_all_field_names())
        for field in self.list_display:
            if hasattr(self, field) and hasattr(getattr(self, field), 'short_description'):
                kwargs = dict(
                    request=self.request,
                    label=getattr(self, field).short_description,
                    name=field,
                    param=self.ordering_param,
                    default=self.get_order_by(),
                    sort_field=getattr(getattr(self, field), 'order_field', None),
                )
            elif hasattr(self.model, field) and hasattr(getattr(self.model, field), 'short_description'):
                kwargs = dict(
                    request=self.request,
                    label=getattr(self.model, field).short_description,
                    name=field,
                    param=self.ordering_param,
                    default=self.get_order_by(),
                    sort_field=getattr(getattr(self.model, field), 'order_field', None),
                )
            else:
                kwargs = dict(
                    request=self.request,
                    label=field,
                    name=field,
                    param=self.ordering_param,
                    default=self.get_order_by(),
                    sort_field=field if field in all_model_field_names else None,
                )
            field_titles.append(ColumnField(**kwargs))
        ctx['field_titles'] = field_titles

        actions = self.get_actions()
        valid_actions = set(actions)

        list_filter_results = []
        for lf_name, lf_query, lf_filter, lf_func, lf_func_value_name, lf_func_order_by in self.list_filter:
            unique_values = set()
            nq = queryset.values(lf_filter).distinct()
            if lf_func_order_by:
                nq = lf_func_order_by(nq)
            final_label_values = []
            for r in nq:
                if lf_func:
                    unique_key = lf_func(r[lf_filter])
                else:
                    unique_key = r[lf_filter]
                if unique_key in unique_values:
                    continue
                unique_values.add(unique_key)
                final_label_values.append((
                    unique_key,
                    lf_func_value_name(unique_key),
                    str(filter_dict.get(lf_name)) == str(unique_key),
                ))

            list_filter_results.append((lf_name, final_label_values))

        path = '/' + ('/'.join([_ for _ in request.path.split('/') if _.strip()][:-1])) + '/'
        action = request.POST.get('action')
        next_url = None
        if action in valid_actions and hasattr(self, action):
            next_url = request.REQUEST.get('next_url')
            obj_ids = request.REQUEST.get('obj_ids', '')
            action_queryset = queryset
            if obj_ids != 'all':
                obj_ids = map(int, obj_ids.split(','))
                action_queryset = action_queryset.filter(id__in=obj_ids)
            response = getattr(self, action)(request, action_queryset)
            if isinstance(response, HttpResponse):
                return response
            return HttpResponseRedirect(next_url)

        ctx['list_filter_results'] = list_filter_results

        class _B(list):
            """
            Proxy object for each queryset record.
            """

            def __init__(self, *args):
                super(list, self).__init__(*args)
                self.id = None

        class _A(object):
            """
            Wrapper around the queryset to allow easily iterating over fields
            in the template.
            """

            def __init__(self, lv, object_list):
                self.lv = lv
                self.object_list = object_list

            def __iter__(self):
                for obj in self.object_list:
                    o = _B()
                    o.id = obj.id
                    made_link = False
                    for k in self.lv.list_display:
                        if hasattr(self.lv, k):
                            func = getattr(self.lv, k)
                            value = func(obj)
                            if hasattr(func, 'allow_tags') and func.allow_tags:
                                value = mark_safe(value)
                            value = value or ''
                        elif hasattr(obj, k):
                            value = getattr(obj, k)
                        else:
                            raise Exception('Invalid column "%s".' % (k,))

                        if (not self.lv.list_display_links and not made_link) or k in self.lv.list_display_links:
                            made_link = True
                            object_url = self.lv.get_object_url(obj)
                            if object_url:
                                value = mark_safe('<a href="%s">%s</a>' % (object_url, value,))

                        o.append(value)
                    yield o

        ctx['page_obj_iterator'] = _A(self, ctx['page_obj'])
        ctx['list_filter_results'] = list_filter_results
        ctx['next_url'] = next_url
        return ctx

    def base_export_csv(self, request, queryset, columns=None):
        import csv

        response = HttpResponse(mimetype='text/csv')
        response['Content-Disposition'] = \
            'attachment; filename=%s-%i%02i%02i.csv' % (
            self.get_plural_name().lower(),
            date.today().year, date.today().month, date.today().day)

        # Create a CSV writer.
        writer = csv.writer(response)

        # Get the IDs and columns to export.
        columns = columns or self.list_display

        # Write a header row.
        writer.writerow(columns)

        # Write a row for each ID.
        for obj in queryset:
            row = []
            for column in columns:
                value = getattr(obj, column)
                if callable(value):
                    value = value()
                row.append(value)
            writer.writerow(row)

        return response

    #def get(self, *args, **kwargs):
        #return super(BaseListView, self).get(*args, **kwargs)

    def post(self, *args, **kwargs):
        ret = self.get_context_data(object_list=self.get_queryset())
        if ret and isinstance(ret, HttpResponse):
            return ret
        return HttpResponseRedirect(self.request.META.get('HTTP_REFERER'))


class BaseAdminView(FormView):#TemplateView):

    app_label = '(app_label)'
    verbose_name = '(verbose_name)'
    verbose_name_plural = '(verbose_name_plural)'
    title = '(title)'

    fieldsets = []

    #def form_valid(self, form):
        #return super(BaseAdminView, self).form_valid(form)

    def get_context_data(self, *args, **kwargs):
        ctx = super(BaseAdminView, self).get_context_data(*args, **kwargs)

        # Required boilerplate admin template variables.
        ctx['title'] = self.title
        ctx['app_label'] = self.app_label
        ctx['has_change_permission'] = True
        class _C(object):
            pass
        ctx['opts'] = opts = _C()
        opts.app_label = self.app_label
        opts.object_name = self.app_label
        opts.verbose_name = self.verbose_name
        opts.verbose_name_plural = self.verbose_name_plural
        opts.get_ordered_objects = lambda: []
        ctx['change'] = False
        ctx['add'] = 0#True
        ctx['is_popup'] = False
        ctx['has_delete_permission'] = False
        ctx['has_add_permission'] = 0#True
        ctx['has_change_permission'] = 0#True
        ctx['has_absolute_url'] = False
        ctx['save_as'] = False
        ctx['show_save'] = True
        ctx['fieldsets'] = self.fieldsets

        form_class = self.get_form_class()
        form = self.get_form(form_class)

        ctx['form'] = form
        ctx['adminform'] = admin.helpers.AdminForm(
            form=form,
            fieldsets=self.fieldsets,
            prepopulated_fields={})

        return ctx
