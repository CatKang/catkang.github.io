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




## **实现**

上面提到，Monitor以集群的形式对外提供服务。为了使集群能够对外提供一致性的元信息管理服务，Monitor内部基于Paxos实现了自己的一致性算法。我们知道，Paxos论文中只着重介绍了集群如何对某一项提案达成一致，而距离真正的工程实现还有比较大的距离，众多的细节和方案需要实现中考虑和选择。下面就讲分别从Ceph Monitor的架构，其初始化过程、选主过程、Recovery过程、读写过程、状态转换六个方面介绍Ceph Monitor的实现。

本章节假设读者已经了解Paxos算法的基本过程，了解Prepare、Promise、Commit、Accept、Quorum等概念。注意Ceph Monitor中的accept概念其实相当于Paxos中的Promise。



#### **1，架构**

![Ceph Monitor Architecture](http://i.imgur.com/pmj3VAj.png)

上图所示是Ceph Monitor的结构图，自下而上有以下几个部分组成：

- DBStore层：数据的最终存储组件，以leveldb为例；


- Paxos层：在集群上对上层提供一致的数据访问逻辑，在这一层看来所有的数据都是kv；上层的多中PaxosService将不同的组件的map数据序列化为单条value，公用同一个paxos实例。
- PaxosService层：每个PaxosService代表集群的一种状态信息。对应的，Ceph Moinitor中包含分别负责OSD Map，Monitor Map, PG Map, CRUSH Map的几种PaxosService。PaxosService负责将自己对应的数据序列化为kv写入Paxos层。Ceph集群所有与Monitor的交互最终都是在调用对应的PaxosSevice功能。



#### **2，初始化**

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

**目的**：可以看出，经过了Boostrap过程，可以完成以下两步保证：

- 可以与超过半数的节点通信；

- 节点间commit数据历史差距不大。

  ​



#### **3，选主**

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

**目的**：可以看出，Monitor选主过程的目的如下：

- 简单的根据ip大小选出leader，而并没有考虑commit数据长度；
- 确定quroum，在此之前所有的操作都是针对Monmap内容的，直到这里才有了quroum，之后的所有Paxos操作便基于当前这个quorum了。



#### **4，RECOVERY阶段**

经过了上述的选主阶段，便确定了leader，peon角色，以及quorum成员。在真正的开始一致性读写之前，还需要经过RECOVERY阶段：

- leader生成新的更大的新的pn，并通过collect消息发送给所有的quorum中成员；
- 收到collect消息的节点当pn大于自己已经accept的最大pn时，接受并通过last消息返回自己的commit位置及uncommitted；
- leader收到last消息，更新自己的commit位置及数据并重复提升pn发送collect消息的过程，指导quorum中所有的节点都接受自己。
- 同时leader会根据的commit及uncommitted位置，分别用commit消息和begin消息更新对应的peon；
- leader向quorum中所有节点发送lease消息，使整个集群进入active状态。

这个阶段的交互过程如下图：

![Ceph Monitor Collect](http://i.imgur.com/4EsQ1xe.png)

**目的**：

- 将leader及quorum节点的数据更新到最新且一致；
- 整个集群进入可用状态。



#### **5，读写流程**

经过了上面的初始化、选主、恢复阶段整个集群进入到一个非常正常的状况，终于可以利用Paxos进行一致性地读写了，其中读过程比较简单，在lease内的所有quroum均可以提供服务。而所有的写都会转发给leader，写过程如下：

- leader在本地记录要提交的value，并向quroum中的所有节点发送begin消息，其中携带了要提交的value, accept_pn及last_commit；
- peon收到begin消息，如果accept过更高的pn则忽略，否则将value写入db并返回accept消息。同时peon会将当前的lease过期掉，在下一次收到lease前不再提供服务；
- leader收到**全部**quorum的accept后进行commit。本地commit后向所有quorum节点发送commit消息；
- peon收到commit消息，本地commit数据；
- leader通过lease消息将整个集群带入到active状态。

交互过程如下：

![Ceph Monitor Write](http://i.imgur.com/WnE9Jg1.png)



**目的**：

- 由leader发起propose，并依次完成写入，一个value完成commit才会开始下一个；
- 通过lease分担读压力。

> 数据存储：我们知道commit以后的数据才算真正写入到集群，那么为什么在begin过程中，leader和peon都会将数据写入db呢？这是因为Ceph Montor利用db来完成了log和value两部分数据的存储，而commit时会将log数据反序列化后以value的格式重新存储到db。



#### **6，状态**

在Monitor的生命周期，贯穿于上述各个过程的包括两个层面的状态转换，Monitor自身的状态，以及Monitor进入主从状态后，其Paxos过程中的状态。

##### **Monitor状态转换**

![Ceph Monitor Status](http://i.imgur.com/VmofRlH.png)

- STATE_PROBING：boostrap过程中节点间相互探测，发现数据差距；
- STATE_SYNCHRONIZING：当数据差距较大无法通过后续机制补齐时，进行全同步；
- STATE_ELECTING：Monitor在进行选主
- STATE_LEADER：当前Monitor成为leader
- STATE_PEON：非leader节点



##### **Paxos状态转换**

![Ceph Monitor Paxos Status](http://i.imgur.com/cWYaq0h.png)

- STATE_RECOVERING：对应上述RECOVERING过程；
- STATE_ACTIVE：leader可以读写或peon拥有lease；
- STATE_UPDATING（STATE_UPDATING_PREVIOUS）：向quroum发送begin，等待accept；
- STATE_WRITING（STATE_WRITING_PREVIOUS）：收到accept
- STATE_REFRESH：本地提交并向quorum发送commit；



## **一致性与Paxos**

可以看出Ceph Monitor的Paxos实现版本中有许多自己的选择和权衡，总结如下：

- **租约**：将读压力分散到所有的Monitor节点上，并成就其水平扩展能力。在Ceph Monitor这种读多写少的场景下显得格外有用；
- **主发起propose**：只有leader可以发起propose，并且每次一个值；
- **用boostrap来简化实现quroum**：所有paxos过程都是针对quorum所有节点的，需要quorum正常答复。任何错误或节点加入退出，都将导致重新的boostrap。这样，Monitor很大的简化了Paxos的实现，但在quroum变动时会有较大不必要的开销。考虑到quroum变动相对于读写操作非常少见，因此这种选择也不失明智。
- **选主只选ip最大的**：而在collect过程中才将leader数据更新到最新。将选主和数据更新分解到两个阶段。
- **聚合更新**: 除维护Monitor自身元数据的MonmapMonitor外，其他PaxosService的写操作均会积累一段时间，合并到一条更新数据中。从而降低对Monitor集群的更新压力，当然可以这么做得益于更智能的OSD节点，他们之间会发现元数据的不一致并相互更新。










### **参考：**

RADOS: A Scalable, Reliable Storage Service for Petabyte-scale Storage Clusters: http://ceph.com/papers/weil-rados-pdsw07.pdf

CEPH: RELIABLE, SCALABLE, AND HIGH-PERFORMANCE DISTRIBUTED STORAGE: http://ceph.com/papers/weil-thesis.pdf

SOURCE CODE: https://github.com/ceph/ceph

分布式存储系统之元数据管理的思考: http://www.cnblogs.com/wuhuiyuan/p/4734012.html

CEPH ARCHITECTURE: http://docs.ceph.com/docs/master/architecture/





