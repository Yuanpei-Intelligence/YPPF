// 智慧书院 2025 年度总结 JavaScript
console.log('=== Summary2025.js 已加载 v20260205 ===');

$(document).ready(function () {
  console.log('jQuery ready, 初始化中...');
  // 检查复选框状态
  let isAgreed = false;

  // 初始化 fullPage.js
  $('#app').fullpage({
    scrollingSpeed: 700,
    autoScrolling: true,
    fitToSection: true,
    navigation: true,
    navigationPosition: 'right',
    showActiveTooltip: false,
    slidesNavigation: false,
    controlArrows: false,
    anchors: ['splash', 'home', 'page2', 'page3', 'page4', 'page5', 'page6', 'page7', 'page8', 'page9', 'page10', 'page11', 'page12', 'page13', 'page14', 'page15', 'page16', 'page17'],
    afterLoad: function (anchorLink, index) {
      // 页面加载后的动画逻辑
      console.log('Loaded section:', 'anchor:', anchorLink, 'index:', index);

      // 为当前页面的所有内容框添加淡入动画
      $('.section.active').find('.text-box, .p1-text-box, .p2-text-box, .p3-text-box, .p4-text-box, .p5-text-box, .p6-text-box, .p7-text-box, .p8-text-box, .p9-text-box, .p10-text-box, .p11-text-box, .p12-text-box, .home-title-container').addClass('animate-in');
    },
    onLeave: function (index, nextIndex, direction) {
      console.log('onLeave 触发:', 'from index', index, 'to', nextIndex, 'direction:', direction, 'isAgreed:', isAgreed);
      // 如果在启动页（index=1）且未同意协议，禁止离开
      if (index === 1 && !isAgreed) {
        console.log('❌ 阻止离开启动页 - 未同意协议');
        return false;
      }

      // 离开页面时移除动画类，准备下次进入
      $('.section').eq(index - 1).find('.text-box, .p1-text-box, .p2-text-box, .p3-text-box, .p4-text-box, .p5-text-box, .p6-text-box, .p7-text-box, .p8-text-box, .p9-text-box, .p10-text-box, .p11-text-box, .p12-text-box, .home-title-container').removeClass('animate-in');
    }
  });

  // 初始化音乐播放
  const audio = document.querySelector('audio');

  // 检查复选框状态，控制按钮是否可用
  const splashButton = document.getElementById('splash-start-btn');
  const agreeCheckbox = document.getElementById('agree-rule');
  const urlParams = new URLSearchParams(window.location.search);
  const hasAccepted = urlParams.get('accept') === 'true';

  if (hasAccepted && agreeCheckbox) {
    agreeCheckbox.checked = true;
    if (splashButton) {
      splashButton.classList.add('active');
      // 自动点击开启旅程
      setTimeout(() => {
        splashButton.click();
      }, 500);
    }
    isAgreed = true;
  }

  // 复选框状态改变时更新按钮样式
  agreeCheckbox.addEventListener('change', function () {
    if (this.checked) {
      splashButton.classList.add('active');
      isAgreed = true;
    } else {
      splashButton.classList.remove('active');
      isAgreed = false;
    }
    console.log('复选框状态改变:', 'checked:', this.checked, 'isAgreed:', isAgreed);
  });

  // 点击"开启旅程"按钮
  splashButton.addEventListener('click', function () {
    if (agreeCheckbox.checked) {
      isAgreed = true;

      if (!hasAccepted) {
        const nextParams = new URLSearchParams(window.location.search);
        nextParams.set("accept", "true");
        nextParams.delete("cancel");
        const newUrl = window.location.pathname + '?' + nextParams.toString();
        window.history.replaceState({}, '', newUrl);
      }

      // 播放音乐
      audio.play();
      document.querySelector('#playing').style.display = 'block';
      document.querySelector('#paused').style.display = 'none';

      // 跳转到下一页
      $.fn.fullpage.moveSectionDown();
    }
  });

  // 显示协议
  const ruleLink = document.getElementById('rule-link');
  const ruleDiv = document.getElementById('rule');
  const ruleButton = document.getElementById('rule-button');

  ruleLink.addEventListener('click', function (e) {
    e.preventDefault();
    ruleDiv.classList.add('show');
  });

  ruleButton.addEventListener('click', function () {
    ruleDiv.classList.remove('show');
  });

  // 点击协议外部关闭
  ruleDiv.addEventListener('click', function (e) {
    if (e.target === ruleDiv) {
      ruleDiv.classList.remove('show');
    }
  });
});
