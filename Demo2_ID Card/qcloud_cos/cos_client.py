# -*- coding=utf-8

import requests
import logging
import hashlib
import base64
import os
import sys
import copy
import xml.dom.minidom
import xml.etree.ElementTree
from requests import Request, Session
from datetime import datetime
from six.moves.urllib.parse import quote, unquote
from hashlib import md5
from dicttoxml import dicttoxml
from .streambody import StreamBody
from .xml2dict import Xml2Dict
from .cos_auth import CosS3Auth
from .cos_comm import *
from .cos_threadpool import SimpleThreadPool
from .cos_exception import CosClientError
from .cos_exception import CosServiceError

logger = logging.getLogger(__name__)


class CosConfig(object):
    """config类，保存用户相关信息"""
    def __init__(self, Appid=None, Region=None, SecretId=None, SecretKey=None, Token=None, Scheme=None, Timeout=None,
                 Access_id=None, Access_key=None, Secret_id=None, Secret_key=None, Endpoint=None):
        """初始化，保存用户的信息

        :param Appid(string): 用户APPID.
        :param Region(string): 地域信息.
        :param SecretId(string): 秘钥SecretId.
        :param SecretKey(string): 秘钥SecretKey.
        :param Token(string): 临时秘钥使用的token.
        :param Scheme(string): http/https
        :param Timeout(int): http超时时间.
        :param Access_id(string): 秘钥AccessId(兼容).
        :param Access_key(string): 秘钥AccessKey(兼容).
        :param Secret_id(string): 秘钥SecretId(兼容).
        :param Secret_key(string): 秘钥SecretKey(兼容).
        :param Endpoint(string): endpoint.
        """
        self._appid = to_unicode(Appid)
        self._token = to_unicode(Token)
        self._timeout = Timeout
        self._region = Region
        self._endpoint = format_endpoint(Endpoint, Region)

        if Scheme is None:
            Scheme = u'https'
        Scheme = to_unicode(Scheme)
        if(Scheme != u'http' and Scheme != u'https'):
            raise CosClientError('Scheme can be only set to http/https')
        self._scheme = Scheme

        # 兼容(SecretId,SecretKey)以及(AccessId,AccessKey)
        if(SecretId and SecretKey):
            self._secret_id = to_unicode(SecretId)
            self._secret_key = to_unicode(SecretKey)
        elif(Secret_id and Secret_key):
            self._secret_id = to_unicode(Secret_id)
            self._secret_key = to_unicode(Secret_key)
        elif(Access_id and Access_key):
            self._secret_id = to_unicode(Access_id)
            self._secret_key = to_unicode(Access_key)
        else:
            raise CosClientError('SecretId and SecretKey is Required!')

    def uri(self, bucket, path=None, endpoint=None):
        """拼接url

        :param bucket(string): 存储桶名称.
        :param path(string): 请求COS的路径.
        :return(string): 请求COS的URL地址.
        """
        bucket = format_bucket(bucket, self._appid)
        scheme = self._scheme
        if endpoint is None:
            endpoint = self._endpoint

        if path is not None:
            if not path:
                raise CosClientError("Key is required not empty")
            path = to_unicode(path)
            if path[0] == u'/':
                path = path[1:]
            path = quote(to_bytes(path), '/-_.~')
            url = u"{scheme}://{bucket}.{endpoint}/{path}".format(
                scheme=to_unicode(scheme),
                bucket=to_unicode(bucket),
                endpoint=to_unicode(endpoint),
                path=to_unicode(path)
            )
        else:
            url = u"{scheme}://{bucket}.{endpoint}/".format(
                scheme=to_unicode(scheme),
                bucket=to_unicode(bucket),
                endpoint=to_unicode(endpoint)
            )
        return url


