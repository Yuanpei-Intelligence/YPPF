//modified by wxy
var togglePassword_pw = document.getElementById("toggle-password_pw");
var togglePassword_new = document.getElementById("toggle-password_new");
var formContent = document.getElementsByClassName('form-content')[0]; 
var getFormContentHeight = formContent.clientHeight;

var formImage = document.getElementsByClassName('form-image')[0];
if (formImage) {
	var setFormImageHeight = formImage.style.height = getFormContentHeight + 'px';
}
if (togglePassword_pw) {
	togglePassword_pw.addEventListener('click', function() {
	  var x = document.getElementById("pw")
	  if (x.type === "password") {
	    x.type = "text";
	  } else {
	    x.type = "password";
	  }
	});
}
if (togglePassword_new) {
	togglePassword_new.addEventListener('click', function() {
	  var y = document.getElementById("new")
	  if (y.type === "password") {
		  y.type = "text";
	  }
	  else{
		  y.type = "password";
	  }
	});
}