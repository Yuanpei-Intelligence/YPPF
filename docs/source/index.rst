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

使用说明
==================

* 安装sphinx
  ``pip install sphinx``
* 切换到docs目录
  ``cd docs``
* 从项目代码生成文档索引
  ``sphinx-apidoc -e -d 2 -o source/yppf ../``

  * -e 表示每个文件生成独立的文件
  * -d 设置目录树的最大深度
* 产生文档
  ``make html``
