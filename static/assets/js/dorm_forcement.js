(function () {
    'use strict';

    const script = document.currentScript;
    const statusUrl = script.dataset.statusUrl;
    const instructionsUrl = script.dataset.instructionsUrl;
    const dormitoryUrl = script.dataset.dormitoryUrl;
    const path = window.location.pathname.replace(/\/$/, '');
    // 签署和首次登录页面先完成各自流程，不弹出阅读提醒。
    if (['/agreement', '/modpw', dormitoryUrl.replace(/\/$/, '')].includes(path)) {
        return;
    }

    fetch(statusUrl, {credentials: 'same-origin', cache: 'no-store'})
        .then(response => {
            if (!response.ok || response.redirected) {
                throw new Error('Unable to check agreement status');
            }
            return response.json();
        })
        .then(state => {
            if (state.needs_dormitory_agreement) {
                window.location.assign(dormitoryUrl);
                return;
            }
            if (state.needs_instructions && path !== instructionsUrl
                    && window.confirm('您尚未查看地下室使用规范，是否现在前往查看？选择取消可稍后查看。')) {
                window.location.assign(instructionsUrl);
            }
        })
        .catch(() => {
            // 检查失败不推断协议已签署；下次进入页面时重试。
            console.error('暂时无法检查协议和规范阅读状态，请刷新页面重试。');
        });
}());
