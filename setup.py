import setuptools

with open('README.md', 'r', encoding='utf-8') as fh:
    long_description = fh.read()

setuptools.setup(
    name='synth_mapping_helper',
    author='Tom Chen',
    author_email='tomchen.org@gmail.com',
    description='Example PyPI (Python Package Index) Package',
    keywords='example, pypi, package',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/adosikas/synth_mapping_helper',
    project_urls={
        'Documentation': 'https://github.com/adosikas/synth_mapping_helper',
        'Bug Reports':
        'https://github.com/adosikas/synth_mapping_helper',
        'Source Code': 'https://github.com/adosikas/synth_mapping_helper',
        # 'Funding': '',
        # 'Say Thanks!': '',
    },
    package_dir={'': 'src'},
    packages=setuptools.find_packages(where='src'),
    classifiers=[
        # see https://pypi.org/classifiers/
        'Development Status :: 3 - Alpha',

        'Intended Audience :: End Users/Desktop',
        'Topic :: Artistic Software',
        'Topic :: Games/Entertainment',

        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3 :: Only',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
    install_requires=['numpy', 'pyperclip'],
    extras_require={
        'dev': ['check-manifest'],
        # 'test': ['coverage'],
    },
    # entry_points={
    #     'console_scripts': [  # This can provide executable scripts
    #         'run=synth_mapping_helper:main',
    # You can execute `run` in bash to run `main()` in src/synth_mapping_helper/__init__.py
    #     ],
    # },
)
