# -*- coding: utf-8 -*-
from qcloud_cos import CosConfig
from qcloud_cos import CosS3Client
from qcloud_cos import CosServiceError

from datetime import datetime
from time import time
import re
import operator
import pymysql.cursors
import logging

# MySql数据库
Host='bj-cdb-cj9w3q53.sql.tencentcdb.com'
User='root'
Password='tencent12345'
Port= 63054
DB=u'SCF_Demo'

# COS
appid = ********  # 请替换为您的 APPID
secret_id = u'********'  # 请替换为您的 SecretId
secret_key = u'********'  # 请替换为您的 SecretKey
region = u'ap-beijing'
token = ''

config = CosConfig(Secret_id=secret_id, Secret_key=secret_key, Region=region, Token=token)
client = CosS3Client(config)
logger = logging.getLogger()


def main_handler(event, context):
    # Authentication Information
    print("Start Request {}", datetime.fromtimestamp(time()).strftime('%Y-%m-%d %H:%M:%S'))

    # Start downloading from COS
    for record in event['Records']:
        try:
            bucket = record['cos']['cosBucket']['name'] + '-' + str(appid)
            key = record['cos']['cosObject']['key']
            key = key.replace('/' + str(appid) + '/' + record['cos']['cosBucket']['name'] + '/', '', 1)
            download_path = '/tmp/{}'.format(key)
            print("Key is " + key)
            print("Get from [%s] to download file [%s]" % (bucket, key))
            try:
                response = client.get_object(Bucket=bucket, Key=key, )
                response['Body'].get_stream_to_file(download_path)
            except CosServiceError as e:
                print(e.get_error_code())
                print(e.get_error_msg())
                print(e.get_resource_location())
                return "Download log fail"
            logger.info("Download file [%s] Success" % key)
        except Exception as e:
            print(e)
            raise e
            return "Access COS Fail"

        print("Start analyzing data {}", datetime.fromtimestamp(time()).strftime('%Y-%m-%d %H:%M:%S'))
        urlList = {}
        statuelist = {}
        terminalList = {}
        timeList = {"24/May/2018 10:00-10:30": 0, "24/May/2018 10:30-11:00": 0}

        fileObject = open(download_path, 'rU')
        try:
            for line in fileObject:
                # Count URL
                URLstart = re.search("GET", line)
                URLend = re.search("mp4", line)
                if URLstart and URLend:
                    url = line[URLstart.end() + 1: URLend.end()]
                    if url in urlList:
                        urlList[url] += 1
                    else:
                        urlList[url] = 1

                # Count Statue code
                Statuestart = re.search("HTTP/1.1", line)
                if Statuestart:
                    StatueCode = line[Statuestart.end() + 2: Statuestart.end() + 5]
                    if StatueCode in statuelist:
                        statuelist[StatueCode] += 1
                    else:
                        statuelist[StatueCode] = 1

                # Count Terminal Device
                Terminalstart = re.search("\"-\"", line)
                TerminalEnd = re.search("\"-\" \"-\"", line)
                if Terminalstart and TerminalEnd:
                    terminal = line[Terminalstart.end() + 2: TerminalEnd.start() - 2]
                    if terminal in terminalList:
                        terminalList[terminal] += 1
                    else:
                        terminalList[terminal] = 1

                # Count Timelist
                Timestarter = re.search("\[", line)
                if Timestarter:
                    if int(line[Timestarter.end() + 15: Timestarter.end() + 17]) > 30:
                        timeList["24/May/2018 10:30-11:00"] += 1
                    else:
                        timeList["24/May/2018 10:00-10:30"] += 1

        finally:
            fileObject.close()

        # Sort Result according to frequence
        URL_sorted_res = sorted(urlList.items(), key=operator.itemgetter(1), reverse=True)
        Statue_sorted_res = sorted(statuelist.items(), key=operator.itemgetter(1), reverse=True)
        Terminal_sorted_res = sorted(terminalList.items(), key=operator.itemgetter(1), reverse=True)
        Time_sorted_res = sorted(timeList.items(), key=operator.itemgetter(1), reverse=True)

        URLres = []
        Statueres = []
        Terminalres = []
        Timeres = []

        for i in range(3):
            URLres.append(URL_sorted_res[i])
            Statueres.append(Statue_sorted_res[i])
            Terminalres.append(Terminal_sorted_res[i])

        for i in range(2):
            Timeres.append(Time_sorted_res[i])

        print("Analyzing Successfully, Start writing to database {}",
              datetime.fromtimestamp(time()).strftime('%Y-%m-%d %H:%M:%S'))

        connection = pymysql.connect(host=Host,
                                     user=User,
                                     password=Password,
                                     port=Port,
                                     db= DB,
                                     charset='utf8',
                                     cursorclass=pymysql.cursors.DictCursor)

        try:
            with connection.cursor() as cursor:
                # Clean dirty data
                cursor.execute("DROP TABLE IF EXISTS url")
                cursor.execute("DROP TABLE IF EXISTS state")
                cursor.execute("DROP TABLE IF EXISTS terminal")
                cursor.execute("DROP TABLE IF EXISTS time")
                cursor.execute("CREATE TABLE url (URL TEXT NOT NULL, Count INT)")
                cursor.execute("CREATE TABLE state (StateCode TEXT NOT NULL, Count INT)")
                cursor.execute("CREATE TABLE terminal (Terminal TEXT NOT NULL, Count INT)")
                cursor.execute("CREATE TABLE time (Timestatue TEXT NOT NULL, Count INT)")

                sql = "INSERT INTO `url` (`URL`, `Count`) VALUES (%s, %s)"
                for i in range(len(URLres)):
                    cursor.execute(sql, (URLres[i][0], URLres[i][1]))

                sql = "INSERT INTO `state` (`StateCode`, `Count`) VALUES (%s, %s)"
                for i in range(len(Statueres)):
                    cursor.execute(sql, (Statueres[i][0], Statueres[i][1]))

                sql = "INSERT INTO `terminal` (`Terminal`, `Count`) VALUES (%s, %s)"
                for i in range(len(Terminalres)):
                    cursor.execute(sql, (Terminalres[i][0], Terminalres[i][1]))

                sql = "INSERT INTO `time` (`Timestatue`, `Count`) VALUES (%s, %s)"
                for i in range(len(Timeres)):
                    cursor.execute(sql, (Timeres[i][0], Timeres[i][1]))

            connection.commit()

        finally:
            connection.close()

        print("Write to database successfully {}", datetime.fromtimestamp(time()).strftime('%Y-%m-%d %H:%M:%S'))
        return "LogAnalysis Success"

