---
layout: post
title: Ceilometer 源码学习 - Central Agent and Compute Agent
---

# Ceilometer 源码学习 - Central Agent and Compute Agent

## 简介
Ceilometer是Openstack中用于数据采集的基础设施，包括多个组件：Central Agent，Compute Agent，Notification Agent，Collector等。其中Central Agent和Compute Agent分别运行在Controller和Compute机器上，通过定期调用其他服务的api来完成数据采集。由于二者的区别只是其所负责的数据来源，这里我们统称为Polling Agent。


## 需求导向
Polling Agent的功能很简单：
> 周期性地向其他服务主动拉取需要的数据，并将数据发送到消息队列。

站在设计者的角度，要完成上述功能，需要面对有如下几个基本问题：
1. 怎么执行拉取
2. 向哪些服务收集数据
3. 对于某个服务收集哪些数据以及如何收集

下面分别针对上述问题介绍依次Ceilometer的实现方式
1. **常驻进程**：自然的我们需要一个常驻进程来完成上述调度任务，基本操作包括
    - 记录全局状态
    - 周期性的触发
    - 负责消息的发送
2. **插件形式**：Ceilometer中用定义插件的方式定义不同的收集器（Pollster），程序从配置文件中获得需要加载哪些收集器收集数据
    - 通过插件形式解决问题2是一个很好的选择，因为：
        - python对插件的良好支持：[stevedore](http://docs.openstack.org/developer/stevedore/)
        - 简化核心逻辑
        - 方便扩展
3.  **共同基类**：数据来源多种多样，针对不同的数据来源的数据方式又各有不同，但他们需要完成同样的的动作，Ceilometer中设计Pollster的共同基类，定义如下接口，是每个Pollster都是要实现的：
    - 默认获取数据来源的方式：default_discovery
    - 拉取数据：get_samples
    
## 流程简介
正是由于上面所说的实现方式使得Polling Agent的核心逻辑变得非常简单，不需要关注具体的数据收集过程，而将自己解放成一个调度管理者，下面将简单介绍实现逻辑。在此之前为了方便说明，介绍下其中涉及到的角色或组件
- **AgentManager**：Polling Agent的核心类，Central Agent和Compute Agent用不同的参数初始化AgentManager。
- **Pollster**：数据收集器，以插件的形式动态载入
- **Discover**：以一定的方式发现数据源Resource
- **Pipeline**：Ceilometer通过pipleline.yml文件的形式定义了所收集数据的一系列转换发送操作，很好的降低了各组件的耦合性和系统的复杂性。该文件中以sources标签定义了不同数据的分组信息，这部分是在Polling Agent中需要关心的。
- **PollingTask**：望文生义，表示一个拉取数据的任务
- **Resource**：代表一个可提供数据的源，如一个镜像或一个虚拟机实例

**基本流程**如下：
- AgentManger初始化，主要完成如下动作
    - 从配置文件中加载需要的收集器Pollster
    - 从配置文件中加载已有的资源发现器Discover
- AgentManger启动
    - 从pipeline文件读取sources信息
    - 为每一个从文件中加载的Pollster根据Pipeline信息分配一个PollingTask
    - 为每个PollingTask建立Timer执行
- PollingTask执行
    - 通过Pollster的default_discovery定义，从已加载的资源发现器Discover中选取合适的一个
    - 调用Discover的discovery获取Resource
    - 调用Pollster的get_samples从Resource中获得采样数据
    - 发送给消息队列

```flow
st=>start: Start
op_load=>operation: 配置文件加载收集器Pollster及资源发现器Discover
op_run=>operation: 初始化并启动PollingTask
cond_dis=>condition: Discover发现数据源?
cond_poll=>condition: Pollster获得采样数据?
op_send=>operation: 发送数据到消息队列
op_wait=>operation: Wait
cond_timer=>condition: Time's Up

st->op_load->op_run->cond_timer
cond_timer(yes)->cond_dis
cond_timer(no)->cond_timer
cond_dis(yes)->cond_poll
cond_dis(no)->cond_timer
cond_poll(yes)->op_send->cond_timer
cond_poll(no)->cond_timer
```



## 代码细节
#### 核心实体
#### 流程
#### 依赖介绍

## 参考


