---
layout: post
title: Ceilometer 源码学习 - Polling Agent
category: 
tags: [Ceilometer, Source]
keywords: Ceilometer, Central Agent, Compute Agent, Source
---
## 简介
Ceilometer是Openstack中用于数据采集的基础设施，包括多个组件：Central Agent，Compute Agent，Notification Agent，Collector等。其中Central Agent和Compute Agent分别运行在Controller和Compute机器上，通过定期调用其他服务的api来完成数据采集。由于二者的区别只是所负责的数据来源，这里我们统称为Polling Agent。

## 需求导向
Polling Agent的功能很简单：

> **周期性地向其他服务主动拉取需要的数据，并将数据发送到消息队列。**

其结构图如下：
![图1 Central Agent结构图](http://docs.openstack.org/developer/ceilometer/_images/2-2-collection-poll.png)

站在设计者的角度，要完成上述功能，需要处理的有如下几个基本问题：

1. 怎么执行拉取；
2. 向哪些服务拉取数据；
3. 对于某个服务收集哪些数据以及如何收集。

下面分别针对上述问题依次介绍Ceilometer的实现方式:

1. **常驻进程**：自然的我们需要一个常驻进程来完成上述调度任务，基本操作包括：
    
    - 记录全局状态；
    - 周期性的触发；
    - 负责消息的发送。
2. **插件形式**：Ceilometer中用定义插件的方式定义多个收集器（Pollster），程序从配置文件中获得需要加载的收集器列表，用插件的形式是一个很好的选择，因为：
    
    - python对插件的良好支持：[stevedore](http://docs.openstack.org/developer/stevedore/)
    - 简化核心逻辑；
    - 方便扩展。
3.  **共同基类**：数据来源多种多样，针对不同的数据来源获取数据方式各有不同，但他们需要完成同样的的动作，Ceilometer中设计Pollster的共同基类，定义了如下接口，是每个Pollster都是要实现的：
    
    - 默认获取数据来源的方式：default\_discovery；
    - 拉取数据：get\_samples。
    
## 流程简介
正是由于上面所说的实现方式使得Polling Agent的核心逻辑变得非常简单，不需要关注具体的数据收集过程，而将自己解放成一个调度管理者，下面将简单介绍其实现逻辑。在此之前为了方便说明，先介绍其中涉及到的角色或组件:

- **AgentManager**：Polling Agent的核心类，Central Agent和Compute Agent用不同的参数初始化AgentManager；
- **Pollster**：数据收集器，以插件的形式动态载入；
- **Discover**：以一定的方式发现数据源Resource；
- **Pipeline**：Ceilometer通过pipleline.yml文件的形式定义了所收集数据的一系列转换发送操作，很好的降低了各组件的耦合性和系统的复杂性。该文件中以sources标签定义了不同数据的分组信息，这部分是在Polling Agent中需要关心的；
- **PollingTask**：望文生义，表示一个拉取数据的任务；
- **Resource**：代表一个可提供数据的源，如一个镜像或一个虚拟机实例。

**基本流程**如下：

- AgentManger初始化，主要完成如下动作：
    
    - 从配置文件中动态加载所有收集器插件Pollster；
    - 从配置文件中动态加载所有资源发现器插件Discover。
- AgentManger启动：
    
    - 从pipeline文件读取sources信息；
    - 为每一个从文件中加载的Pollster根据Pipeline信息分配一个PollingTask；
    - 为每个PollingTask建立Timer执行。
- PollingTask执行：
    
    - 通过Pollster的default\_discovery函数定义，从已加载的资源发现器Discover中选取合适的一个；
    - 调用Discover的discovery函数获取Resource；
    - 调用Pollster的get\_samples函数，从Resource中获得采样数据；
    - 发送给消息队列。

## 代码细节
先看一下数据采集的完整过程：
![图2 Central Agent 序列图](https://www.gliffy.com/go/publish/image/9349993/L.png)

接下来从代码层面详细介绍上述逻辑实现：

### 1. **入口**
- Ceilometer采用[pbr](http://docs.openstack.org/developer/pbr/)的方式管理配置，
- setup.cfg中定义了Polling Agent 入口位置，如下：

``` yaml
console_scripts =
    ceilometer-polling = ceilometer.cmd.eventlet.polling:main
    ...
```

### 2. **ceilometer.cmd.eventlet.polling**
相应的，在ceilometer/cmd/eventlet/polling.py 文件中找到该函数，如下：

``` python
def main():
     service.prepare_service()
     os_service.launch(CONF, manager.AgentManager(CONF.polling_namespaces,
                                                CONF.pollster_list)).wait()
```

- prepare\_service中做了一些初始化工作，如初始化日志，加载配置文件等；
- 第二句为核心，配置并启动了manager.AgentManager，进一步了解到主要工作发生在该类的父类中，即base.AgentManger

### 3. **base.AgentManager 初始化**
ceilometer/agent/base.py下找到AgentManager的初始化部分代码，部分如下所示：

``` python
from stevedore import extension

...
def __init__(self, namespaces, pollster_list, group_prefix=None):
    ...
    # 从配置文件中动态加载收集器Pollster
    extensions = (self._extensions('poll', namespace).extensions
                   for namespace in namespaces)
    ... 
    
    self.extensions = list(itertools.chain(*list(extensions))) + list(
         itertools.chain(*list(extensions_fb)))
    # 从配置文件中动态加载资源发现器Discover
    self.discovery_manager = self._extensions('discover')
    ...

 @staticmethod
 def _get_ext_mgr(namespace):
     def _catch_extension_load_error(mgr, ep, exc):
       ...

     return extension.ExtensionManager(
         namespace=namespace,
         invoke_on_load=True,
         on_load_failure_callback=_catch_extension_load_error,
     )

 def _extensions(self, category, agent_ns=None):
     namespace = ('ceilometer.%s.%s' % (category, agent_ns) if agent_ns
                  else 'ceilometer.%s' % category)
     return self._get_ext_mgr(namespace)
```

- 可以看出\_extensions函数中通过[stevedore](http://docs.openstack.org/developer/stevedore/)加载了配置文件中的对应namespace下的插件；
- 初始化过程init中，主要做了两件事情：
    - 加载ceilometer.poll.central下的插件到self.extensions，即上面所说的收集器Pollster；
    - 加载ceilometer.discover下的插件到self.discovery\_manager，即上面所说的资源发现器Discover。
- 而在配置文件setup.cfg中可以看到对应的定义，截取部分在这里：

``` yaml
...
ceilometer.poll.central =
      ip.floating = ceilometer.network.floatingip:FloatingIPPollster
      image = ceilometer.image.glance:ImagePollster
      image.size = ceilometer.image.glance:ImageSizePollster
      ...
...   
ceilometer.discover =
      local_instances = ceilometer.compute.discovery:InstanceDiscovery
      endpoint = ceilometer.agent.discovery.endpoint:EndpointDiscovery
      tenant = ceilometer.agent.discovery.tenant:TenantDiscovery
      ...
 ...
```

### 4. **base.AgentManager 启动**
了解AgentManager初始化之后，再来看启动部分的代码实现：

``` python
def start(self):
    # 读取pipeline.yaml配置文件
    self.polling_manager = pipeline.setup_polling()
    ...
    # 
    self.pollster_timers = self.configure_polling_tasks()
    ...
...
```

下面分别介绍这两行代码的功能：

- pipeline.setup\_polling中加载解析pipeline.yaml文件，来看一个pipeline.yaml中的示例，更多内容：[pipeline](http://docs.openstack.org/developer/ceilometer/architecture.html#pipeline-manager)；

``` yaml
---
  sources:
      - name: meter_source
        interval: 600
        meters:
            - "*"
        sinks:
            - meter_sink
      - name: cpu_source
        ...
      ...
  sinks:
      - name: meter_sink
        transformers:
        publishers:
      ...
  ...
```

ceilometer中用pipeline配置文件的方式定义meter数据从收集到处理到发送的过程，在Polling Agent中我们只需要关心sources部分，在上述pipeline.setup\_polling()中读取pipeline文件并解析封装其中的sources内容，供后面使用。

- configure\_polling\_tasks代码如下：

``` python
def configure_polling_tasks(self):
    ...
    pollster_timers = []
    # 创建PollingTask
    data = self.setup_polling_tasks()
    # PollingTask定时执行
    for interval, polling_task in data.items():
        delay_time = (interval + delay_polling_time if delay_start
                      else delay_polling_time)
        pollster_timers.append(self.tg.add_timer(interval,
                               self.interval_task,   #PollsterTask执行内容
                               initial_delay=delay_time,
                               task=polling_task)) 
    ...
    return pollster_timers
```

其中，setup\_polling\_tasks中新建PollingTask，并根据上一步中封装的sources内容，将每一个收集器Pollster根据其interval设置分配到不同的PollingTask中，interval相同的收集器会分配到同一个PollingTask中。之后每个PollingTask都根据其运行周期设置Timer定时执行。
注意，其中interval\_task函数指定timer需要执行的任务。

### 5. **PollingTask 执行**
上边我们了解到PollingTask会定时执行，而interval\_task中定义了他的内容：

``` python
@staticmethod
def interval_task(task):
     task.poll_and_notify()

def poll_and_notify(self):
    ...
    for source_name in self.pollster_matches:
       # 循环处理PollingTask中的每一个收集器Pollster
       for pollster in self.pollster_matches[source_name]:
           ...
           # Discover发现可用的数据源
           if not candidate_res and pollster.obj.default_discovery:
                candidate_res = self.manager.discover(
                    [pollster.obj.default_discovery], discovery_cache)

            ...   #做一些过滤

             try:
                 # 从数据源处拉取采样数据
                 samples = pollster.obj.get_samples(
                     manager=self.manager,
                     cache=cache,
                     resources=polling_resources
                 )
                 sample_batch = []

                 # 发送数据到消息队列
                 for sample in samples:
                     sample_dict = (
                         publisher_utils.meter_message_from_counter(
                             sample, self._telemetry_secret
                         ))
                     if self._batch:
                         sample_batch.append(sample_dict)
                     else:
                         self._send_notification([sample_dict])

                 if sample_batch:
                     self._send_notification(sample_batch)

            except 
                ...
    
```

可以看出，在这段代码中完成了比较核心的几个步骤：
1.  资源发现器Discover发现可用数据源；
2.  收集器Pollster拉取采样数据；
3.  发送数据到消息队列。

### 6. **Pollster示例**
上面介绍了Polling Agent中如何是如何加载Pollster执行数据的收集工作的。下面以获取image基本信息的ImagePollster为例，看一下具体的实现：

``` python
class _Base(plugin_base.PollsterBase):

     @property
     def default_discovery(self):
         return 'endpoint:%s' % cfg.CONF.service_types.glance

     def get_glance_client(ksclient, endpoint):
         ...
    
     def _get_images(self, ksclient, endpoint):
         client = self.get_glance_client(ksclient, endpoint)
         ...
         return client.images.list(filters={"is_public": None}, **kwargs)

     def _iter_images(self, ksclient, cache, endpoint):
         key = '%s-images' % endpoint
         if key not in cache:
             cache[key] = list(self._get_images(ksclient, endpoint))
         return iter(cache[key])
```

``` python
class ImagePollster(_Base):
    def get_samples(self, manager, cache, resources):
        for endpoint in resources:
            for image in self._iter_images(manager.keystone, cache, endpoint):
                yield sample.Sample(
                    name='image',
                    type=sample.TYPE_GAUGE,
                    unit='image',
                    ...
                )

```
像上边介绍过的，Pollster需要实现两个接口:

- default\_discovery：指定默认的discover
- get\_samples：对每个image获取采样数据

### 7. **Discover示例**

``` python
class EndpointDiscovery(plugin.DiscoveryBase):
    """Discovery that supplies service endpoints.
    """

    @staticmethod
    def discover(manager, param=None):
        endpoints = manager.keystone.service_catalog.get_urls(
            service_type=param,
            endpoint_type=cfg.CONF.service_credentials.os_endpoint_type,
            region_name=cfg.CONF.service_credentials.os_region_name)
        if not endpoints:
            LOG.warning(_LW('No endpoints found for service %s'),
                        "<all services>" if param is None else param)
            return []
        return endpoints
```
可以看到上面的ImagePollster所指定的Discover中慧从keystone获取所有的glance的endpoint列表, 这些endpoint列表最终会作为数据来源传给ImagePollster的get_samples

### 8. **其他**
除了上述提到的内容外，还有一些点需要注意：

- polling agent采用[tooz](http://docs.openstack.org/developer/tooz/)实现了agent的高可用，不同的agent实例之间通过tooz进行通信。在base.AgentManager的初始化和运行过程中都有相关处理，其具体实现可以在ceilometer/coordination.py中看到。；
- 除了上述动态加载Pollster和Discover的方式外，pipeline还提供的静态的加载方式，可以在pipeline文件中通过sources的resources和discovery参数指定。




## 核心实体

### **AgentManger**
- oslo.service 子类；
- polling agent 的核心实现类；
- 函数：
    - 定义agent的初始化、启动、关闭等逻辑；
    - 定义读取扩展的相关函数；
    - 定义pollingtask相关函数。
- 成员
    - self.extensions：从setup.cfg中读入的pollster插件；
    - self.discover\_manager：从setup.cfg中读入的discover插件；
    - self.context：oslo\_context 的RequestContext；
    - self.partition\_coordinator：用于active-active高可用实现的PartitionCoordinator；
    - self.notifier：oslo\_messaging.Notifier 用于将收集的meter信息发送到消息队列；
    - self.polling\_manager: PollingManager实例，主要用其通过pipeline配置文件封装的source；
    - self.group\_prefix：用来计算partition\_coordination的group\_id。


### **PollingTask**
- Polling task for polling samples and notifying
- 函数：
    - add：向pollstertask中增加pollster；
    - poll\_and\_notify：发现资源，拉取采样数据，将其转化成meter message后发送到消息队列；
- 成员：
    - self.manager: 记录当前的agent\_manager；
    - self.pollster\_matches，value为set类型的dic，用来记录source到pollster set的映射；
    - self.resources用来记录“source\_name-pollster” key 到Resource的映射；
    - self.\_batch 是否要批量发送；
    - self.\_telemetry\_secret : 配置文件中的\_telemetry\_secret；

## 参考
官方文档：[Ceilometer Architecture](http://docs.openstack.org/developer/ceilometer/architecture.html)
Github：[Ceilometer Source Code](https://github.com/openstack/ceilometer)


