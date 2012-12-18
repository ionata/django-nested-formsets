#!/usr/bin/env python
"""
Install django-nested-formsets using setuptools
"""

from nestedformsets import __version__

try:
    from setuptools import setup, find_packages
except ImportError:
    from ez_setup import use_setuptools
    use_setuptools()
    from setuptools import setup, find_packages

setup(
    name='django-nested-formsets',
    version=__version__,
    description='Simple nested formsets in a ModelForm',
    author='Ionata Web Solutions',
    author_email='webmaster@ionata.com.au',
    url='https://bitbucket.org/ionata/django-nested-formsets',

    install_requires=['Django>=1.4', 'ordereddict==1.1'],
    zip_safe=False,

    packages=find_packages(),

    include_package_data=True,
    package_data={ },

    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Framework :: Django',
    ],
)
