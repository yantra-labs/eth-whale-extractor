from setuptools import Extension, setup
from Cython.Build import cythonize

extensions = [
    Extension(
        "eth_whale_extractor.core",
        ["src/eth_whale_extractor/core.py"],
    )
]

setup(ext_modules=cythonize(extensions, compiler_directives={"language_level": "3"}))
