# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html


# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys
import django
# 项目的根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
os.environ['DJANGO_SETTINGS_MODULE'] = 'boot.settings'
# 启动django命令，这个很重要
django.setup()

project = 'YPPF'
copyright = '2023, pht'
author = 'pht'
version = '5.0'
release = 'latest'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    # 支持Google和Numpy风格的文档注释
    'sphinx.ext.napoleon',
    # 将TODO添加到文档字符串中
    # 'sphinx.ext.todo',
    # 在浏览文档的同时直接查看源代码
    'sphinx.ext.viewcode',
    # 从文档字符串构建文档
    'sphinx.ext.autodoc',
    # 收集文档中的可执行代码，如>>>格式
    # 'sphinx.ext.doctest',
    # 检查文档覆盖率
    # 'sphinx.ext.coverage',
]

templates_path = ['_templates']
exclude_patterns = ['**/*.migrations.*', '**/*.test.*']

language = 'zh_CN'


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# 注意安装python-docs-theme
html_theme = 'python_docs_theme'
html_static_path = ['_static']
