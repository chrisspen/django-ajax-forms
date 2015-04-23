
from setuptools import setup, find_packages, Command

import ajax_forms

setup(
    name='django-ajax-forms-mega',
    version=ajax_forms.__version__,
    description='Provides support for doing validation using Ajax(currently with jQuery) using your existing Django forms.',
    author='Chris Spencer',
    author_email='chrisspen@gmail.com',
    url='https://github.com/chrisspen/django-ajax-forms',
    packages=find_packages(),
    package_data = {
        'ajax_forms': [
            'templates/*.*',
            'templates/*/*.*',
            'templates/*/*/*.*',
            'templatetags/*.*',
            'static/*.*',
            'static/*/*.*',
            'static/*/*/*.*',
        ],
    },
    classifiers=[
        'Development Status :: 1 - Alpha',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Framework :: Django',
    ],
    zip_safe=False,
    install_requires=['Django>=1.4'],
)
