import os
from setuptools import setup, find_packages

import ajax_forms

CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))

def get_reqs(*fns):
    lst = []
    for fn in fns:
        for package in open(os.path.join(CURRENT_DIR, fn)).readlines():
            package = package.strip()
            if not package:
                continue
            lst.append(package.strip())
    return lst

setup(
    name='django-ajax-forms-mega',
    version=ajax_forms.__version__,
    description='Provides support for doing validation using Ajax(currently with jQuery) using your existing Django forms.',
    author='Chris Spencer',
    author_email='chrisspen@gmail.com',
    url='https://github.com/chrisspen/django-ajax-forms',
    packages=find_packages(),
    package_data={
        'ajax_forms': [
            'templates/*.*',
            'templates/*/*.*',
            'templates/*/*/*.*',
            'templatetags/*.*',
            'tests/templates/*.*',
            'static/*.*',
            'static/*/*.*',
            'static/*/*/*.*',
        ],
    },
    #https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Framework :: Django',
    ],
    zip_safe=False,
    install_requires=get_reqs('requirements-min-django.txt', 'requirements.txt'),
    tests_require=get_reqs('requirements-test.txt'),
)
