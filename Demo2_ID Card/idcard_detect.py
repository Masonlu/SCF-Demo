# -*- coding: utf-8 -*-
import json
import os
import logging
import datetime
from qcloud_cos import CosConfig
from qcloud_cos import CosS3Client
from qcloud_cos import CosServiceError
from qcloud_image import Client
from qcloud_image import CIUrl, CIFile, CIBuffer, CIUrls, CIFiles, CIBuffers
from PIL import Image
import PIL.Image
import sys


logging.basicConfig(level=logging.INFO, stream=sys.stdout)

appid = 1251762227  # 请替换为您的 APPID
secret_id = u'****'  # 请替换为您的 SecretId
secret_key = u'****'  # 请替换为您的 SecretKey
region = u'ap-beijing'
token = ''

config = CosConfig(Secret_id=secret_id, Secret_key=secret_key, Region=region, Token=token)
client = CosS3Client(config)
logger = logging.getLogger()


def resize_image(image_path, resized_path):
    with Image.open(image_path) as image:
        size = float(os.path.getsize(image_path) / 1024 / 1024)
        print size
        if size >= 1:
            image.thumbnail(tuple(x / 2 for x in image.size))
            # image.resize((1024,1024),Image.BILINEAR)
        image.save(resized_path)


def delete_local_file(src):
    logger.info("delete files and folders")
    if os.path.isfile(src):
        try:
            os.remove(src)
        except:
            pass
    elif os.path.isdir(src):
        for item in os.listdir(src):
            itemsrc = os.path.join(src, item)
            delete_file_folder(itemsrc)
        try:
            os.rmdir(src)
        except:
            pass


def main_handler(event, context):
    logger.info("start main handler")
    for record in event['Records']:
        try:
            bucket = record['cos']['cosBucket']['name'] + '-' + str(appid)
            key = record['cos']['cosObject']['key']
            key = key.replace('/' + str(appid) + '/' + record['cos']['cosBucket']['name'] + '/', '', 1)
            download_path = '/tmp/{}'.format(key)
            tmpload_path = '/tmp/resized-{}'.format(key)
            print("Key is " + key)
            print("Get from [%s] to download file [%s]" % (bucket, key))

            # download image from cos
            try:
                response = client.get_object(Bucket=bucket, Key=key, )
                response['Body'].get_stream_to_file(download_path)
            except CosServiceError as e:
                print(e.get_error_code())
                print(e.get_error_msg())
                print(e.get_resource_location())
                return "Fail"

            logger.info("Download file [%s] Success" % key)
            logger.info("Image compress function start")
            starttime = datetime.datetime.now()

            # compress image here
            resize_image(download_path, tmpload_path)
            endtime = datetime.datetime.now()
            logger.info("compress image take " + str((endtime - starttime).microseconds / 1000) + "ms")

            # detect idcard
            print("Start Detection")
            client_card = Client(appid, secret_id, secret_key, record['cos']['cosBucket']['name'])
            client_card.use_http()
            client_card.set_timeout(30)
            res_up = client_card.idcard_detect(CIFiles([tmpload_path]), 0)
            res_down = client_card.idcard_detect(CIFiles([tmpload_path]), 1)
            if res_up["result_list"][0]["code"] == 0 and res_down["result_list"][0]["code"] != 0:
                res_up_print = {
                    "姓名：": res_up["result_list"][0]["data"]["name"],
                    "性别：": res_up["result_list"][0]["data"]["sex"],
                    "出生：": res_up["result_list"][0]["data"]["birth"],
                    "住址：": res_up["result_list"][0]["data"]["address"],
                    "民族：": res_up["result_list"][0]["data"]["nation"],
                    "公民身份证号：": res_up["result_list"][0]["data"]["id"]
                }
                print json.dumps(res_up_print).decode('unicode-escape')
            elif res_up["result_list"][0]["code"] != 0 and res_down["result_list"][0]["code"] == 0:
                res_down_print = {
                    "有效期限：": res_down["result_list"][0]["data"]["valid_date"],
                    "签发机关：": res_down["result_list"][0]["data"]["authority"]
                }
                print json.dumps(res_down_print).decode('unicode-escape')
            else:
                print ("err_message: [%s]" % (res_up["result_list"][0]["message"]))
                print ("err_code: [%s]" % (res_up["result_list"][0]["code"]))
                print ("err_filename: [%s]" % (res_up["result_list"][0]["filename"]))
                delete_local_file(str(download_path))
                delete_local_file(str(tmpload_path))
                return "Detect Fail"

            # delete local file
            delete_local_file(str(download_path))
            delete_local_file(str(tmpload_path))
            return "Success"

        except Exception as e:
            print(e)
            raise e
            return "Detect Fail"

