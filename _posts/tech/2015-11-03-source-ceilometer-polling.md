---
layout: post
title: Ceilometer 源码学习 - Polling Agent
category: 技术
tags: [Ceilometer, Source]
keywords: Ceilometer, Central Agent, Compute Agent, Source
---
## 简介
Ceilometer是Openstack中用于数据采集的基础设施，包括多个组件：Central Agent，Compute Agent，Notification Agent，Collector等。其中Central Agent和Compute Agent分别运行在Controller和Compute机器上，通过定期调用其他服务的api来完成数据采集。由于二者的区别只是其所负责的数据来源，这里我们统称为Polling Agent。


## 需求导向
Polling Agent的功能很简单：

> **周期性地向其他服务主动拉取需要的数据，并将数据发送到消息队列。**

站在设计者的角度，要完成上述功能，需要面对有如下几个基本问题：
1. 怎么执行拉取
2. 向哪些服务收集数据
3. 对于某个服务收集哪些数据以及如何收集

下面分别针对上述问题依次介绍Ceilometer的实现方式:

1. **常驻进程**：自然的我们需要一个常驻进程来完成上述调度任务，基本操作包括    
    
    - 记录全局状态
    - 周期性的触发
    - 负责消息的发送
2. **插件形式**：Ceilometer中用定义插件的方式定义不同的收集器（Pollster），程序从配置文件中获得需要加载哪些收集器收集数据，通过插件形式解决问题2是一个很好的选择，因为：
    
    - python对插件的良好支持：[stevedore](http://docs.openstack.org/developer/stevedore/)
    - 简化核心逻辑
    - 方便扩展
3.  **共同基类**：数据来源多种多样，针对不同的数据来源的数据方式又各有不同，但他们需要完成同样的的动作，Ceilometer中设计Pollster的共同基类，定义如下接口，是每个Pollster都是要实现的：
    
    - 默认获取数据来源的方式：default_discovery
    - 拉取数据：get_samples
    
## 流程简介
正是由于上面所说的实现方式使得Polling Agent的核心逻辑变得非常简单，不需要关注具体的数据收集过程，而将自己解放成一个调度管理者，下面将简单介绍实现逻辑。在此之前为了方便说明，介绍下其中涉及到的角色或组件:

- **AgentManager**：Polling Agent的核心类，Central Agent和Compute Agent用不同的参数初始化AgentManager。
- **Pollster**：数据收集器，以插件的形式动态载入
- **Discover**：以一定的方式发现数据源Resource
- **Pipeline**：Ceilometer通过pipleline.yml文件的形式定义了所收集数据的一系列转换发送操作，很好的降低了各组件的耦合性和系统的复杂性。该文件中以sources标签定义了不同数据的分组信息，这部分是在Polling Agent中需要关心的。
- **PollingTask**：望文生义，表示一个拉取数据的任务
- **Resource**：代表一个可提供数据的源，如一个镜像或一个虚拟机实例

**基本流程**如下：

- AgentManger初始化，主要完成如下动作
    
    - 从配置文件中动态加载所有的收集器插件Pollster
    - 从配置文件中加载已有的资源发现器插件Discover
- AgentManger启动
    
    - 从pipeline文件读取sources信息
    - 为每一个从文件中加载的Pollster根据Pipeline信息分配一个PollingTask
    - 为每个PollingTask建立Timer执行
- PollingTask执行
    
    - 通过Pollster的default_discovery定义，从已加载的资源发现器Discover中选取合适的一个
    - 调用Discover的discovery获取Resource
    - 调用Pollster的get_samples从Resource中获得采样数据
    - 发送给消息队列

## 代码细节
接下来从代码层面详细介绍上述逻辑

### 1. **入口**
- Ceilometer采用[pbr](http://docs.openstack.org/developer/pbr/)的方式管理配置
- setup.cfg中定义了Polling Agent 入口位置

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

- prepare_service中做了一些初始化工作，如初始化日志，加载配置文件等
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

- 可以看出_extensions函数中通过[stevedore](http://docs.openstack.org/developer/stevedore/)加载了配置文件中的对应namespace下的插件
- 初始化过程init中，主要做了两件事情
    - 加载ceilometer.poll.central或ceilometer.builder.poll下的插件到computeself.extensions，即上面所说的收集器Pollster
    - 加载ceilometer.discover下的插件到self.discovery_manager，即上面所说的资源发现器Discover
- 而在配置文件setup.cfg中可以看到对应的定义，截取部分在这里

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

下面分别介绍这两句的功能：

- pipeline.setup_polling中加载解析pipeline.yaml文件，看一个pipeline.yaml中的示例，更多内容：[pipeline](http://docs.openstack.org/developer/ceilometer/architecture.html#pipeline-manager)

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

ceilometer中用pipeline配置文件的方式定义meter数据从收集到处理到发送的过程，在Polling Agent中我们只需要关心sources部分，在上述pipeline.setup_polling()中读取pipeline文件并解析封装其中的sources内容，供后边使用

- configure_polling_tasks代码如下：

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
     self.tg.add_timer(cfg.CONF.coordination.heartbeat,
                       self.partition_coordinator.heartbeat)

     return pollster_timers
```

其中，setup_polling_tasks中新建PollingTask，并根据上一步中封装的sources内容，将每一个收集器Pollster分配到不同的PollingTask中。之后每个PollingTask都会设置Timer定时执行。
注意，其中interval_task函数指定timer需要执行的任务。

### 5. **PollingTask 执行**
上边我们了解到PollingTask会定时执行，而interval_task中定义了他的内容：

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
1.  资源发现器Discover发现可用数据源
2.  收集器Pollster拉取采样数据
3.  发送数据到消息队列


## 核心实体

#### **AgentManger**
- oslo.service 子类
- polling agent 的核心实现类
- agent的初始化，启动，关闭
- extension相关函数
- pollingtask相关函数
- 成员
    - self.extensions：从setup.cfg中读入的pollster插件
    - self.discovery_manager：从setup.cfg中读入的discover插件
    - self.context：oslo_context 的RequestContext
    - self.partition_coordinator：用于active-active高可用实现的PartitionCoordinator
    - self.notifier：oslo_messaging.Notifier 用于将收集的meter信息发送到消息队列
    - self.polling_manager: PollingManager实例，主要用其通过pipeline配置文件封装的source
    - self.group_prefix：用来计算partition_coordination的group_id

#### **PollingTask**
- Polling task for polling samples and notifying
- 函数
    - add：向pollstertask中增加pollster
    - poll_and_notify：从resources poll sample，转化成meter message后发送给notification agent
- 成员
    - self.manager: 记录当前的agent_manager
    - self.pollster_matches，value为set类型的dic，用来记录source到pollster set的映射
    - self.resources用来记录“source_name-pollster”  key 到Resource的映射
    - self._batch 是否要批量发送
    - self._telemetry_secret : 配置文件中的_telemetry_secret

#### **Resources**
- 支持从pipeline的source项定义的_resource和_discovery直接读取resources
- 成员
    - agent_manager: 记录当前的agent_manager
    - _resources
    - _discovery
    - blacklist
    - last_dup

#### **SampleSource**
- 代表pipeline 中的一个source
- 成员
    - self.name
    - self.sinks
    - self.interval
    - self.resources list
    - self.discovery list

#### **PollingManager**
- Polling manager sets up polling according to config file.
- 成员
    - self.sources：同过pipeline配置文件封装的SampleSource

#### **PartitionCoordinator**
- 使用tooz库来实现组中各实例的负载均衡
- 成员
    - self._coordinator：tooz.coordination
    - self._groups: 当前实例所在组
    - self._my_id：唯一id

## 依赖介绍
Polling Agent 中有大量的依赖库，下面列出主要的依赖供参考：

- oslo.i18n 
    -  contain utilities for working with internationalization  features
    -  http://docs.openstack.org/developer/oslo.i18n/api.html
- oslo.config
    - library for parsing configuration options from the command line and configuration files
    - http://docs.openstack.org/developer/oslo.config/
- oslo.log
    - provides standardized configuration for all openstack projects. It also provides custom formatters, handlers and support for context specific logging (like resource id’s etc).`
    - http://docs.openstack.org/developer/oslo.log/usage.html
- oslo.messaging
    - The Oslo messaging API supports RPC and notifications over a number of different messaging transports.
    - http://docs.openstack.org/developer/oslo.messaging/transport.html?highlight=set_transport_defaults#oslo_messaging.set_transport_defaults
- oslo.service
    - oslo.service provides a framework for defining new long-running services using the patterns established by other OpenStack applications. It also includes utilities long-running applications might need for working with SSL or WSGI, performing periodic operations, interacting with systemd, etc.
    - http://docs.openstack.org/developer/oslo.service/
- stevedore
    - http://docs.openstack.org/developer/stevedore/
- tooz
    - http://docs.openstack.org/developer/tooz/

## 参考
官方文档：http://docs.openstack.org/developer/ceilometer/architecture.html
Github：https://github.com/openstack/ceilometer


