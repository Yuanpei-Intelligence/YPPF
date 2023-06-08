import os

from django.http import HttpResponse

from utils.views import SecureView
from record.log.utils import get_logger
from record.log.config import log_config as CONFIG


class LogShortcut(SecureView):
    '''日志文件快捷呈现

    显示日志文件列表，点击文件名可预览日志内容，GET参数控制末尾行数
    由于安全性考虑，只有管理员可访问
    '''
    http_method_names = ['get']

    def check_perm(self) -> None:
        super().check_perm()
        if not self.request.user.is_superuser:
            self.permission_denied()

    def dispatch_prepare(self, method: str):
        match method:
            case 'get':
                return self.show_log if 'file' in self.request.GET else self.show_files
            case _:
                return self.default_prepare(method)

    def logs(self) -> list[str]:
        return os.listdir(CONFIG.log_dir)

    def display_log_list(self) -> str:
        log_list_html = '<ul>'
        for file in self.logs():
            log_list_html += f'<li><a href="?file={file}">{file}</a></li>'
        log_list_html += '</ul>'
        return log_list_html

    def show_files(self):
        return HttpResponse(f'<h1>Log Files</h1>' + self.display_log_list())

    def show_log(self):
        file = self.request.GET.get('file', '')
        if file not in self.logs():
            return self.permission_denied('Invalid log file selected.')
        try:
            num_lines = int(self.request.GET.get('lines', 100))
        except ValueError:
            return self.permission_denied('Invalid number of lines selected.')

        with open(os.path.join(CONFIG.log_dir, file), 'r', encoding='utf8') as f:
            lines = f.readlines()
        content = ''.join(lines[-num_lines:])
        preview = f'<pre>{content}</pre>'
        html_content = f'<h1>{file} 预览 (后{num_lines}行) </h1>'
        html_content += f'<h2><a href="?">返回</a></h2>'
        return HttpResponse(html_content + preview)

    def get_logger(self):
        return super().get_logger() or get_logger('error')
