from django.conf import settings

HORIZONTAL = 'horizontal'
VERTICAL = 'vertical'

VIEW = 'view'
CREATE = 'create'
READ = 'read'
UPDATE = 'update'
DELETE = 'delete'
GET = 'get'
SET = 'set'

CRUD_ACTIONS = (
    CREATE,
    READ,
    UPDATE,
    DELETE,
    GET,
    SET,
    VIEW,
)

AJAX_URL_PREFIX = getattr(settings, 'AJAX_URL_PREFIX', 'ajax')

TOP = 'top'
BOTTOM = 'bottom'
