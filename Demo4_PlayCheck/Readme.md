##使用SCF实现定时拨测和发送告警邮件

在本Demo中，我们用到了无服务器云函数 SCF，消息队列 CMQ。其中，云函数 SCF2：PlayCheck 用来进行定时拨测，在拨测失败时写失败信息到 CMQ主题订阅：SendEmail，CMQ 会自动触发云函数 SCF1：SendEmail 来发送邮件。发邮件功能和拨测功能也可以在一个函数中实现，这里想要演示消息队列 CMQ 的使用方法，同时使用 CMQ 可以解耦拨测功能和发邮件功能，便于维护。


###步骤一 创建 CMQ 主题订阅

首先要到消息队列 CMQ 的控制台创建一个 主题订阅，我们可以命名为 SendEmail，并选择“北京”地域。
![](https://main.qcloudimg.com/raw/e9b452f7cdeeb45c2e91e27e1634c5f5.png)

###步骤二 创建云函数 SCF1：SendEmail
在这里，可以直接前往云函数 SCF 的控制台，选择地域“北京”，点击创建函数，命名函数为 SendEmail，函数超时时间修改为5s，内存默认128M即可。点击“下一步”，在“函数代码”的编辑框中，可以直接复制如下代码：
```
# -*- coding: utf8 -*-
import json
import smtplib
from email.mime.text import MIMEText
from email.header import Header

# 第三方 SMTP 服务
mail_host="smtp.qq.com"         #SMTP服务器
mail_user="xxxxxxxxxx"          #用户名，如是QQ邮箱，则为****@qq.com
mail_pass="xxxxxxxxxx"          #口令,登录smtp服务器的口令密码
mail_port=465                   #SMTP服务端口

def sendEmail(fromAddr,toAddr,subject,content):
    sender = fromAddr
    receivers = [toAddr]  # 接收邮件，可设置为您的QQ邮箱或者其他邮箱

    message = MIMEText(content, 'plain', 'utf-8')
    message['From'] = Header(fromAddr, 'utf-8')
    message['To'] =  Header(toAddr, 'utf-8')
    message['Subject'] = Header(subject, 'utf-8')

    try:
        smtpObj = smtplib.SMTP_SSL(mail_host, mail_port)
        smtpObj.login(mail_user,mail_pass)
        smtpObj.sendmail(sender, receivers, message.as_string())
        print("send email success")
        return True
    except smtplib.SMTPException as e:
        print(e)
        print("Error: send email fail")
        return False

def main_handler(event, context):
    if event is not None and "Records" in event.keys():
        if len(event["Records"]) >= 1 and "CMQ" in event["Records"][0].keys():
            cmqMsgStr = event["Records"][0]["CMQ"]["msgBody"]
            cmqMsg = json.loads(cmqMsgStr.replace("'", '"'))
            print cmqMsg
    if sendEmail(cmqMsg['fromAddr'], cmqMsg['toAddr'], cmqMsg['title'], cmqMsg['body']):
        return "send email success"
    else:
        return "send email fail"
```
注意：
参数 mail_host, mail_user, mail_pass, mail_port 需要您根据所期望发送的邮箱或邮件服务器来配置，这里我们以 QQ 邮箱为例，您可以从 [这里](http://service.mail.qq.com/cgi-bin/help?subtype=1&&no=166&&id=28) 了解到如何开启 QQ 邮箱的 SMTP 功能。QQ 邮箱的 SMTP 功能开启后，相应的参数如下。

- mail_host SMTP服务器地址为 "smtp.qq.com"
- mail_user 登录用户名为您的邮箱地址，例如 3473058547@qq.com
- mail_pass 为您在开启 SMTP 功能时设置的密码
- mail_port 为服务器登录端口，由于 QQ 邮箱强制要求SSL登录，端口固定为 465，同时代码中使用 smtplib.SMTP_SSL 创建 SSL 的 SMTP 连接

点击“下一步”，添加触发方式为“CMQ主题订阅触发”，选择步骤一中创建的Topic：SendEmail。先点击“保存”，再点击“完成”。

###步骤三 测试 CMQ 主题和 SendEmail 函数的连通性

完成SendEmail函数创建后，可以先在“函数代码”界面的右上角，点击“测试”，选择“CMQ Topic 事件模板”，并把如下代码复制粘贴到模板的代码框中，点击“测试运行”查看函数运行日志。
其中 “msgBody” 字段内， fromAddr，toAdd的字段，需要根据您自身邮箱地址进行修改，建议可以修改为相同地址，自身邮箱向自身邮箱内发送邮件，以便测试邮件发送的正确性。
```
{
  "Records": [
    {
      "CMQ": {
        "type": "topic",
        "topicOwner":1253970226,
        "topicName": "sendEmailQueue",
        "subscriptionName":"sendEmailFunction",
        "publishTime": "2017-09-25T06:34:00.000Z",
        "msgId": "123345346",
        "requestId":"123345346",
        "msgBody": "{\"fromAddr\":\"*****@qq.com\",\"toAddr\":\"****@qq.com\",\"title\":\"hello from scf & cmq\",\"body\":\"email content to send\"}",
        "msgTag": []
      }
    }
  ]
}
```
测试结果:
![](https://main.qcloudimg.com/raw/a81771fdb342ca9f5353717b1430edb3.png)


测试成功后，可以前往 CMQ 控制台，测试 CMQ 和云函数的联动，如下图所示，点击“发送消息”，在弹出的对话框中，输入如下消息内容，同样 fromAddr，toAdd 的字段需要根据您自身邮箱地址进行修改，然后点击“发送”。
![](https://main.qcloudimg.com/raw/db7c86129af2dffcfc5ffb54fcd21154.png)
```
{
"fromAddr":"*****@qq.com",
"toAddr":"*****@qq.com",
"title":"hello from scf & cmq",
"body":"email content to send"
}
```
最后回到云函数控制台，查看 SendEmail 函数的执行日志，并前往邮箱查看是否收到了邮件。

###步骤四 创建云函数 SCF2：PlayCheck

首先确保在您的系统中已经安装好了python运行环境，然后在本地创建需要放置函数代码的文件夹，[点我](http://cmqsdk-10016717.cossh.myqcloud.com/qc_cmq_python_sdk_V1.0.4.zip?_ga=1.90614994.954607454.1530621311)下载 cmq python sdk，解压后，把文件夹“cmq”复制到刚创建好的函数代码文件夹的根目录下。
注意：请在“cmq”文件夹中找到“cmq_tool.py”文件，打开后，把 log_file="CMQ_python_sdk.log"（如下图所示位置） 修改为 log_file="/tmp/CMQ_python_sdk.log" 并保存。因为本次 Demo 会在 SCF 中使用cmq sdk,而 cmq sdk发送消息时会在本地创建log，所以修改路径为云函数的本地临时存储路径tmp。
![](https://main.qcloudimg.com/raw/1dc09a98586e79660f58b16e8d27a5fe.png)

前往函数代码文件夹的根目录下，创建 python 文件，可以命名为：Play_Check.py，并使用如下示例代码：
```
# -*- coding: utf8 -*-
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

import json
import logging
from cmq.account import Account
from cmq.cmq_exception import *
from cmq.topic import *
import requests

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

#使用 cmq 所需的鉴权信息
secret_id = u'********'   # 请替换为您的 SecretId
secret_key = u'********'  # 请替换为您的 SecretKey
topic_name = "SendEmail"  # 请替换为您的 Topic 名称
endpoint = "http://cmq-topic-bj.api.qcloud.com"

#拨测失败后，告警邮件需要通知的邮箱列表
email_notify_list = {
    "******@qq.com",
    "******@qq.com",
}

#拨测失败后，发出告警邮件的邮箱，请根据您自身设置的邮箱地址进行修改
fromAddr = "******@qq.com"

#拨测地址列表
test_url_list = [
    "http://www.baidu.com",
    "http://www.qq.com",
    "http://wrong.tencent.com",
    "http://unkownurl.com"
]

def Send_CMQ(body):
    # 初始化 my_account
    my_account = Account(endpoint, secret_id, secret_key, debug=True)
    my_account.set_log_level(logging.DEBUG)
    my_topic = my_account.get_topic(topic_name)
    for toAddr in email_notify_list:
        try:
            message = Message()
            sendbody = {
                "fromAddr": fromAddr,
                "toAddr": toAddr,
                "title": u"Please note: PlayCheck Error 拨测地址异常，请检查",
                "body": body
            }
            message.msgBody = json.dumps(sendbody)
            print ("send message [%s] to [%s]" % (body, toAddr))
            my_topic.publish_message(message)

        except CMQExceptionBase, e:
            print "Exception:%s\n" % e


def test_url(url_list):
    errorinfo = []
    for url in url_list:
        resp = None
        try:
            resp = requests.get(url, timeout=3)
            print resp
        except (
        requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout) as e:
            logger.warn("request exceptions:" + str(e))
            errorinfo.append("Access " + url + " timeout")
        else:
            if resp.status_code >= 400:
                logger.warn("response status code fail:" + str(resp.status_code))
                errorinfo.append("Access " + url + " fail, status code:" + str(resp.status_code))
    if len(errorinfo) != 0:
        Send_CMQ("\r\n".join(errorinfo))


def main_handler(event, context):
    test_url(test_url_list)


if __name__ == '__main__':
    main_handler("", "")
```
注意：
- 在使用本段代码的时候，需要把 secret_id、secret_key 替换为您自己的 secret_id和secret_key 后方能使用，您可以在“账号信息”中查看对应信息。另外 topic_name 需要和您在步骤一中创建的 topic 保持一致；
- 还请把 email_notify_list 中的地址替换为您想要通知的邮箱列表，可放置一个，也可放置多个；
- fromAddr 是发出告警邮件的邮箱，还请根据您自身设置的邮箱地址进行修改。

保存后，回到根目录下，对 cmq 文件夹和 Play_Check.py 文件进行打包，注意不是对外层的文件夹打包；另外还需要保证压缩包为zip格式。打包完成后，我们就可以前往云函数 SCF 控制台进行部署。
选择“北京”地域，点击“创建函数”，命名函数为 PlayCheck，函数超时时间修改为5s，内存默认128M即可。点击“下一步”，选择“本地上传zip包”，注意执行方法填写为：Play_Check.main_handler，“保存”后点击“下一步”，触发方式可以先空缺，点击“完成”完成函数部署。

在这里，您也可以直接下载git中提供的项目文件，并打成zip包，通过控制台创建函数并完成部署，注意：
- 打包文件为 Play_Check 文件夹中的 cmq 文件夹和 Play_Check.py 文件
- 在“函数代码”中需修改secret_id、secret_key、topic_name、email_notify_list、fromAddr等字段并保存。

###步骤五 测试函数功能
PlayCheck 函数部署完成后，可以在“函数代码”的右上角点击“测试”，默认使用“Hello World 事件模板”即可，点击“测试运行”查看运行日志，函数正常执行成功之后，您应该可以收到主题为“Please note: PlayCheck Error 拨测地址异常，请检查”的告警邮件。
函数测试成功后，您可以给 PlayCheck 函数添加定时触发器，那么一个完整的播测+邮件告警系统就部署完成了。您也可以根据自身业务的需求，DIY 其他的拨测和告警使用方法。

