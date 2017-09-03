#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

with open('README.md') as f:
    readme = f.read()

with open('LICENSE') as f:
    license = f.read()

setup(
    name='peppercornenumerator',
    version='0.5',
    description='Domain-level nucleic acid reaction enumerator)',
    long_description=readme,
    author='Karthik Sarma, Casey Grun, Stefan Badelt and Erik Winfree',
    author_email='winfree@caltech.edu',
    license=license,
    test_suite='tests',
    install_requires=[
        'pyparsing>=1.5.5', 
        'crnsimulator>=0.2',
        'numpy',
        'dsdobjects>=0.1'],
    dependency_links=['http://github.com/DNA-and-Natural-Algorithms-Group/dsdobjects/tarball/master#egg=dsdobjects-0.1'],
    packages=['peppercornenumerator'],
    scripts=['scripts/peppercorn']
)

