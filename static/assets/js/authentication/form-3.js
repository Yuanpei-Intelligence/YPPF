//added by pht
var wechat = document.getElementById("send_wechat");
var email = document.getElementById("send_email");
var submit = document.getElementById("submit_btn");
var form = document.getElementById("form");
var send_captcha = document.getElementById("send_captcha");
var countdown = 60;

function settime() {
	if (countdown == 0) {
		wechat.removeAttribute("disabled");
		wechat.innerHTML = "发送微信";
		email.removeAttribute("disabled");
		email.innerHTML = "发送邮件";
		countdown = 60;
	} else {
		wechat.setAttribute("disabled", true);
		wechat.innerHTML = "重新发送(" + countdown + ")";
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