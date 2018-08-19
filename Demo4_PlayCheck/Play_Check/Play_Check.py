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
secret_id = '********'   # 请替换为您的 SecretId
secret_key = '********'  # 请替换为您的 SecretKey
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
