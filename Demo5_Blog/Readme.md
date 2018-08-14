##使用API GW实现博客文章查询

下面是该服务的实现流程：

- 创建函数，在 API 网关中配置 API 规则并且后端服务指向函数。
- 用户请求 API 时带有文章编号。
- 云函数根据请求参数，查询编号对应内容，并使用 json 格式响应请求。
- 用户可获取到 json 格式响应后进行后续处理。


请注意，完成本教程后，您的账户中将具有以下资源：

- 一个由 API 网关触发的 SCF 云函数。
- 一个 API 网关中的 API 服务及下属的 API 规则。

本教程分为了三个主要部分：

- 完成函数代码编写、函数创建和测试。
- 完成 API 服务和 API 规则的设计，创建及配置。
- 通过浏览器或 HTTP 请求工具测试验证 API 接口工作的正确性。

#### API 设计

现在应用的 API 设计通常遵守 Restful 规范，因此，在此示例中，我们设计获取博客文章的 API 为以下形式

* /article GET
返回文章列表

* /article/{articleId} GET
根据文章 id，返回文章内容


## 步骤一 创建 blogArticle 云函数

1 . 登录[无服务器云函数控制台](https://console.cloud.tencent.com/scf)，在【北京】地域下单击【新建】按钮。

2 . 进入函数配置部分，函数名称填写`blogArticle`，剩余项保持默认，单击【下一步】。

3 . 进入函数代码部分，执行方法填写`index.main_handler`，代码窗口内贴入如下代码，单击【下一步】。

```
# -*- coding: utf8 -*-
import json

testArticleInfo=[
    {"id":1,"category":"blog","title":"hello world","content":"first blog! hello world!","time":"2017-12-05 13:45"},
    {"id":2,"category":"blog","title":"record info","content":"record work and study!","time":"2017-12-06 08:22"},
    {"id":3,"category":"python","title":"python study","content":"python study for 2.7","time":"2017-12-06 18:32"},
]

def main_handler(event,content):
    if "requestContext" not in event.keys():
        return {"errorCode":410,"errorMsg":"event is not come from api gateway"}
    if event["requestContext"]["path"] != "/article/{articleId}" and event["requestContext"]["path"] != "/article":
        return {"errorCode":411,"errorMsg":"request is not from setting api path"}
    if event["requestContext"]["path"] == "/article" and event["requestContext"]["httpMethod"] == "GET": #获取文章列表
        retList = []
        for article in testArticleInfo:
            retItem = {}
            retItem["id"] = article["id"]
            retItem["category"] = article["category"]
            retItem["title"] = article["title"]
            retItem["time"] = article["time"]
            retList.append(retItem)
        return retList
    if event["requestContext"]["path"] == "/article/{articleId}" and event["requestContext"]["httpMethod"] == "GET": #获取文章内容
        articleId = int(event["pathParameters"]["articleId"])
        for article in testArticleInfo:
            if article["id"] == articleId:
                return article
        return {"errorCode":412,"errorMsg":"article is not found"}
    return {"errorCode":413,"errorMsg":"request is not correctly execute"}
```
4 . 进入触发方式部分，由于 API 网关触发的配置位于 API 网关中，此处暂时不添加任何触发方式，单击【完成】按钮。


**注意**

保存文章的数据结构使用 testArticleInfo 变量进行保存和模拟，此处在实际应用中通常为从数据库中或者文件中读取。

#### 测试 blogArticle 云函数

在创建函数时，通常会使用控制台或 API 先进行测试，确保函数输出符合预期后再绑定触发器进行实际应用。

1 . 在刚刚创建的函数详情页中，单击【测试】按钮；

2 . 在测试模版内选择【API Gateway 测试模版】，并修改模版成为如下内容，此内容为测试获取文章列表的 API。

```
{
  "requestContext": {
    "serviceName": "testsvc",
    "path": "/article",
    "httpMethod": "GET",
    "requestId": "c6af9ac6-7b61-11e6-9a41-93e8deadbeef",
    "identity": {
      "secretId": "abdcdxxxxxxxsdfs"
    },
    "sourceIp": "10.0.2.14",
    "stage": "prod"
  },
  "headers": {
    "Accept-Language": "en-US,en,cn",
    "Accept": "text/html,application/xml,application/json",
    "Host": "service-3ei3tii4-251000691.ap-guangzhou.apigateway.myqloud.com",
    "User-Agent": "User Agent String"
  },
  "pathParameters": {
  },
  "queryStringParameters": {
  },
  "headerParameters":{
    "Refer": "10.0.2.14"
  },
  "path": "/article",
  "httpMethod": "GET"
}
```

其中 `requestContext` 内的 `path`，`httpMethod`字段，外围的`path`，`httpMethod` 字段，均修改为我们设计的 API 路径 `/article` 和方法 `GET`。

3 . 单击【运行】按钮，观察运行结果。运行结果应该为成功，且返回内容应该为如下所示的文章概要内容。

```
[{"category": "blog", "time": "2017-12-05 13:45", "id": 1, "title": "hello world"}, {"category": "blog", "time": "2017-12-06 08:22", "id": 2, "title": "record info"}, {"category": "python", "time": "2017-12-06 18:32", "id": 3, "title": "python study"}]
```

4 . 修改测试模版成为如下内容，此内容为测试获取文章内容的 API。

```
{
  "requestContext": {
    "serviceName": "testsvc",
    "path": "/article/{articleId}",
    "httpMethod": "GET",
    "requestId": "c6af9ac6-7b61-11e6-9a41-93e8deadbeef",
    "identity": {
      "secretId": "abdcdxxxxxxxsdfs"
    },
    "sourceIp": "10.0.2.14",
    "stage": "prod"
  },
  "headers": {
    "Accept-Language": "en-US,en,cn",
    "Accept": "text/html,application/xml,application/json",
    "Host": "service-3ei3tii4-251000691.ap-guangzhou.apigateway.myqloud.com",
    "User-Agent": "User Agent String"
  },
  "pathParameters": {
    "articleId":"1"
  },
  "queryStringParameters": {
  },
  "headerParameters":{
    "Refer": "10.0.2.14"
  },
  "path": "/article/1",
  "httpMethod": "GET"
}
```

其中 `requestContext` 内的 `path`，`httpMethod`字段，外围的`path`，`httpMethod` 字段，均修改为我们设计的 API 路径 `/article/{articleId}`和实际请求路径 `/article/1` ，方法为`GET`， `pathParameters` 字段内应该为 API网关内抽取出来的参数和实际值`"articleId":"1" ` 。

5 . 单击【运行】按钮，观察运行结果。运行结果应该为成功，且返回内容应该为如下所示的文章详细内容。

```
{"category": "blog", "content": "first blog! hello world!", "time": "2017-12-05 13:45", "id": 1, "title": "hello world"}
```

## 步骤二 创建 API 服务和 API 规则

> 注意：
> API 服务和函数必须位于同一个地域下。在本教程中，将使用北京区域来创建 API 服务。

1. 登录[腾讯云控制台](https://console.cloud.tencent.com/apigateway)，从云产品中选择【互联网中间件】-【API 网关】。

2. 单击【服务】选项卡，并切换地域为【北京】。

3. 单击【新建】按钮以新建 API 服务，在弹出窗口中写入服务名 `blogAPI`，单击提交创建。

4. 在弹出的选项卡中，选择 【API 配置】前往 API 管理选项卡。

5. 单击【新建】创建 API，API 名称可以写为 `blogArticle`， 路径为 `/article`，请求方法为 GET，为了方便后面的测试，在这里选择免鉴权，无需输入参数配置，单击【下一步】。

6. 后端类型选择为【cloud function】，选择函数为步骤一中创建的 `blogArticle`，单击【下一步】，单击【完成】，在弹出的选项卡中单击【取消】。

7. 继续在【API管理】选项卡中单击【新建】创建 API，API 名称可以写为 `blogArticleID`，路径为 `/article/{articleId}`，请求方法为 GET，选择免鉴权，参数配置中点击“新增参数配置”，输入名称为 `articleId` 的参数，参数位置为 Path，类型为 int，默认值为 1，单击【下一步】。

8. 后端类型选择为【cloud function】，选择函数为步骤一中创建的 `blogArticle`，单击【下一步】，单击【完成】，在弹出的选项卡中单击【取消】。

9. 在【API管理】选项卡中，选中前面第 5 步创建的 `blogArticle` API，在右上角单击 【API 调试】，在调试页面点击【发送请求】，确保返回结果内的响应 Body，为如下内容：
```
[{"category": "blog", "time": "2017-12-05 13:45", "id": 1, "title": "hello world"}, {"category": "blog", "time": "2017-12-06 08:22", "id": 2, "title": "record info"}, {"category": "python", "time": "2017-12-06 18:32", "id": 3, "title": "python study"}]
```

10. 返回【API管理】选项卡中，选中前面第 7 步创建的 `blogArticleID` API， 在右上角单击【API 调试】，在调试页面点击【发送请求】，确保返回结果内的响应 Body，为如下内容：
```
{"category": "blog", "content": "first blog! hello world!", "time": "2017-12-05 13:45", "id": 1, "title": "hello world"}
```

11. 也可以修改第 2 步中的请求参数 articleId 的值为其他数字，查看响应内容。

##步骤三 API 服务发布

1. 在 API 网关控制台的【服务】列表页中，找到在步骤二创建的 blogAPI 服务，并单击服务操作中的【发布】按钮。

2. 在发布服务的弹窗中，发布环境选择 `发布`，备注内填入 `发布API`，单击【提交】。

#### API 在线验证

通过发布动作，完成了 API 服务的发布，使得 API 可以被外部所访问到，接下来通过浏览器发起请求来查看 API 是否能正确响应。

1. 在 blogAPI 服务中，进入【环境管理】选项卡，复制其中 `发布` 环境的访问路径，例如 `service-k3jie4bl-1256608914.ap-beijing.apigateway.myqcloud.com/release`。
 **注意** 这里由于每个服务的域名均不相同，您的服务所分配到的域名将与本文中的服务域名有差别，请勿直接拷贝本文中的地址访问。

2. 在此路径后增加创建的 API 规则的路径，形成如下路径。
```
service-k3jie4bl-1256608914.ap-beijing.apigateway.myqcloud.com/release/article
service-k3jie4bl-1256608914.ap-beijing.apigateway.myqcloud.com/release/article/1
service-k3jie4bl-1256608914.ap-beijing.apigateway.myqcloud.com/release/article/2
```

3. 将第2步中的路径复制到浏览器中访问，确定输出内容与测试 API 时的输出相同。

4. 可进一步修改请求中的文章编号并查看输出，查看代码是否能正确处理错误的文章编号。


至此完成了通过 SCF 云函数实现服务，通过 API 对外提供服务。后续可以通过继续修改代码，增加功能并增加 API 规则，使其完善成为一个更丰富的应用模块。

