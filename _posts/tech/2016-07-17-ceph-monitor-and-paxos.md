---
layout: post
title: Ceph Monitor and Paxos
category: 技术
tags: [Ceph, Ceph Monitor, Paxos, 源码, 实现, 源码介绍, 分布式存储, 元信息管理, 一致性协议]
keywords: Ceph, Ceph Monitor, Paxos, 源码, 实现, 源码介绍, 分布式存储, 元信息管理, 一致性协议
---

Ceph Monitor集群作为Ceph中的元信息管理组件，基于改进的Paxos算法，对外提供一致性的元信息访问和更新服务。本文首先介绍Monitor在整个系统中的意义以及其反映出来的设计思路；之后更进一步介绍Monitor的任务及所维护数据；最后介绍其基于Paxos的实现细节和改进点。



## **定位**

RADOS毋庸置疑是Ceph架构中的重中之重，Ceph所提供的对象存储，块存储及文件存储都无一例外的以RADOS为基石和最终的存储方案。论文中将RADOS描述为：”A Scalable, Reliable Storage Service for Petabyte-scaleStorage Clusters“，可见其对扩展性的重视。而与扩展性息息相关的首先就是分布式存储设计中必须要面对的元信息管理问题，即通过key找到数据所在的节点。

元信息管理的实现无外乎有以下两种方式，各自的优缺点也显而易见：

- 有中心的元信息管理：由中心节点来负责整个集群元信息的检测、更新和维护：
  - 优点：设计简洁清晰，容易实现，且元信息变化时更新相对及时；
  - 缺点：单点故障及中心节点本身的处理能力对集群扩展的限制；
- 对等的元信息管理：将集群元信息的处理负担分散到集群的所有节点及Client上去：
  - 优点：无单点故障，水平扩展能力；
  - 缺点：状态变化的消息传播缓慢（如采用Gossip），集群变大时更为明显；

可以看出，无论哪种方式，都不可避免的限制了集群的可扩展性。针对这种情况，CEPH做出了自己的选择：**有中心节点Monitor**， 但其在以下几个方面不同于上面提到的有中心方式：

- CRUSH算法：输入key值和当前集群状态，输出数据所在OSDs，从而极大的减少Monitor需要处理的元信息量。
- Cluster：Monitor采用集群的方式，在一定程度上缓解了单点问题及中心节点的处理能力限制问题。
- 智能存储节点：Ceph通过给与OSD更多的”智能“，来分担Monitor的元信息管理负担：
  - OSD及Client缓存元信息，实现大多数情况下的点对点数据访问；
  - OSD自身完成数据备份、强一致性访问、故障检测、数据迁移及故障恢复，从而极大的减少了Monitor的工作；
  - OSD之间的心跳检测感知彼此的元信息版本号并主动更新落后节点。得益于此，Monitor对OSD的元信息更新可以不十分及时。
- 良好的Monitor实现，本文会着重介绍这部分的内容。




## **任务及数据**

通过上面的描述可知，Montor负责维护整个集群的元信息及其更新，这里的元信息包括：

- **OSD Map**：其中主要记录OSD列表及各自的状态；
- **Monitor Map**：记录Monitor本身的节点信息及epoch；
- **PG Map**：记录各个PG的状态
- **CRUSH Map**：记录CRUSH算法所需要的节点及规则信息

Ceph的设计思路是尽可能由更“智能”的OSD及Cilent来降低Monitor作为中心节点的负担，所以Monitor需要介入的场景并不太多，主要集中在以下几点：

- Client首次访问数据需要从Monitor获取当前的集群状态和CRUSH信息；
- 发生故障时，OSD节点自己或者依靠同伴向Monitor报告故障信息；
- OSD恢复，加入集群时，会首先报告Monitor并获得当前的集群状态；




## **一致性与Paxos**

上面提到，Monitor以集群的形式对外提供服务。为了使集群能够对外提供一致性的元信息管理服务，Monitor内部基于Paxos实现了自己的一致性算法。我们知道，Paxos论文中只着重介绍了集群如何对某一项提案达成一致，而距离真正的工程实现还有比较大的距离，众多的细节和方案需要实现中考虑和选择。

- 加入选主阶段，同时只会有一个提案；

- 引入租约，将读压力分散到所有的Monitor节点上，并成就其水平扩展能力。在Ceph Monitor这种读多写少的场景下显得格外有用；
- 聚合更新，Monitor leader将多条更新信息聚合到单条消息中，使得更新消息的量级与机器规模无关。而能够实现这一点也正是得益于上述的智能存储节点。

