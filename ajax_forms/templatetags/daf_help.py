import re

from django.core.urlresolvers import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django import template
from django.contrib.admin.templatetags.admin_list import result_headers, result_hidden_fields, results
from django.contrib.admin.views.main import ALL_VAR, PAGE_VAR

from six import string_types

DOT = '.'

register = template.Library()

@register.simple_tag
def next_query_string(request, param_name, param_value, remove=0):
    """
    Returns the current query string with the param name/value pair
    replaced or inserted.
    """
    param_value = str(param_value)
    new_path = request.META['QUERY_STRING']
    remove = int(remove)
    if remove:
        new_path = re.sub(param_name+'=[^&]+', '', new_path)
    elif param_name+'=' in new_path:
        new_path = re.sub(param_name+'=[^&]+', param_name+'='+param_value, new_path)
    else:
        new_path = new_path + '&' + param_name + '=' + param_value
    if new_path.startswith('&'):
        new_path = new_path[1:]
    return new_path

@register.filter
def clean_title(s):
    if hasattr(s, 'no_clean_title'):
        return s
    return str(s).replace('_', ' ').strip().title()

@register.filter
def nbsp(s):
    return str(s).strip().replace(' ', '&nbsp;')

@register.simple_tag
def sort_link(request, param_name, field_name, default='', label=''):
    """
    Creates a list view column sort by link to be used in the list header.

    param_name := the name of the URL GET parameter to use when building URL
    field_name := the Django model field name
    default := the default Django model field name to sort by
    label := the text to use for rendering the column head
    """
    if isinstance(default, string_types):
        order_by = request.GET.get(param_name, default).replace(' ', '').split(',')
        order_by = [_ for _ in order_by if _.strip()]
    else:
        assert isinstance(default, (tuple, list))
        order_by = default

    priority = None
    direction = None
    for i, o in enumerate(order_by):
        if o.startswith('-'):
            _name, _dir = (o[1:], 'asc')
        else:
            _name, _dir = (o, 'desc')
        if _name == field_name:
            priority = i
            direction = _dir
            break

    if not order_by:
        return ''

    new_path = request.META['QUERY_STRING']
    opposite_dir = ''
    if priority is None:
        icon = ''
    else:
        if direction == 'desc':
            icon = '<i class="icon-arrow-up"></i>'
            opposite_dir = '-'
        else:
            icon = '<i class="icon-arrow-down"></i>'
    if param_name+'=' in new_path:
        new_path = re.sub(param_name+'=[^&]+', param_name+'='+opposite_dir+field_name, new_path)
    else:
        new_path = new_path + ('&' if new_path else '') + param_name+'='+opposite_dir+field_name
    return '<a class="sort-link" href="?%(query_string)s">%(name_visible)s %(icon)s</a>' % dict(
        icon=icon,
        name_visible=label or field_name.title().replace('_', ' '),
        query_string=new_path,
    )

@register.simple_tag
def daf_admin_urlname(opts, action, site=None, id=None): # pylint: disable=redefined-builtin
    site_name = site.name if site else 'admin'
    args = None
    if id:
        args = (id,)
    return reverse('%s:%s_%s_%s' % (site_name, opts.app_label, opts.module_name, action), args=args)

@register.inclusion_tag("ajax_forms/change_list_results.html")
def daf_result_list(cl):
    """
    Displays the headers and data list together
    """
    headers = list(result_headers(cl))
    num_sorted_fields = 0
    for h in headers:
        if h['sortable'] and h['sorted']:
            num_sorted_fields += 1
    return {'cl': cl,
            'result_hidden_fields': list(result_hidden_fields(cl)),
            'result_headers': headers,
            'num_sorted_fields': num_sorted_fields,
            'results': list(results(cl))}

@register.inclusion_tag('ajax_forms/actions.html', takes_context=True)
def daf_admin_actions(context):
    """
    Track the number of times the action field has been rendered on the page,
    so we know which value to use.
    """
    context['action_index'] = context.get('action_index', -1) + 1
    #TODO:is there a better place to do this?
    context['action_form'].fields['action'].choices[0] = ('', '--- Select Action ---')
    return context

@register.simple_tag
def paginator_number(cl, i):
    """
    Generates an individual page index link in a paginated list.
    """
    if i == DOT:
        return format_html('<li><a href="?">...</a></li>')
    elif i == cl.page_num:
        return format_html('<li class="active"><a href="?">{0}</a></li> ', i+1)
    return format_html('<li><a href="{0}"{1}>{2}</a></li> ',
                       cl.get_query_string({PAGE_VAR: i}),
                       mark_safe(' class="end"' if i == cl.paginator.num_pages-1 else ''),
                       i+1)

@register.inclusion_tag('ajax_forms/pagination.html')
def pagination(cl):
    """
    Generates the series of links to the pages in a paginated list.
    """
    paginator, page_num = cl.paginator, cl.page_num

    pagination_required = (not cl.show_all or not cl.can_show_all) and cl.multi_page
    if not pagination_required:
        page_range = []
    else:
        ON_EACH_SIDE = 3
        ON_ENDS = 2

        # If there are 10 or fewer pages, display links to every page.
        # Otherwise, do some fancy
        if paginator.num_pages <= 10:
            page_range = range(paginator.num_pages)
        else:
            # Insert "smart" pagination links, so that there are always ON_ENDS
            # links at either end of the list of pages, and there are always
            # ON_EACH_SIDE links at either end of the "current page" link.
            page_range = []
            if page_num > (ON_EACH_SIDE + ON_ENDS):
                page_range.extend(range(0, ON_EACH_SIDE - 1))
                page_range.append(DOT)
                page_range.extend(range(page_num - ON_EACH_SIDE, page_num + 1))
            else:
                page_range.extend(range(0, page_num + 1))
            if page_num < (paginator.num_pages - ON_EACH_SIDE - ON_ENDS - 1):
                page_range.extend(range(page_num + 1, page_num + ON_EACH_SIDE + 1))
                page_range.append(DOT)
                page_range.extend(range(paginator.num_pages - ON_ENDS, paginator.num_pages))
            else:
                page_range.extend(range(page_num + 1, paginator.num_pages))

    need_show_all_link = cl.can_show_all and not cl.show_all and cl.multi_page
    return {
        'cl': cl,
        'paginator': paginator,
        'pagination_required': pagination_required,
        'show_all_url': need_show_all_link and cl.get_query_string({ALL_VAR: ''}),
        'page_range': page_range,
        'ALL_VAR': ALL_VAR,
        '1': 1,
    }

@register.inclusion_tag('ajax_forms/submit_line.html', takes_context=True)
def daf_submit_row(context):
    """
    Displays the row of buttons for delete and save.
    """
    opts = context['opts']
    change = context['change']
    is_popup = context['is_popup']
    save_as = context['save_as']
    site = context['site']
    ctx = {
        'opts': opts,
        'site': site,
        'onclick_attrib': (opts.get_ordered_objects() and change
                            and 'onclick="submitOrderForm();"' or ''),
        'show_delete_link': (not is_popup and context['has_delete_permission']
                              and change and context.get('show_delete', True)),
        'show_save_as_new': not is_popup and change and save_as,
        'show_save_and_add_another': context['has_add_permission'] and
                            not is_popup and (not save_as or context['add']),
        'show_save_and_continue': not is_popup and context['has_change_permission'],
        'is_popup': is_popup,
        'extra_buttons': context.get('extra_buttons'),
        'show_save': True
    }
    if context.get('original') is not None:
        ctx['original'] = context['original']
    return ctx

@register.simple_tag
def daf_render_button_url(btn, *args):
    return btn.get_url(*args)
