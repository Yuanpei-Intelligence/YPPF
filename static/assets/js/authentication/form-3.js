//added by pht
var info = document.getElementById("send_info");
var drop_list = document.getElementById("send_list");
var wechat = document.getElementById("send_wechat");
var email = document.getElementById("send_email");
var submit = document.getElementById("submit_btn");
var form = document.getElementById("form");
var send_captcha = document.getElementById("send_captcha");
var countdown = 60;

function settime() {
	if (countdown == 0) {
		info.removeAttribute("disabled");
		info.innerHTML = "发送到";
		drop_list.removeAttribute("disabled");
		wechat.removeAttribute("disabled");
		wechat.innerHTML = "企业微信";
		email.removeAttribute("disabled");
		email.innerHTML = "个人邮箱";
		countdown = 60;
	} else {
		info.setAttribute("disabled", true);
		info.innerHTML = "重新发送";
		drop_list.setAttribute("disabled", true);
		wechat.setAttribute("disabled", true);
		wechat.innerHTML = "(" + countdown + ")";
		email.setAttribute("disabled", true);
		email.innerHTML = "重新发送(" + countdown + ")";
		countdown--;
		setTimeout("settime()", 1000);
	}
}

if (wechat) {
	wechat.addEventListener('click', function () {
		send_captcha.value = 'wechat';
		form.submit();
		settime();
	});
}
if (email) {
	email.addEventListener('click', function () {
		send_captcha.value = 'email';
		form.submit();
		settime();
	});
}
if (submit) {
	submit.addEventListener('click', function () {
		send_captcha.value = 'no';
	});
}