本文假设读者已经了解Paxos算法的基本过程，了解Prepare、Promise、Commit、Accept、Quorum等概念。注意Ceph Monitor中的accept概念其实相当于Paxos中的Promise。



## **实现**

下面将分别从Ceph Monitor的架构，其初始化、选主、Collect过程、读写过程、消息处理、状态转换六个方面介绍Ceph Monitor的实现：

#### **架构**

![Ceph Monitor Architecture](http://i.imgur.com/pmj3VAj.png)

上图所示是Ceph Monitor的结构图，自下而上有以下几个部分组成：

- DBStore层：数据的最终存储组件，以leveldb为例；


- Paxos层：在集群上对上层提供一致的数据访问逻辑，在这一层看来所有的数据都是kv；上层的多中PaxosService将不同的组件的map数据序列化为单条value，公用同一个paxos实例。
- PaxosService层：每个PaxosService代表集群的一种状态信息。对应的，Ceph Moinitor中包含分别负责OSD Map，Monitor Map, PG Map, CRUSH Map的几种PaxosService。PaxosService负责将自己对应的数据序列化为kv写入Paxos层。Ceph集群所有与Monitor的交互最终都是在调用对应的PaxosSevice功能。



#### **1，初始化**

![Ceph Monitor Initial](http://i.imgur.com/oPBqw19.png)

可以看出，Ceph Monitor在启动节点端，主要做了三件事情：

- 自下而上依次初始化上述的三大组成部分：DBStroe，Paxos，PaxoService
- 初始化Messager，并向其中注册命令执行回调函数。Messager是Ceph中的网络线程模块，Messager会在收到网络请求后，回调Moniotor在初始化阶段注册命令处理函数。
- Bootstrap过程在整个Monitor的生命周期中被反复调用，下面就重点介绍一下这个过程。

**Boostrap**

- 执行Boostrap的Monitor节点会首先进入PROBING状态，并开始向所有monmap中其他节点发送Probing消息。
- 收到Probing消息的节点执行Boostrap并回复Probing_ack，并给出自己的last_commit以及first_commit，其中first_commit指示当前机器的commit记录中最早的一条，其存在使得单个节点上可以仅保存最近的几条记录。
- 收到Probing_ack的节点发现commit数据的差距早于对方first_commit，则主动发起全同步，并在之后重新Boostrap
- 收到超过半数的ack并不需要全同步时，则进入选主过程。

上述交互过程见下图：

![Ceph Monitor Boostrap](http://i.imgur.com/aCN4fig.png)

可以看出，经过了Boostrap过程，可以完成以下两步**保证**：

- 可以与超过半数的节点通信；

- 节点间commit数据历史差距不大。

  ​



#### **2，选主**

接着，节点进入选主过程：

- 将election_epoch加1，向Monmap中的所有其他节点发送Propose消息；
- 收到Propose消息的节点进入election状态并仅对有更新的election_epoch且rank值大于自己的消息答复Ack。这里的rank简单的由ip大小决定；
- 发送Propose的节点统计收到的Ack数，超时时间内收到Monmap中大多数的ack后可进入victory过程，这些发送ack的节点形成quorum；

**victory**

- election_epoch加1，可以看出election_epoch的奇偶可以表示是否在选举轮次；
- 向quorum中的所有节点发送VICTORY消息，并告知自己的epoch及quorum；
- 当前节点完成Election，进入Leader状态；
- 收到VICTORY消息的节点完成Election，进入Peon状态

上述交互过程见下图：

![Ceph Monitor Election](http://i.imgur.com/INz6V5X.png)

可以看出，Monitor选主过程的**目的**如下：

- 简单的根据ip大小选出leader，而并没有考虑commit数据长度；
- 确定quroum，在此之前所有的操作都是针对Monmap内容的，直到这里才有了quroum，之后的所有Paxos操作便基于当前这个quorum了。



#### 3，Collect阶段



#### **4，读写流程**



#### **5，状态**



#### 6，**消息处理**



## **比较**

- 租约

- 主发起propose

- 用boostrap来简化实现quroum

- 选主只选ip最大的，而在collect过程中才将leader数据更新到最新

  ​











### **参考：**

http://www.cnblogs.com/wuhuiyuan/p/4734012.html