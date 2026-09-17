from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html


class InstructionsReminderMiddleware:
    """为已登录网站 HTML 统一加载提醒，包括未继承 base 的独立页面。

    不修改 API、下载、流式响应或错误响应；检查脚本先处理住宿协议，
    再提示地下室规范。脚本不依赖 jQuery，可在普通浏览器和 WebView 使用。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (request.method not in ('GET', 'POST') or response.status_code != 200
                or response.streaming
                or not response.get('Content-Type', '').startswith('text/html')
                or response.get('Content-Disposition')
                or response.get('Content-Encoding')
                or not request.user.is_authenticated
                or not request.user.is_valid()
                or request.user.is_newuser):
            return response
        content = response.content
        position = content.lower().rfind(b'</body>')
        if position == -1:
            return response
        script = format_html(
            '<script src="{}" data-status-url="{}" data-instructions-url="{}"'
            ' data-dormitory-url="{}"></script>',
            static('assets/js/dorm_forcement.js'),
            reverse('Appointment:instructions_status'),
            reverse('Appointment:instructions'), '/dormitory/agreement/',
        ).encode(response.charset)
        response.content = content[:position] + script + content[position:]
        if response.has_header('Content-Length'):
            response['Content-Length'] = len(response.content)
        return response
