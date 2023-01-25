import setuptools

with open('README.md', 'r') as fh:
    long_description = fh.read()

setuptools.setup(
    name='pipeline_manager_backend_communication',
    version='0.1',
    packages=setuptools.find_packages(),
    long_description=long_description,
    include_package_data=True,
    description='General purpose TCP communication backend',
    author='Antmicro Ltd.',
    author_email='contact@antmicro.com',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: OS Independent',
    ]
)
