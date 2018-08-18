App({
    onLaunch: function() {
        wx.cloud.init({
            traceUser: true //是否要捕捉每个用户的访问记录。设置为true，用户可在管理端看到用户访问记录
            })
    }
});