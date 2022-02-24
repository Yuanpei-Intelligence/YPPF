//埋点 并获取所需信息 的代码
/******** 目前的效果 *******/
// 在当前页面刷新：PV PD
// 后退：PD
// 前进：PD
// 手机ios退出+等待+重进：发生了一次重新加载，记PV
// 手机ios退出+马上重进：无变化
// 手机ios切换标签页+马上重进：无变化
// 手机ios杀后台：无变化（不记PD）

/******** 问题 *******/
// iOS iPadOS上，使用Safari操作时无法捕获onbeforeunload事件，暂时没找到解决方法
// 所以在数据库中新增了 设备类型 和 浏览器 的相关信息(Platform ExploreName ExploreVer三个字段)
// 如果分析数据需要用到PD，可以排除用 这些设备+浏览器 所得到的记录（如果它们不是很多的话）。因为这类设备上只记录了PV

function getExplore(){
    var Sys = {};  
    var ua = navigator.userAgent.toLowerCase();  
    var s;  
    (s = ua.match(/rv:([\d.]+)\) like gecko/)) ? Sys.ie = s[1] :
    (s = ua.match(/msie ([\d\.]+)/)) ? Sys.ie = s[1] :  
    (s = ua.match(/edge\/([\d\.]+)/)) ? Sys.edge = s[1] :
    (s = ua.match(/firefox\/([\d\.]+)/)) ? Sys.firefox = s[1] :  
    (s = ua.match(/(?:opera|opr).([\d\.]+)/)) ? Sys.opera = s[1] :  
    (s = ua.match(/chrome\/([\d\.]+)/)) ? Sys.chrome = s[1] :  
    (s = ua.match(/version\/([\d\.]+).*safari/)) ? Sys.safari = s[1] : 0;  
     // 根据关系进行判断
    if (Sys.ie) return ('IE ' + Sys.ie);  
    if (Sys.edge) return ('EDGE ' + Sys.edge);
    if (Sys.firefox) return ('Firefox ' + Sys.firefox);  
    if (Sys.chrome) return ('Chrome ' + Sys.chrome);  
    if (Sys.opera) return ('Opera ' + Sys.opera);  
    if (Sys.safari) return ('Safari ' + Sys.safari);
    return 'Unknown Unknown';
}

// Page View, Page Disappear的埋点
function PageTrackFunction(type){
    // alert(getExplore())
    var myDate = new Date();
    $.ajax({ 
        type: 'POST',
        url: "/eventTrackingFunc/", // be mindful of url names
        data: {
            'Time': myDate.getTime(),
            'Url': window.location.pathname,
            'Type': type, // models.PageLog.PV(type=0) or PD(type=1)
            'Platform': navigator.platform,
            'Explore': getExplore()
        },
        success: function(response) {
            status = response.status
        }
    })
}

// Mudule Click的埋点
function ModuleTrackFunction(type, name){
    console.log(name)
    var myDate = new Date();
    $.ajax({ 
        type: 'POST',
        url: "/eventTrackingFunc/", // be mindful of url names
        data: {
            'Time': myDate.getTime(),
            'Url': window.location.pathname,
            'Name': name,
            'Type': type, // models.ModuleLog.MV(type=0) or MC(type=1)
            'Platform': navigator.platform,
            'Explore': getExplore()
        },
        success: function(response) {
            status = response.status
        }
    })
}