class CosS3Client(object):
    """cos客户端类，封装相应请求"""
    def __init__(self, conf, retry=1, session=None):
        """初始化client对象

        :param conf(CosConfig): 用户的配置.
        :param retry(int): 失败重试的次数.
        :param session(object): http session.
        """
        self._conf = conf
        self._retry = retry  # 重试的次数，分片上传时可适当增大
        if session is None:
            self._session = requests.session()
        else:
            self._session = session

    def get_auth(self, Method, Bucket, Key, Expired=300, Headers={}, Params={}):
        """获取签名

        :param Method(string): http method,如'PUT','GET'.
        :param Bucket(string): 存储桶名称.
        :param Key(string): 请求COS的路径.
        :param Expired(int): 签名有效时间,单位为s.
        :param headers(dict): 签名中的http headers.
        :param params(dict): 签名中的http params.
        :return (string): 计算出的V5签名.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 获取上传请求的签名
            auth_string = client.get_auth(
                    Method='PUT'
                    Bucket='bucket',
                    Key='test.txt',
                    Expired=600,
                    Headers={'header1': 'value1'},
                    Params={'param1': 'value1'}
                )
            print (auth_string)
        """
        url = self._conf.uri(bucket=Bucket, path=Key)
        r = Request(Method, url, headers=Headers, params=Params)
        auth = CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, Params, Expired)
        return auth(r).headers['Authorization']

    def send_request(self, method, url, timeout=30, **kwargs):
        """封装request库发起http请求"""
        if self._conf._timeout is not None:  # 用户自定义超时时间
            timeout = self._conf._timeout
        if self._conf._token is not None:
            kwargs['headers']['x-cos-security-token'] = self._conf._token
        kwargs['headers']['User-Agent'] = 'cos-python-sdk-v5.1.5.5'
        kwargs['headers'] = format_values(kwargs['headers'])
        if 'data' in kwargs:
            kwargs['data'] = to_bytes(kwargs['data'])
        try:
            for j in range(self._retry):
                if method == 'POST':
                    res = self._session.post(url, timeout=timeout, **kwargs)
                elif method == 'GET':
                    res = self._session.get(url, timeout=timeout, **kwargs)
                elif method == 'PUT':
                    res = self._session.put(url, timeout=timeout, **kwargs)
                elif method == 'DELETE':
                    res = self._session.delete(url, timeout=timeout, **kwargs)
                elif method == 'HEAD':
                    res = self._session.head(url, timeout=timeout, **kwargs)
                if res.status_code < 400:  # 2xx和3xx都认为是成功的
                    return res
        except Exception as e:  # 捕获requests抛出的如timeout等客户端错误,转化为客户端错误
            logger.exception('url:%s, exception:%s' % (url, str(e)))
            raise CosClientError(str(e))

        if res.status_code >= 400:  # 所有的4XX,5XX都认为是COSServiceError
            if method == 'HEAD' and res.status_code == 404:   # Head 需要处理
                info = dict()
                info['code'] = 'NoSuchResource'
                info['message'] = 'The Resource You Head Not Exist'
                info['resource'] = url
                info['requestid'] = res.headers['x-cos-request-id']
                info['traceid'] = res.headers['x-cos-trace-id']
                logger.error(info)
                raise CosServiceError(method, info, res.status_code)
            else:
                msg = res.text
                if msg == u'':  # 服务器没有返回Error Body时 给出头部的信息
                    msg = res.headers
                logger.error(msg)
                raise CosServiceError(method, msg, res.status_code)

        return None

    #  s3 object interface begin
    def put_object(self, Bucket, Body, Key, EnableMD5=False, **kwargs):
        """单文件上传接口，适用于小文件，最大不得超过5GB

        :param Bucket(string): 存储桶名称.
        :param Body(file|string): 上传的文件内容，类型为文件流或字节流.
        :param Key(string): COS路径.
        :param EnableMD5(bool): 是否需要SDK计算Content-MD5，打开此开关会增加上传耗时.
        :kwargs(dict): 设置上传的headers.
        :return(dict): 上传成功返回的结果，包含ETag等信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 上传本地文件到cos
            with open('test.txt', 'rb') as fp:
                response = client.put_object(
                    Bucket='bucket',
                    Body=fp,
                    Key='test.txt'
                )
                print (response['ETag'])
        """
        check_object_content_length(Body)
        headers = mapped(kwargs)
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("put object, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        Body = deal_with_empty_file_stream(Body)
        if EnableMD5:
            md5_str = get_content_md5(Body)
            if md5_str:
                headers['Content-MD5'] = md5_str
        rt = self.send_request(
            method='PUT',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key),
            data=Body,
            headers=headers)

        response = rt.headers
        return response

    def get_object(self, Bucket, Key, **kwargs):
        """单文件下载接口

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param kwargs(dict): 设置下载的headers.
        :return(dict): 下载成功返回的结果,包含Body对应的StreamBody,可以获取文件流或下载文件到本地.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 下载cos上的文件到本地
            response = client.get_object(
                Bucket='bucket'
                Key='test.txt'
            )
            response['Body'].get_stream_to_file('local_file.txt')
        """
        headers = mapped(kwargs)
        final_headers = {}
        params = {}
        for key in headers:
            if key.startswith("response"):
                params[key] = headers[key]
            else:
                final_headers[key] = headers[key]
        headers = final_headers

        if 'versionId' in headers:
            params['versionId'] = headers['versionId']
            del headers['versionId']
        params = format_values(params)

        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("get object, url=:{url} ,headers=:{headers}, params=:{params}".format(
            url=url,
            headers=headers,
            params=params))
        rt = self.send_request(
                method='GET',
                url=url,
                stream=True,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params),
                params=params,
                headers=headers)

        response = rt.headers
        response['Body'] = StreamBody(rt)

        return response

    def get_presigned_download_url(self, Bucket, Key, Expired=300):
        """生成预签名的下载url

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param Expired(int): 签名过期时间.
        :return(string): 预先签名的下载URL.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 获取预签名文件下载链接
            response = client.get_presigned_download_url(
                Bucket='bucket'
                Key='test.txt'
            )
        """
        url = self._conf.uri(bucket=Bucket, path=Key)
        sign = self.get_auth(Method='GET', Bucket=Bucket, Key=Key, Expired=Expired)
        url = url + '?sign=' + quote(sign)
        return url

    def delete_object(self, Bucket, Key, **kwargs):
        """单文件删除接口

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param kwargs(dict): 设置请求headers.
        :return: dict.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 删除一个文件
            response = client.delete_object(
                Bucket='bucket'
                Key='test.txt'
            )
        """
        headers = mapped(kwargs)
        params = {}
        if 'versionId' in headers:
            params['versionId'] = headers['versionId']
            del headers['versionId']
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("delete object, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
                method='DELETE',
                url=url,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key),
                headers=headers,
                params=params)
        data = rt.headers
        return data

    def delete_objects(self, Bucket, Delete={}, **kwargs):
        """文件批量删除接口,单次最多支持1000个object

        :param Bucket(string): 存储桶名称.
        :param Delete(dict): 批量删除的object信息.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 批量删除的结果.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 批量删除文件
            objects = {
                "Quiet": "true",
                "Object": [
                    {
                        "Key": "file_name1"
                    },
                    {
                        "Key": "file_name2"
                    }
                ]
            }
            response = client.delete_objects(
                Bucket='bucket'
                Delete=objects
            )
        """
        lst = ['<Object>', '</Object>']  # 类型为list的标签
        xml_config = format_xml(data=Delete, root='Delete', lst=lst)
        headers = mapped(kwargs)
        headers['Content-MD5'] = get_md5(xml_config)
        headers['Content-Type'] = 'application/xml'
        params = {'delete': ''}
        params = format_values(params)
        url = self._conf.uri(bucket=Bucket)
        logger.info("delete objects, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='POST',
            url=url,
            data=xml_config,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        data = xml_to_dict(rt.content)
        format_dict(data, ['Deleted', 'Error'])
        return data

    def head_object(self, Bucket, Key, **kwargs):
        """获取文件信息

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 文件的metadata信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 查询文件属性
            response = client.head_object(
                Bucket='bucket'
                Key='test.txt'
            )
        """
        headers = mapped(kwargs)
        params = {}
        if 'versionId' in headers:
            params['versionId'] = headers['versionId']
            del headers['versionId']
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("head object, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='HEAD',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params),
            headers=headers,
            params=params)
        return rt.headers

    def copy_object(self, Bucket, Key, CopySource, CopyStatus='Copy', **kwargs):
        """文件拷贝，文件信息修改

        :param Bucket(string): 存储桶名称.
        :param Key(string): 上传COS路径.
        :param CopySource(dict): 拷贝源,包含Appid,Bucket,Region,Key.
        :param CopyStatus(string): 拷贝状态,可选值'Copy'|'Replaced'.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 拷贝成功的结果.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 文件拷贝
            copy_source = {'Bucket': 'test04-1252448703', 'Key': '/test.txt', 'Region': 'ap-beijing-1'}
            response = client.copy_object(
                Bucket='bucket',
                Key='test.txt',
                CopySource=copy_source
            )
        """
        headers = mapped(kwargs)
        headers['x-cos-copy-source'] = gen_copy_source_url(CopySource)
        if CopyStatus != 'Copy' and CopyStatus != 'Replaced':
            raise CosClientError('CopyStatus must be Copy or Replaced')
        headers['x-cos-metadata-directive'] = CopyStatus
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("copy object, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='PUT',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key),
            headers=headers)
        body = xml_to_dict(rt.content)
        data = rt.headers
        data.update(body)
        return data

    def upload_part_copy(self, Bucket, Key, PartNumber, UploadId, CopySource, CopySourceRange='', **kwargs):
        """拷贝指定文件至分块上传

        :param Bucket(string): 存储桶名称.
        :param Key(string): 上传COS路径.
        :param PartNumber(int): 上传分块的编号.
        :param UploadId(string): 分块上传创建的UploadId.
        :param CopySource(dict): 拷贝源,包含Appid,Bucket,Region,Key.
        :param CopySourceRange(string): 拷贝源的字节范围,bytes=first-last。
        :param kwargs(dict): 设置请求headers.
        :return(dict): 拷贝成功的结果.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 分块上传拷贝分块
            copy_source = {'Bucket': 'test04-1252448703', 'Key': '/test.txt', 'Region': 'ap-beijing-1'}
            response = client.upload_part_copy(
                Bucket='bucket',
                Key='test.txt',
                PartNumber=1,
                UploadId='your uploadid',
                CopySource=copy_source
            )
        """
        headers = mapped(kwargs)
        headers['x-cos-copy-source'] = gen_copy_source_url(CopySource)
        headers['x-cos-copy-source-range'] = CopySourceRange
        params = {'partNumber': PartNumber, 'uploadId': UploadId}
        params = format_values(params)
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("upload part copy, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
                method='PUT',
                url=url,
                headers=headers,
                params=params,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params))
        body = xml_to_dict(rt.content)
        data = rt.headers
        data.update(body)
        return data

    def create_multipart_upload(self, Bucket, Key, **kwargs):
        """创建分块上传，适用于大文件上传

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 初始化分块上传返回的结果，包含UploadId等信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 创建分块上传
            response = client.create_multipart_upload(
                Bucket='bucket',
                Key='test.txt'
            )
        """
        headers = mapped(kwargs)
        params = {'uploads': ''}
        params = format_values(params)
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("create multipart upload, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
                method='POST',
                url=url,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params),
                headers=headers,
                params=params)

        data = xml_to_dict(rt.content)
        return data

    def upload_part(self, Bucket, Key, Body, PartNumber, UploadId, EnableMD5=False, **kwargs):
        """上传分块，单个大小不得超过5GB

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param Body(file|string): 上传分块的内容,可以为文件流或者字节流.
        :param PartNumber(int): 上传分块的编号.
        :param UploadId(string): 分块上传创建的UploadId.
        :param kwargs(dict): 设置请求headers.
        :param EnableMD5(bool): 是否需要SDK计算Content-MD5，打开此开关会增加上传耗时.
        :return(dict): 上传成功返回的结果，包含单个分块ETag等信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 分块上传
            with open('test.txt', 'rb') as fp:
                data = fp.read(1024*1024)
                response = client.upload_part(
                    Bucket='bucket',
                    Body=data,
                    Key='test.txt'
                )
        """
        check_object_content_length(Body)
        headers = mapped(kwargs)
        params = {'partNumber': PartNumber, 'uploadId': UploadId}
        params = format_values(params)
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("upload part, url=:{url} ,headers=:{headers}, params=:{params}".format(
            url=url,
            headers=headers,
            params=params))
        Body = deal_with_empty_file_stream(Body)
        if EnableMD5:
            md5_str = get_content_md5(Body)
            if md5_str:
                headers['Content-MD5'] = md5_str
        rt = self.send_request(
                method='PUT',
                url=url,
                headers=headers,
                params=params,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params),
                data=Body)
        response = dict()
        response['ETag'] = rt.headers['ETag']
        return response

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload={}, **kwargs):
        """完成分片上传,除最后一块分块块大小必须大于等于1MB,否则会返回错误.

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param UploadId(string): 分块上传创建的UploadId.
        :param MultipartUpload(dict): 所有分块的信息,包含Etag和PartNumber.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 上传成功返回的结果，包含整个文件的ETag等信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 分块上传
            response = client.complete_multipart_upload(
                Bucket='bucket',
                Key='multipartfile.txt',
                UploadId='uploadid',
                MultipartUpload={'Part': lst}
            )
        """
        headers = mapped(kwargs)
        params = {'uploadId': UploadId}
        params = format_values(params)
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("create multipart upload, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
                method='POST',
                url=url,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params),
                data=dict_to_xml(MultipartUpload),
                timeout=1200,  # 分片上传大文件的时间比较长，设置为20min
                headers=headers,
                params=params)
        body = xml_to_dict(rt.content)
        data = rt.headers
        data.update(body)
        return data

    def abort_multipart_upload(self, Bucket, Key, UploadId, **kwargs):
        """放弃一个已经存在的分片上传任务，删除所有已经存在的分片.

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param UploadId(string): 分块上传创建的UploadId.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 分块上传
            response = client.abort_multipart_upload(
                Bucket='bucket',
                Key='multipartfile.txt',
                UploadId='uploadid'
            )
        """
        headers = mapped(kwargs)
        params = {'uploadId': UploadId}
        params = format_values(params)
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("abort multipart upload, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
                method='DELETE',
                url=url,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params),
                headers=headers,
                params=params)
        return None

    def list_parts(self, Bucket, Key, UploadId, EncodingType='', MaxParts=1000, PartNumberMarker=0, **kwargs):
        """列出已上传的分片.

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param UploadId(string): 分块上传创建的UploadId.
        :param EncodingType(string): 设置返回结果编码方式,只能设置为url.
        :param MaxParts(int): 设置单次返回最大的分块数量,最大为1000.
        :param PartNumberMarker(int): 设置返回的开始处,从PartNumberMarker下一个分块开始列出.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 分块的相关信息，包括Etag和PartNumber等信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 列出分块
            response = client.list_parts(
                Bucket='bucket',
                Key='multipartfile.txt',
                UploadId='uploadid'
            )
        """
        headers = mapped(kwargs)
        decodeflag = True
        params = {
            'uploadId': UploadId,
            'part-number-marker': PartNumberMarker,
            'max-parts': MaxParts}
        if EncodingType:
            if EncodingType != 'url':
                raise CosClientError('EncodingType must be url')
            params['encoding-type'] = EncodingType
            decodeflag = False
        else:
            params['encoding-type'] = 'url'
        params = format_values(params)
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("list multipart upload parts, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
                method='GET',
                url=url,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params),
                headers=headers,
                params=params)
        data = xml_to_dict(rt.content)
        format_dict(data, ['Part'])
        if decodeflag:
            decode_result(data, ['Key'], [])
        return data

    def put_object_acl(self, Bucket, Key, AccessControlPolicy={}, **kwargs):
        """设置object ACL

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param AccessControlPolicy(dict): 设置object ACL规则.
        :param kwargs(dict): 通过headers来设置ACL.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 设置 object ACL
            response = client.put_object_acl(
                Bucket='bucket',
                Key='multipartfile.txt',
                ACL='public-read',
                GrantRead='id="qcs::cam::uin/123:uin/456",id="qcs::cam::uin/123:uin/123"'
            )
        """
        lst = [  # 类型为list的标签
            '<Grant>',
            '</Grant>']
        xml_config = ""
        if AccessControlPolicy:
            xml_config = format_xml(data=AccessControlPolicy, root='AccessControlPolicy', lst=lst)
        headers = mapped(kwargs)
        params = {'acl': ''}
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("put object acl, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='PUT',
            url=url,
            data=xml_config,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params),
            headers=headers,
            params=params)
        return None

    def get_object_acl(self, Bucket, Key, **kwargs):
        """获取object ACL

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param kwargs(dict): 设置请求headers.
        :return(dict): Object对应的ACL信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 获取object ACL
            response = client.get_object_acl(
                Bucket='bucket',
                Key='multipartfile.txt'
            )
        """
        headers = mapped(kwargs)
        params = {'acl': ''}
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("get object acl, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='GET',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params),
            headers=headers,
            params=params)
        data = xml_to_dict(rt.content, "type", "Type")
        if data['AccessControlList'] is not None and isinstance(data['AccessControlList']['Grant'], dict):
            lst = []
            lst.append(data['AccessControlList']['Grant'])
            data['AccessControlList']['Grant'] = lst
        return data

    def restore_object(self, Bucket, Key, RestoreRequest={}, **kwargs):
        """取回沉降到CAS中的object到COS

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param RestoreRequest: 取回object的属性设置
        :param kwargs(dict): 设置请求headers.
        :return: None.
        """
        params = {'restore': ''}
        headers = mapped(kwargs)
        if 'versionId' in headers:
            params['versionId'] = headers['versionId']
            headers.pop('versionId')
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("restore_object, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        xml_config = format_xml(data=RestoreRequest, root='RestoreRequest')
        rt = self.send_request(
            method='POST',
            url=url,
            data=xml_config,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params),
            headers=headers,
            params=params)
        return None

    # s3 bucket interface begin
    def create_bucket(self, Bucket, **kwargs):
        """创建一个bucket

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 创建bucket
            response = client.create_bucket(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        url = self._conf.uri(bucket=Bucket)
        logger.info("create bucket, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
                method='PUT',
                url=url,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key),
                headers=headers)
        return None

    def delete_bucket(self, Bucket, **kwargs):
        """删除一个bucket，bucket必须为空

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 删除bucket
            response = client.delete_bucket(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        url = self._conf.uri(bucket=Bucket)
        logger.info("delete bucket, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
                method='DELETE',
                url=url,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key),
                headers=headers)
        return None

    def list_objects(self, Bucket, Prefix="", Delimiter="", Marker="", MaxKeys=1000, EncodingType="", **kwargs):
        """获取文件列表

        :param Bucket(string): 存储桶名称.
        :param Prefix(string): 设置匹配文件的前缀.
        :param Delimiter(string): 分隔符.
        :param Marker(string): 从marker开始列出条目.
        :param MaxKeys(int): 设置单次返回最大的数量,最大为1000.
        :param EncodingType(string): 设置返回结果编码方式,只能设置为url.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 文件的相关信息，包括Etag等信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 列出bucket
            response = client.list_objects(
                Bucket='bucket',
                MaxKeys=100,
                Prefix='中文',
                Delimiter='/'
            )
        """
        decodeflag = True  # 是否需要对结果进行decode
        headers = mapped(kwargs)
        url = self._conf.uri(bucket=Bucket)
        logger.info("list objects, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        params = {
            'prefix': Prefix,
            'delimiter': Delimiter,
            'marker': Marker,
            'max-keys': MaxKeys
            }
        if EncodingType:
            if EncodingType != 'url':
                raise CosClientError('EncodingType must be url')
            decodeflag = False  # 用户自己设置了EncodingType不需要去decode
            params['encoding-type'] = EncodingType
        else:
            params['encoding-type'] = 'url'
        params = format_values(params)
        rt = self.send_request(
                method='GET',
                url=url,
                params=params,
                headers=headers,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params))
        data = xml_to_dict(rt.content)
        format_dict(data, ['Contents', 'CommonPrefixes'])
        if decodeflag:
            decode_result(
                data,
                [
                    'Prefix',
                    'Marker',
                    'NextMarker'
                ],
                [
                    ['Contents', 'Key'],
                    ['CommonPrefixes', 'Prefix']
                ]
            )
        return data

    def list_objects_versions(self, Bucket, Prefix="", Delimiter="", KeyMarker="", VersionIdMarker="", MaxKeys=1000, EncodingType="", **kwargs):
        """获取文件列表

        :param Bucket(string): 存储桶名称.
        :param Prefix(string): 设置匹配文件的前缀.
        :param Delimiter(string): 分隔符.
        :param KeyMarker(string): 从KeyMarker指定的Key开始列出条目.
        :param VersionIdMarker(string): 从VersionIdMarker指定的版本开始列出条目.
        :param MaxKeys(int): 设置单次返回最大的数量,最大为1000.
        :param EncodingType(string): 设置返回结果编码方式,只能设置为url.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 文件的相关信息，包括Etag等信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 列出bucket带版本
            response = client.list_objects_versions(
                Bucket='bucket',
                MaxKeys=100,
                Prefix='中文',
                Delimiter='/'
            )
        """
        headers = mapped(kwargs)
        decodeflag = True
        url = self._conf.uri(bucket=Bucket)
        logger.info("list objects versions, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        params = {
            'versions': '',
            'prefix': Prefix,
            'delimiter': Delimiter,
            'key-marker': KeyMarker,
            'version-id-marker': VersionIdMarker,
            'max-keys': MaxKeys
            }
        if EncodingType:
            if EncodingType != 'url':
                raise CosClientError('EncodingType must be url')
            decodeflag = False
            params['encoding-type'] = EncodingType
        else:
            params['encoding-type'] = 'url'
        params = format_values(params)
        rt = self.send_request(
                method='GET',
                url=url,
                params=params,
                headers=headers,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params))
        data = xml_to_dict(rt.content)
        format_dict(data, ['Version', 'DeleteMarker', 'CommonPrefixes'])
        if decodeflag:
            decode_result(
                data,
                [
                    'Prefix',
                    'KeyMarker',
                    'NextKeyMarker',
                    'VersionIdMarker',
                    'NextVersionIdMarker'
                ],
                [
                    ['Version', 'Key'],
                    ['CommonPrefixes', 'Prefix'],
                    ['DeleteMarker', 'Key']
                ]
            )
        return data

    def list_multipart_uploads(self, Bucket, Prefix="", Delimiter="", KeyMarker="", UploadIdMarker="", MaxUploads=1000, EncodingType="", **kwargs):
        """获取Bucket中正在进行的分块上传

        :param Bucket(string): 存储桶名称.
        :param Prefix(string): 设置匹配文件的前缀.
        :param Delimiter(string): 分隔符.
        :param KeyMarker(string): 从KeyMarker指定的Key开始列出条目.
        :param UploadIdMarker(string): 从UploadIdMarker指定的UploadID开始列出条目.
        :param MaxUploads(int): 设置单次返回最大的数量,最大为1000.
        :param EncodingType(string): 设置返回结果编码方式,只能设置为url.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 文件的相关信息，包括Etag等信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 列出所有分块上传
            response = client.list_multipart_uploads(
                Bucket='bucket',
                MaxUploads=100,
                Prefix='中文',
                Delimiter='/'
            )
        """
        headers = mapped(kwargs)
        decodeflag = True
        url = self._conf.uri(bucket=Bucket)
        logger.info("get multipart uploads, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        params = {
            'uploads': '',
            'prefix': Prefix,
            'delimiter': Delimiter,
            'key-marker': KeyMarker,
            'upload-id-marker': UploadIdMarker,
            'max-uploads': MaxUploads
            }
        if EncodingType:
            if EncodingType != 'url':
                raise CosClientError('EncodingType must be url')
            decodeflag = False
            params['encoding-type'] = EncodingType
        else:
            params['encoding-type'] = 'url'
        params = format_values(params)
        rt = self.send_request(
                method='GET',
                url=url,
                params=params,
                headers=headers,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params))

        data = xml_to_dict(rt.content)
        format_dict(data, ['Upload', 'CommonPrefixes'])
        if decodeflag:
            decode_result(
                data,
                [
                    'Prefix',
                    'KeyMarker',
                    'NextKeyMarker',
                    'UploadIdMarker',
                    'NextUploadIdMarker'
                ],
                [
                    ['Upload', 'Key'],
                    ['CommonPrefixes', 'Prefix']
                ]
            )
        return data

    def head_bucket(self, Bucket, **kwargs):
        """确认bucket是否存在

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 确认bucket是否存在
            response = client.head_bucket(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        url = self._conf.uri(bucket=Bucket)
        logger.info("head bucket, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='HEAD',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key),
            headers=headers)
        return None

    def put_bucket_acl(self, Bucket, AccessControlPolicy={}, **kwargs):
        """设置bucket ACL

        :param Bucket(string): 存储桶名称.
        :param AccessControlPolicy(dict): 设置bucket ACL规则.
        :param kwargs(dict): 通过headers来设置ACL.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 设置 object ACL
            response = client.put_bucket_acl(
                Bucket='bucket',
                ACL='private',
                GrantRead='id="qcs::cam::uin/123:uin/456",id="qcs::cam::uin/123:uin/123"'
            )
        """
        lst = [  # 类型为list的标签
            '<Grant>',
            '</Grant>']
        xml_config = ""
        if AccessControlPolicy:
            xml_config = format_xml(data=AccessControlPolicy, root='AccessControlPolicy', lst=lst)
        headers = mapped(kwargs)
        params = {'acl': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("put bucket acl, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='PUT',
            url=url,
            data=xml_config,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        return None

    def get_bucket_acl(self, Bucket, **kwargs):
        """获取bucket ACL

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置headers.
        :return(dict): Bucket对应的ACL信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 设置 object ACL
            response = client.get_bucket_acl(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        params = {'acl': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("get bucket acl, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='GET',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        data = xml_to_dict(rt.content, "type", "Type")
        if data['AccessControlList'] is not None and not isinstance(data['AccessControlList']['Grant'], list):
            lst = []
            lst.append(data['AccessControlList']['Grant'])
            data['AccessControlList']['Grant'] = lst
        return data

    def put_bucket_cors(self, Bucket, CORSConfiguration={}, **kwargs):
        """设置bucket CORS

        :param Bucket(string): 存储桶名称.
        :param CORSConfiguration(dict): 设置Bucket跨域规则.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 设置bucket跨域配置
            cors_config = {
                'CORSRule': [
                    {
                        'ID': '1234',
                        'AllowedOrigin': ['http://www.qq.com'],
                        'AllowedMethod': ['GET', 'PUT'],
                        'AllowedHeader': ['x-cos-meta-test'],
                        'ExposeHeader': ['x-cos-meta-test1'],
                        'MaxAgeSeconds': 500
                    }
                ]
            }
            response = client.put_bucket_cors(
                Bucket='bucket',
                CORSConfiguration=cors_config
            )
        """
        lst = [  # 类型为list的标签
            '<CORSRule>',
            '<AllowedOrigin>',
            '<AllowedMethod>',
            '<AllowedHeader>',
            '<ExposeHeader>',
            '</CORSRule>',
            '</AllowedOrigin>',
            '</AllowedMethod>',
            '</AllowedHeader>',
            '</ExposeHeader>']
        xml_config = format_xml(data=CORSConfiguration, root='CORSConfiguration', lst=lst)
        headers = mapped(kwargs)
        headers['Content-MD5'] = get_md5(xml_config)
        headers['Content-Type'] = 'application/xml'
        params = {'cors': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("put bucket cors, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='PUT',
            url=url,
            data=xml_config,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        return None

    def get_bucket_cors(self, Bucket, **kwargs):
        """获取bucket CORS

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 获取Bucket对应的跨域配置.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 获取bucket跨域配置
            response = client.get_bucket_cors(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        params = {'cors': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("get bucket cors, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='GET',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        data = xml_to_dict(rt.content)
        if 'CORSRule' in data and not isinstance(data['CORSRule'], list):
            lst = []
            lst.append(data['CORSRule'])
            data['CORSRule'] = lst
        if 'CORSRule' in data:
            allow_lst = ['AllowedOrigin', 'AllowedMethod', 'AllowedHeader', 'ExposeHeader']
            for rule in data['CORSRule']:
                for text in allow_lst:
                    if text in rule and not isinstance(rule[text], list):
                        lst = []
                        lst.append(rule[text])
                        rule[text] = lst
        return data

    def delete_bucket_cors(self, Bucket, **kwargs):
        """删除bucket CORS

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 删除bucket跨域配置
            response = client.delete_bucket_cors(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        params = {'cors': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("delete bucket cors, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='DELETE',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        return None

    def put_bucket_lifecycle(self, Bucket, LifecycleConfiguration={}, **kwargs):
        """设置bucket LifeCycle

        :param Bucket(string): 存储桶名称.
        :param LifecycleConfiguration(dict): 设置Bucket的生命周期规则.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 设置bucket生命周期配置
            lifecycle_config = {
                'Rule': [
                    {
                        'Expiration': {'Date': get_date(2018, 4, 24)},
                        'ID': '123',
                        'Filter': {'Prefix': ''},
                        'Status': 'Enabled',
                    }
                ]
            }
            response = client.put_bucket_lifecycle(
                Bucket='bucket',
                LifecycleConfiguration=lifecycle_config
            )
        """
        # 类型为list的标签
        lst = [
            '<Rule>',
            '<Tag>',
            '<Transition>',
            '<NoncurrentVersionTransition>',
            '</NoncurrentVersionTransition>',
            '</Transition>',
            '</Tag>',
            '</Rule>'
        ]
        xml_config = format_xml(data=LifecycleConfiguration, root='LifecycleConfiguration', lst=lst)
        headers = mapped(kwargs)
        headers['Content-MD5'] = get_md5(xml_config)
        headers['Content-Type'] = 'application/xml'
        params = {'lifecycle': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("put bucket lifecycle, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='PUT',
            url=url,
            data=xml_config,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        return None

    def get_bucket_lifecycle(self, Bucket, **kwargs):
        """获取bucket LifeCycle

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return(dict): Bucket对应的生命周期配置.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 获取bucket生命周期配置
            response = client.get_bucket_lifecycle(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        params = {'lifecycle': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("get bucket lifecycle, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='GET',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        data = xml_to_dict(rt.content)
        format_dict(data, ['Rule'])
        if 'Rule' in data:
            for rule in data['Rule']:
                format_dict(rule, ['Transition', 'NoncurrentVersionTransition'])
                if 'Filter' in rule:
                    format_dict(rule['Filter'], ['Tag'])
        return data

    def delete_bucket_lifecycle(self, Bucket, **kwargs):
        """删除bucket LifeCycle

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 删除bucket生命周期配置
            response = client.delete_bucket_lifecycle(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        params = {'lifecycle': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("delete bucket lifecycle, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='DELETE',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        return None

    def put_bucket_versioning(self, Bucket, Status, **kwargs):
        """设置bucket版本控制

        :param Bucket(string): 存储桶名称.
        :param Status(string): 设置Bucket版本控制的状态，可选值为'Enabled'|'Suspended'.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 打开多版本配置
            response = client.put_bucket_versioning(
                Bucket='bucket',
                Status='Enabled'
            )
        """
        headers = mapped(kwargs)
        params = {'versioning': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("put bucket versioning, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        if Status != 'Enabled' and Status != 'Suspended':
            raise CosClientError('versioning status must be set to Enabled or Suspended!')
        config = dict()
        config['Status'] = Status
        xml_config = format_xml(data=config, root='VersioningConfiguration')
        rt = self.send_request(
            method='PUT',
            url=url,
            data=xml_config,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        return None

    def get_bucket_versioning(self, Bucket, **kwargs):
        """查询bucket版本控制

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 获取Bucket版本控制的配置.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 获取多版本配置
            response = client.get_bucket_versioning(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        params = {'versioning': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("get bucket versioning, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='GET',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        data = xml_to_dict(rt.content)
        return data

    def get_bucket_location(self, Bucket, **kwargs):
        """查询bucket所属地域

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 存储桶的地域信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 获取bucket所在地域信息
            response = client.get_bucket_location(
                Bucket='bucket'
            )
            print (response['LocationConstraint'])
        """
        headers = mapped(kwargs)
        params = {'location': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("get bucket location, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='GET',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        root = xml.etree.ElementTree.fromstring(rt.content)
        data = dict()
        data['LocationConstraint'] = root.text
        return data

    def put_bucket_replication(self, Bucket, ReplicationConfiguration={}, **kwargs):
        """设置bucket跨区域复制配置

        :param Bucket(string): 存储桶名称.
        :param ReplicationConfiguration(dict): 设置Bucket的跨区域复制规则.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 设置bucket跨区域复制配置
            replication_config = {
                'Role': 'qcs::cam::uin/735905558:uin/735905558',
                'Rule': [
                    {
                        'ID': '123',
                        'Status': 'Enabled',
                        'Prefix': 'replication',
                        'Destination': {
                            'Bucket': 'qcs:id/0:cos:cn-south:appid/1252448703:replicationsouth'
                        }
                    }
                ]
            }
            response = client.put_bucket_replication(
                Bucket='bucket',
                ReplicationConfiguration=replication_config
            )
        """
        lst = ['<Rule>', '</Rule>']  # 类型为list的标签
        xml_config = format_xml(data=ReplicationConfiguration, root='ReplicationConfiguration', lst=lst)
        headers = mapped(kwargs)
        headers['Content-MD5'] = get_md5(xml_config)
        headers['Content-Type'] = 'application/xml'
        params = {'replication': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("put bucket replication, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='PUT',
            url=url,
            data=xml_config,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        return None

    def get_bucket_replication(self, Bucket, **kwargs):
        """获取bucket 跨区域复制配置

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return(dict): Bucket对应的跨区域复制配置.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 获取bucket跨区域复制配置
            response = client.get_bucket_replication(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        params = {'replication': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("get bucket replication, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='GET',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        data = xml_to_dict(rt.content)
        format_dict(data, ['Rule'])
        return data

    def delete_bucket_replication(self, Bucket, **kwargs):
        """删除bucket 跨区域复制配置

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 删除bucket跨区域复制配置
            response = client.delete_bucket_replication(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        params = {'replication': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("delete bucket replication, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='DELETE',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        return None

    def put_bucket_website(self, Bucket, WebsiteConfiguration={}, **kwargs):
        """设置bucket静态网站配置

        :param Bucket(string): 存储桶名称.
        :param ReplicationConfiguration(dict): 设置Bucket的静态网站规则.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 设置bucket跨区域复制配置
            website_config = {
                'IndexDocument': {
                    'Suffix': 'string'
                },
                'ErrorDocument': {
                    'Key': 'string'
                },
                'RedirectAllRequestsTo': {
                    'HostName': 'string',
                    'Protocol': 'http'|'https'
                },
                'RoutingRules': [
                    {
                        'Condition': {
                            'HttpErrorCodeReturnedEquals': 'string',
                            'KeyPrefixEquals': 'string'
                        },
                        'Redirect': {
                            'HostName': 'string',
                            'HttpRedirectCode': 'string',
                            'Protocol': 'http'|'https',
                            'ReplaceKeyPrefixWith': 'string',
                            'ReplaceKeyWith': 'string'
                        }
                    }
                ]
            }
            response = client.put_bucket_website(
                Bucket='bucket',
                WebsiteConfiguration=website_config
            )
        """
        xml_config = format_xml(data=WebsiteConfiguration, root='WebsiteConfiguration', parent_child=True)
        headers = mapped(kwargs)
        headers['Content-MD5'] = get_md5(xml_config)
        headers['Content-Type'] = 'application/xml'
        params = {'website': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("put bucket website, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='PUT',
            url=url,
            data=xml_config,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        return None

    def get_bucket_website(self, Bucket, **kwargs):
        """获取bucket 静态网站配置

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return(dict): Bucket对应的静态网站配置.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 获取bucket静态网站配置
            response = client.get_bucket_website(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        params = {'website': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("get bucket website, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='GET',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        data = xml_to_dict(rt.content)
        if 'RoutingRules' in data and not isinstance(data['RoutingRules']['RoutingRule'], list):
            lst = []
            lst.append(data['RoutingRules']['RoutingRule'])
            data['RoutingRules']['RoutingRule'] = lst
        if 'RoutingRules' in data:
            data['RoutingRules'] = data['RoutingRules']['RoutingRule']
        return data

    def delete_bucket_website(self, Bucket, **kwargs):
        """删除bucket 静态网站配置

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 删除bucket静态网站配置
            response = client.delete_bucket_website(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        params = {'website': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("delete bucket website, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='DELETE',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        return None

    def put_bucket_logging(self, Bucket, BucketLoggingStatus={}, **kwargs):
        """设置bucket logging

        :param Bucket(string): 存储桶名称.
        :param BucketLoggingStatus(dict): 设置Bucket的日志配置.
        :param kwargs(dict): 设置请求headers.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 设置bucket logging服务
            logging_bucket = 'logging-beijing-1252448703'
            logging_config = {
                'LoggingEnabled': {
                    'TargetBucket': logging_bucket,
                    'TargetPrefix': 'test'
                }
            }
            response = logging_client.put_bucket_logging(
                Bucket=logging_bucket,
                BucketLoggingStatus=logging_config
            )
        """
        xml_config = format_xml(data=BucketLoggingStatus, root='BucketLoggingStatus')
        headers = mapped(kwargs)
        headers['Content-MD5'] = get_md5(xml_config)
        headers['Content-Type'] = 'application/xml'
        params = {'logging': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("put bucket logging, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        logging_rt = self.send_request(
            method='PUT',
            url=url,
            data=xml_config,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        grant_rt = self.put_bucket_acl(Bucket=Bucket, GrantFullControl=LOGGING_UIN)
        return None

    def get_bucket_logging(self, Bucket, **kwargs):
        """获取bucket logging

        :param Bucket(string): 存储桶名称.
        :param kwargs(dict): 设置请求headers.
        :return(dict): Bucket对应的logging配置.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 获取bucket logging服务配置
            response = logging_client.get_bucket_logging(
                Bucket=logging_bucket
            )
        """
        headers = mapped(kwargs)
        params = {'logging': ''}
        url = self._conf.uri(bucket=Bucket)
        logger.info("get bucket logging, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        rt = self.send_request(
            method='GET',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, params=params),
            headers=headers,
            params=params)
        data = xml_to_dict(rt.content)
        return data

    # service interface begin
    def list_buckets(self, **kwargs):
        """列出所有bucket

        :return(dict): 账号下bucket相关信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 获取账户下所有存储桶信息
            response = logging_client.list_buckets(
                Bucket='bucket'
            )
        """
        headers = mapped(kwargs)
        url = 'http://service.cos.myqcloud.com/'
        rt = self.send_request(
                method='GET',
                url=url,
                headers=headers,
                auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key),
                )
        data = xml_to_dict(rt.content)
        if data['Buckets'] is not None and not isinstance(data['Buckets']['Bucket'], list):
            lst = []
            lst.append(data['Buckets']['Bucket'])
            data['Buckets']['Bucket'] = lst
        return data

    # Advanced interface
    def _upload_part(self, bucket, key, local_path, offset, size, part_num, uploadid, md5_lst, resumable_flag, already_exist_parts):
        """从本地文件中读取分块, 上传单个分块,将结果记录在md5——list中

        :param bucket(string): 存储桶名称.
        :param key(string): 分块上传路径名.
        :param local_path(string): 本地文件路径名.
        :param offset(int): 读取本地文件的分块偏移量.
        :param size(int): 读取本地文件的分块大小.
        :param part_num(int): 上传分块的序号.
        :param uploadid(string): 分块上传的uploadid.
        :param md5_lst(list): 保存上传成功分块的MD5和序号.
        :param resumable_flag(bool): 是否为断点续传.
        :param already_exist_parts(dict): 断点续传情况下,保存已经上传的块的序号和Etag.
        :return: None.
        """
        # 如果是断点续传且该分块已经上传了则不用实际上传
        if resumable_flag and part_num in already_exist_parts:
            md5_lst.append({'PartNumber': part_num, 'ETag': already_exist_parts[part_num]})
        else:
            with open(local_path, 'rb') as fp:
                fp.seek(offset, 0)
                data = fp.read(size)
            rt = self.upload_part(bucket, key, data, part_num, uploadid)
            md5_lst.append({'PartNumber': part_num, 'ETag': rt['ETag']})
        return None

    def _get_resumable_uploadid(self, bucket, key):
        """从服务端获取未完成的分块上传任务,获取断点续传的uploadid

        :param bucket(string): 存储桶名称.
        :param key(string): 分块上传路径名.
        :return(string): 断点续传的uploadid,如果不存在则返回None.
        """
        multipart_response = self.list_multipart_uploads(
            Bucket=bucket,
            Prefix=key
        )
        if 'Upload' in multipart_response:
            # 取最后一个(最新的)uploadid
            index = len(multipart_response['Upload']) - 1
            while index >= 0:
                if multipart_response['Upload'][index]['Key'] == key:
                    return multipart_response['Upload'][index]['UploadId']
                index -= 1
        return None

    def _check_single_upload_part(self, local_path, offset, local_part_size, remote_part_size, remote_etag):
        """从本地文件中读取分块, 校验本地分块和服务端的分块信息

        :param local_path(string): 本地文件路径名.
        :param offset(int): 读取本地文件的分块偏移量.
        :param local_part_size(int): 读取本地文件的分块大小.
        :param remote_part_size(int): 服务端的文件的分块大小.
        :param remote_etag(string): 服务端的文件Etag.
        :return(bool): 本地单个分块的信息是否和服务端的分块信息一致
        """
        if local_part_size != remote_part_size:
            return False
        with open(local_path, 'rb') as fp:
            fp.seek(offset, 0)
            local_etag = get_raw_md5(fp.read(local_part_size))
            if local_etag == remote_etag:
                return True
        return False

    def _check_all_upload_parts(self, bucket, key, uploadid, local_path, parts_num, part_size, last_size, already_exist_parts):
        """获取所有已经上传的分块的信息,和本地的文件进行对比

        :param bucket(string): 存储桶名称.
        :param key(string): 分块上传路径名.
        :param uploadid(string): 分块上传的uploadid
        :param local_path(string): 本地文件的大小
        :param parts_num(int): 本地文件的分块数
        :param part_size(int): 本地文件的分块大小
        :param last_size(int): 本地文件的最后一块分块大小
        :param already_exist_parts(dict): 保存已经上传的分块的part_num和Etag
        :return(bool): 本地文件是否通过校验,True为可以进行断点续传,False为不能进行断点续传
        """
        parts_info = []
        part_number_marker = 0
        list_over_status = False
        while list_over_status is False:
            response = self.list_parts(
                Bucket=bucket,
                Key=key,
                UploadId=uploadid,
                PartNumberMarker=part_number_marker
            )
            # 已经存在的分块上传,有可能一个分块都没有上传,判断一下
            if 'Part' in response:
                parts_info.extend(response['Part'])
            if response['IsTruncated'] == 'false':
                list_over_status = True
            else:
                part_number_marker = int(response['NextPartNumberMarker'])
        for part in parts_info:
            part_num = int(part['PartNumber'])
            # 如果分块数量大于本地计算出的最大数量,校验失败
            if part_num > parts_num:
                return False
            offset = (part_num - 1) * part_size
            local_part_size = part_size
            if part_num == parts_num:
                local_part_size = last_size
            # 有任何一块没有通过校验，则校验失败
            if not self._check_single_upload_part(local_path, offset, local_part_size, int(part['Size']), part['ETag']):
                return False
            already_exist_parts[part_num] = part['ETag']
        return True

    def upload_file(self, Bucket, Key, LocalFilePath, PartSize=1, MAXThread=5, **kwargs):
        """小于等于20MB的文件简单上传，大于20MB的文件使用分块上传

        :param Bucket(string): 存储桶名称.
        :param key(string): 分块上传路径名.
        :param LocalFilePath(string): 本地文件路径名.
        :param PartSize(int): 分块的大小设置,单位为MB.
        :param MAXThread(int): 并发上传的最大线程数.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 成功上传文件的元信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 根据文件大小自动选择分块大小,多线程并发上传提高上传速度
            file_name = 'thread_1GB_test'
            response = client.upload_file(
                Bucket='bucket',
                Key=file_name,
                LocalFilePath=file_name,
                PartSize=10,
                MAXThread=10,
                CacheControl='no-cache',
                ContentDisposition='download.txt'
            )
        """
        file_size = os.path.getsize(LocalFilePath)
        if file_size <= 1024*1024*20:
            with open(LocalFilePath, 'rb') as fp:
                rt = self.put_object(Bucket=Bucket, Key=Key, Body=fp, **kwargs)
            return rt
        else:
            part_size = 1024*1024*PartSize  # 默认按照1MB分块,最大支持10G的文件，超过10G的分块数固定为10000
            last_size = 0  # 最后一块可以小于1MB
            parts_num = file_size // part_size
            last_size = file_size % part_size

            if last_size != 0:
                parts_num += 1
            else:  # 如果刚好整除,最后一块的大小等于分块大小
                last_size = part_size
            if parts_num > 10000:
                parts_num = 10000
                part_size = file_size // parts_num
                last_size = file_size % parts_num
                last_size += part_size

            # 创建分块上传
            # 判断是否可以断点续传
            resumable_flag = False
            already_exist_parts = {}
            uploadid = self._get_resumable_uploadid(Bucket, Key)
            if uploadid is not None:
                logger.info("fetch an existed uploadid in remote cos, uploadid={uploadid}".format(uploadid=uploadid))
                # 校验服务端返回的每个块的信息是否和本地的每个块的信息相同,只有校验通过的情况下才可以进行断点续传
                resumable_flag = self._check_all_upload_parts(Bucket, Key, uploadid, LocalFilePath, parts_num, part_size, last_size, already_exist_parts)
            # 如果不能断点续传,则创建一个新的分块上传
            if not resumable_flag:
                rt = self.create_multipart_upload(Bucket=Bucket, Key=Key, **kwargs)
                uploadid = rt['UploadId']
                logger.info("create a new uploadid in upload_file, uploadid={uploadid}".format(uploadid=uploadid))

            # 上传分块
            offset = 0  # 记录文件偏移量
            lst = list()  # 记录分块信息
            pool = SimpleThreadPool(MAXThread)

            for i in range(1, parts_num+1):
                if i == parts_num:  # 最后一块
                    pool.add_task(self._upload_part, Bucket, Key, LocalFilePath, offset, file_size-offset, i, uploadid, lst, resumable_flag, already_exist_parts)
                else:
                    pool.add_task(self._upload_part, Bucket, Key, LocalFilePath, offset, part_size, i, uploadid, lst, resumable_flag, already_exist_parts)
                    offset += part_size

            pool.wait_completion()
            result = pool.get_result()
            if not result['success_all'] or len(lst) != parts_num:
                raise CosClientError('some upload_part fail after max_retry, please upload_file again')
            lst = sorted(lst, key=lambda x: x['PartNumber'])  # 按PartNumber升序排列

            # 完成分块上传
            rt = self.complete_multipart_upload(Bucket=Bucket, Key=Key, UploadId=uploadid, MultipartUpload={'Part': lst})
            return rt

    def _inner_head_object(self, CopySource):
        """查询源文件的长度"""
        bucket, path, endpoint, versionid = get_copy_source_info(CopySource)
        params = {}
        if versionid != '':
            params['versionId'] = versionid
        url = self._conf.uri(bucket=bucket, path=path, endpoint=endpoint)
        rt = self.send_request(
            method='HEAD',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, path, params=params),
            headers={},
            params=params)
        return int(rt.headers['Content-Length'])

    def _upload_part_copy(self, bucket, key, part_number, upload_id, copy_source, copy_source_range, md5_lst):
        """拷贝指定文件至分块上传,记录结果到lst中去

        :param bucket(string): 存储桶名称.
        :param key(string): 上传COS路径.
        :param part_number(int): 上传分块的编号.
        :param upload_id(string): 分块上传创建的UploadId.
        :param copy_source(dict): 拷贝源,包含Appid,Bucket,Region,Key.
        :param copy_source_range(string): 拷贝源的字节范围,bytes=first-last。
        :param md5_lst(list): 保存上传成功分块的MD5和序号.
        :return: None.
        """
        rt = self.upload_part_copy(bucket, key, part_number, upload_id, copy_source, copy_source_range)
        md5_lst.append({'PartNumber': part_number, 'ETag': rt['ETag']})
        return None

    def _check_same_region(self, dst_endpoint, CopySource):
        src_endpoint = get_copy_source_info(CopySource)[2]
        if src_endpoint == dst_endpoint:
            return True
        return False

    def copy(self, Bucket, Key, CopySource, CopyStatus='Copy', PartSize=10, MAXThread=5, **kwargs):
        """文件拷贝，小于5G的文件调用copy_object，大于等于5G的文件调用分块上传的upload_part_copy

        :param Bucket(string): 存储桶名称.
        :param Key(string): 上传COS路径.
        :param CopySource(dict): 拷贝源,包含Appid,Bucket,Region,Key.
        :param CopyStatus(string): 拷贝状态,可选值'Copy'|'Replaced'.
        :param PartSize(int): 分块的大小设置.
        :param MAXThread(int): 并发上传的最大线程数.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 拷贝成功的结果.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 根据拷贝源文件的大小自动选择拷贝策略
            copy_source = {'Bucket': 'testcopt-1252468703', 'Key': '/thread_1MB', 'Region': 'ap-guangzhou'}
            response = client.copy(
                Bucket='test',
                Key='copy_10G.txt',
                CopySource=copy_source,
                MAXThread=10
            )
        """
        # 同园区直接走copy_object
        if self._check_same_region(self._conf._endpoint, CopySource):
            response = self.copy_object(Bucket=Bucket, Key=Key, CopySource=CopySource, CopyStatus=CopyStatus, **kwargs)
            return response

        # 不同园区查询拷贝源object的content-length
        file_size = self._inner_head_object(CopySource)
        # 如果源文件大小小于5G，则直接调用copy_object接口
        if file_size < SINGLE_UPLOAD_LENGTH:
            response = self.copy_object(Bucket=Bucket, Key=Key, CopySource=CopySource, CopyStatus=CopyStatus, **kwargs)
            return response

        # 如果源文件大小大于等于5G，则先创建分块上传，在调用upload_part
        part_size = 1024*1024*PartSize  # 默认按照10MB分块
        last_size = 0  # 最后一块可以小于1MB
        parts_num = file_size // part_size
        last_size = file_size % part_size
        if last_size != 0:
            parts_num += 1
        if parts_num > 10000:
            parts_num = 10000
            part_size = file_size // parts_num
            last_size = file_size % parts_num
            last_size += part_size
        # 创建分块上传
        rt = self.create_multipart_upload(Bucket=Bucket, Key=Key, **kwargs)
        uploadid = rt['UploadId']

        # 上传分块拷贝
        offset = 0  # 记录文件偏移量
        lst = list()  # 记录分块信息
        pool = SimpleThreadPool(MAXThread)

        for i in range(1, parts_num+1):
            if i == parts_num:  # 最后一块
                copy_range = gen_copy_source_range(offset, file_size-1)
                pool.add_task(self._upload_part_copy, Bucket, Key, i, uploadid, CopySource, copy_range, lst)
            else:
                copy_range = gen_copy_source_range(offset, offset+part_size-1)
                pool.add_task(self._upload_part_copy, Bucket, Key, i, uploadid, CopySource, copy_range, lst)
                offset += part_size

        pool.wait_completion()
        result = pool.get_result()
        if not result['success_all']:
            raise CosClientError('some upload_part_copy fail after max_retry')

        lst = sorted(lst, key=lambda x: x['PartNumber'])  # 按PartNumber升序排列
        # 完成分片上传
        try:
            rt = self.complete_multipart_upload(Bucket=Bucket, Key=Key, UploadId=uploadid, MultipartUpload={'Part': lst})
        except Exception as e:
            abort_response = self.abort_multipart_upload(Bucket=Bucket, Key=Key, UploadId=uploadid)
            raise e
        return rt

    def _upload_part_from_buffer(self, bucket, key, data, part_num, uploadid, md5_lst):
        """从内存中读取分块, 上传单个分块,将结果记录在md5——list中

        :param bucket(string): 存储桶名称.
        :param key(string): 分块上传路径名.
        :param data(string): 数据块.
        :param part_num(int): 上传分块的序号.
        :param uploadid(string): 分块上传的uploadid.
        :param md5_lst(list): 保存上传成功分块的MD5和序号.
        :return: None.
        """

        rt = self.upload_part(bucket, key, data, part_num, uploadid)
        md5_lst.append({'PartNumber': part_num, 'ETag': rt['ETag']})
        return None

    def upload_file_from_buffer(self, Bucket, Key, Body, MaxBufferSize=100, PartSize=10, MAXThread=5, **kwargs):
        """小于分块大小的的文件简单上传，大于等于分块大小的文件使用分块上传

        :param Bucket(string): 存储桶名称.
        :param key(string): 分块上传路径名.
        :param Body(fp): 文件流,必须实现了read方法.
        :param MaxBufferSize(int): 缓存文件的大小,单位为MB,MaxBufferSize/PartSize决定线程池中最大等待调度的任务数量
        :param PartSize(int): 分块的大小设置,单位为MB
        :param MAXThread(int): 并发上传的最大线程数.
        :param kwargs(dict): 设置请求headers.
        :return(dict): 成功上传的文件的结果.
        """
        if not hasattr(Body, 'read'):
            raise CosClientError("Body must has attr read")

        part_size = 1024*1024*PartSize

        # 先读一个块,如果直接EOF了就调用简单文件上传
        part_num = 1
        data = Body.read(part_size)

        if len(data) < part_size:
            rt = self.put_object(Bucket=Bucket, Key=Key, Body=data, **kwargs)
            return rt

        # 创建分块上传
        rt = self.create_multipart_upload(Bucket=Bucket, Key=Key, **kwargs)
        uploadid = rt['UploadId']

        lst = list()  # 记录分块信息
        MAXQueue = MaxBufferSize//PartSize
        pool = SimpleThreadPool(MAXThread, MAXQueue)
        while True:
            if data == "":
                break
            pool.add_task(self._upload_part_from_buffer, Bucket, Key, data, part_num, uploadid, lst)
            part_num += 1
            data = Body.read(part_size)

        pool.wait_completion()
        result = pool.get_result()
        if not result['success_all']:
            raise CosClientError('some upload_part fail after max_retry')
        lst = sorted(lst, key=lambda x: x['PartNumber'])  # 按PartNumber升序排列

        # 完成分片上传
        try:
            rt = self.complete_multipart_upload(Bucket=Bucket, Key=Key, UploadId=uploadid, MultipartUpload={'Part': lst})
        except Exception as e:
            abort_response = self.abort_multipart_upload(Bucket=Bucket, Key=Key, UploadId=uploadid)
            raise e
        return rt

    def append_object(self, Bucket, Key, Position, Data, **kwargs):
        """文件块追加接口

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param Position(int): 追加内容的起始位置.
        :param Data(string): 追加的内容
        :kwargs(dict): 设置上传的headers.
        :return(dict): 上传成功返回的结果，包含ETag等信息.
        """
        headers = mapped(kwargs)
        params = {'append': '', 'position': Position}
        url = self._conf.uri(bucket=Bucket, path=Key)
        logger.info("append object, url=:{url} ,headers=:{headers}".format(
            url=url,
            headers=headers))
        Body = deal_with_empty_file_stream(Data)
        rt = self.send_request(
            method='POST',
            url=url,
            auth=CosS3Auth(self._conf._secret_id, self._conf._secret_key, Key, params=params),
            data=Body,
            headers=headers,
            params=params)
        response = rt.headers
        return response

    def put_object_from_local_file(self, Bucket, LocalFilePath, Key, EnableMD5=False, **kwargs):
        """本地文件上传接口，适用于小文件，最大不得超过5GB

        :param Bucket(string): 存储桶名称.
        :param LocalFilePath(string): 上传文件的本地路径.
        :param Key(string): COS路径.
        :param EnableMD5(bool): 是否需要SDK计算Content-MD5，打开此开关会增加上传耗时.
        :kwargs(dict): 设置上传的headers.
        :return(dict): 上传成功返回的结果，包含ETag等信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 上传本地文件到cos
            response = client.put_object_from_local_file(
                Bucket='bucket',
                LocalFilePath='local.txt',
                Key='test.txt'
            )
            print (response['ETag'])
        """
        with open(LocalFilePath, 'rb') as fp:
            return self.put_object(Bucket, fp, Key, EnableMD5, **kwargs)

    def object_exists(self, Bucket, Key):
        """判断一个文件是否存在

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :return(bool): 文件是否存在,返回True为存在,返回False为不存在

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 上传本地文件到cos
            status = client.object_exists(
                Bucket='bucket',
                Key='test.txt'
            )
        """
        try:
            self.head_object(Bucket, Key)
            return True
        except CosServiceError as e:
            if e.get_status_code() == 404:
                return False
            else:
                raise e

    def bucket_exists(self, Bucket):
        """判断一个存储桶是否存在

        :param Bucket(string): 存储桶名称.
        :return(bool): 存储桶是否存在,返回True为存在,返回False为不存在.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 上传本地文件到cos
            status = client.bucket_exists(
                Bucket='bucket'
            )
        """
        try:
            self.head_bucket(Bucket)
            return True
        except CosServiceError as e:
            if e.get_status_code() == 404:
                return False
            else:
                raise e

    def change_object_storage_class(self, Bucket, Key, StorageClass):
        """改变文件的存储类型

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :param StorageClass(bool): 是否需要SDK计算Content-MD5，打开此开关会增加上传耗时.
        :kwargs(dict): 设置上传的headers.
        :return(dict): 上传成功返回的结果，包含ETag等信息.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 上传本地文件到cos
            response = client.change_object_storage_class(
                Bucket='bucket',
                Key='test.txt',
                StorageClass='STANDARD'
            )
        """
        copy_source = {
            'Bucket': Bucket,
            'Key': Key,
            'Endpoint': self._conf._endpoint,
            'Appid': self._conf._appid
        }
        response = self.copy_object(
            Bucket=Bucket,
            Key=Key,
            CopySource=copy_source,
            CopyStatus='Replaced',
            StorageClass=StorageClass
        )
        return response

    def update_object_meta(self, Bucket, Key, **kwargs):
        """改变文件的存储类型

        :param Bucket(string): 存储桶名称.
        :param Key(string): COS路径.
        :kwargs(dict): 设置文件的元属性.
        :return: None.

        .. code-block:: python

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)  # 获取配置对象
            client = CosS3Client(config)
            # 上传本地文件到cos
            response = client.update_object_meta(
                Bucket='bucket',
                Key='test.txt',
                ContentType='text/html'
            )
        """
        copy_source = {
            'Bucket': Bucket,
            'Key': Key,
            'Endpoint': self._conf._endpoint,
            'Appid': self._conf._appid
        }
        response = self.copy_object(
            Bucket=Bucket,
            Key=Key,
            CopySource=copy_source,
            CopyStatus='Replaced',
            **kwargs
        )
        return response


if __name__ == "__main__":
    pass
