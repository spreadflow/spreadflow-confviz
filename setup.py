from setuptools import setup

setup(
    name='SpreadFlowConfviz',
    version='0.0.1',
    description='Configuration visualization tool for SpreadFlow metadata extraction and processing engine',
    author='Lorenz Schori',
    author_email='lo@znerol.ch',
    url='https://github.com/znerol/spreadflow-confviz',
    packages=[
        'spreadflow_confviz',
    ],
    entry_points={
        'console_scripts': [
            'spreadflow-confviz = spreadflow_confviz:main'
        ]
    },
    install_requires=[
        'SpreadFlowCore',
        'graphviz',
    ],
    zip_safe=True,
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Framework :: Twisted',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2.7',
        'Topic :: Multimedia'
    ],
)
