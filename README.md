django-ajax-form-mixin
======================

[![](https://img.shields.io/pypi/v/django-ajax-forms-mega.svg)](https://pypi.python.org/pypi/django-ajax-forms-mega) [![Build Status](https://img.shields.io/travis/chrisspen/django-ajax-forms.svg?branch=master)](https://travis-ci.org/chrisspen/django-ajax-forms) [![](https://pyup.io/repos/github/chrisspen/django-ajax-forms/shield.svg)](https://pyup.io/repos/github/chrisspen/django-ajax-forms)

Ajax Form Mixin that allows forms and their individual fields to be evaluated through Ajax calls

Development
-----------

To run unittests across multiple Python versions, install:

    sudo add-apt-repository ppa:fkrull/deadsnakes
    sudo apt-get update
    sudo apt-get install python-dev python3-dev python3.3-minimal python3.3-dev python3.4-minimal python3.4-dev python3.5-minimal python3.5-dev python3.6 python3.6-dev

To run all [tests](http://tox.readthedocs.org/en/latest/):

    export TESTNAME=; tox

To run tests for a specific environment (e.g. Python 2.7 with Django 1.11):
    
    export TESTNAME=; tox -e py27-django111

To run a specific test:
    
    export TESTNAME=.testName; tox -e py27-django111

To build and deploy a versioned package to PyPI, run:

    python setup.py sdist
    twine upload dist/<file>
