// Page View, Page Disappear的埋点
function PageTrackFunction(type){
    console.log('LoadFunction')
    var myDate = new Date();
    $.ajax({ 
        type: 'POST',
        url: "/eventTrackingFunc/", // be mindful of url names
        data: {
            'Time': myDate.getTime(),
            'Url': window.location.pathname,
            'Type': type // models.PageCount.PV(type=0) or PD(type=1)
        },
        success: function(response) {
            status = response.status
        }
    })
}

// Mudule Click的埋点
function ModuleTrackFunction(type){
    var myDate = new Date();
    $.ajax({ 
        type: 'POST',
        url: "/eventTrackingFunc/", // be mindful of url names
        data: {
            'Time': myDate.getTime(),
            'Url': window.location.pathname + 'JiJiangJieZhi',
            'Type': type // models.PageCount.PV
        },
        success: function(response) {
            status = response.status
        }
    })
}