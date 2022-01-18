# YPPF
启动前请向组长私下要`local_json.json`放在根目录，里面存储了运行的配置文件。如果本文件修改，我们会及时update。

完成后在`mysql`中运行`create database YPPF charset='utf8mb4'`，然后makemigrations+migrate。

静态文件的存储目前存在冗余，更新后会保留唯一一份静态文件，请目前需要操作前端的同学注意。
