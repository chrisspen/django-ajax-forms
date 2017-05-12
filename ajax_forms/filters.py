from __future__ import print_function

import re

from django.contrib.admin.filters import FieldListFilter

def TitledListFilter(title, list_filter_class=FieldListFilter):
    """
    Helper function to easily set a custom title on a list filter,
    since the default ModelAdmin.list_filter, and even the ListFilter
    class provides no simple way to do this.
    """
    def init(self, field, request, params, model, model_admin, field_path):

        # Determine the true class at runtime.
        # Ideally, we wouldn't have to do this if admin.validation.validate()
        # didn't force the list filter to be an subclass of FieldListFilter.
        true_cls = None
        for test, cls in list_filter_class._field_list_filters:
            if not test(field):
                continue
            true_cls = cls
            break
        if not true_cls:
            raise Exception('No filter class found.')

        # Automagically transform the current object into an instance of
        # the target class.
        self.__class__ = true_cls
        self.__class__.__init__(self, field, request, params, model, model_admin, field_path)

        # Now, set a specific title. This is what all this nonsense is for.
        self.title = title

    nc = type('TitledFilter_%s' % re.sub('[^a-zA-Z]+', '_', title), (list_filter_class,), {})
    nc.__init__ = init
    return nc
