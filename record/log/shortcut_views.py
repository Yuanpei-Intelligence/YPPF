import os

from django.http import HttpResponse

from utils.views import SecureView
from record.log.utils import get_logger
from record.log.config import log_config as CONFIG
from boot.config import GLOBAL_CONFIG


class LogShortcut(SecureView):
    '''日志文件快捷呈现

    显示日志文件列表，点击文件名可预览日志内容，GET参数控制末尾行数。
    出于安全性考虑，只有超级用户或在 config.json 的 debug_stuids 配置中的用户可以访问。
    '''
    http_method_names = ['get']

    def check_perm(self) -> None:
        super().check_perm()
        user = self.request.user
        # Allow superuser or debug_stuids
        if not (user.is_superuser or (hasattr(user, 'username') and user.username in GLOBAL_CONFIG.debug_stuids)):
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
