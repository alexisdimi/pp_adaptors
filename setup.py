import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

dependencies ["git://github.com/alexisdimi/pp_adaptors.git#egg=pp_adaptors"]
    
setuptools.setup(
    name="pp_adaptors",
    version="0.0.1",
    author="Alexis Dimitriadis",
    author_email="alexis.dimitriadis@semantic-web.com",
    description="Extensions and wrappers for pp_api",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/alexisdimi/pp_adaptors",
    packages=["pp_adaptors"],
    license="MIT",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    dependency_links=dependencies,
)
