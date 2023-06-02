YPPF 说明文档
================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:



目录
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

介绍
==================

.. include:: ../../README.md
   :parser: myst_parser.sphinx_

文档说明
==================

可以通过以下方式生成文档：

* 安装sphinx
   ``pip install sphinx``

   * 可能需要安装其它依赖，如``python-docs-theme``等
      ``pip install python-docs-theme``

* 切换到docs目录
   ``cd docs``

* 从项目代码生成文档索引
   ``sphinx-apidoc -e -d 2 -o source/yppf ../``

   * -e 表示每个文件生成独立的文件
   * -d 设置目录树的最大深度

* 产生文档
   ``make html``
