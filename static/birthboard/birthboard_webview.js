/**
 * 小程序 webview 适配（birthboard 模块共用）。
 *
 * 在微信小程序内嵌 webview 中，把页面里标注了 [data-bb-exit] 的
 * "返回首页"类出口改为返回小程序（wx.miniProgram.navigateBack()）。
 * 普通浏览器 UA 不含 miniProgram，本脚本直接返回，行为保持不变。
 */
(function () {
    var inMiniProgram = navigator.userAgent
        && navigator.userAgent.indexOf('miniProgram') > -1;
    if (!inMiniProgram) return;

    function onReady() {
        if (!window.wx || !wx.miniProgram) return;
        var exits = document.querySelectorAll('[data-bb-exit]');
        for (var i = 0; i < exits.length; i++) {
            exits[i].addEventListener('click', function (e) {
                e.preventDefault();
                wx.miniProgram.navigateBack();
            });
        }
    }

    var s = document.createElement('script');
    s.src = 'https://res.wx.qq.com/open/js/jweixin-1.6.0.js';
    s.onload = onReady;
    document.head.appendChild(s);
})();
