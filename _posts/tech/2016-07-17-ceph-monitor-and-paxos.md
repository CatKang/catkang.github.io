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

通过上面的描述可知，Montor负责维护整个集群的元信息及其更新，这里的元信息包括记录数据分布的OSDMap，记录Monitor状态的MonitorMap，以及Ceph集群所需要的其他信息。Ceph的设计思路是尽可能由更“智能”的OSD及Cilent来降低Monitor作为中心节点的负担，所以Monitor需要介入的场景并不太多，主要集中在以下几点：

- Client首次访问数据需要从Monitor获取当前的集群状态和CRUSH信息；
- 发生故障时，OSD节点自己或者依靠同伴向Monitor报告故障信息；
- OSD恢复，加入集群时，会首先报告Monitor并获得当前的集群状态；




## **实现简介**

![Ceph Monitor Architecture](http://i.imgur.com/pmj3VAj.png)

Ceph Monitor的结构如上图所示，总体上分为PaxosService、Paxos、Leveldb三层，其中PaxosService层将不同的元信息封装成单条kv，Leveldb层则作为最终的数据和log存储。本文的关注重点在Paxos层，Paxos层对上层提供一致性的数据访问逻辑，在其看来所有的数据都是kv，上层的不同的元信息在这里共用同一个Paxos实例。基于Paxos算法，通过一系列的节点间通信来实现集群间一致性的读写以及故障检测和恢复。Paxos将整个过程分解为多个阶段，每个阶段达成一定的目的进而进入不同的状态。通过分层的思路使得整个实现相对简单清晰。

#### **Boostrap阶段：**

节点启动或者之后的多数故障情况发生时都会首先进入Boostrap过程，Boostrap过程会向其他节点发送探测消息，感知彼此的数据新旧，并对差距较大的节点进行全同步。经过这个过程可以有如下保证：

- 可以与超过半数的节点通信
- 节点间的数据差距不大

#### **选主阶段：**

- 选出Leader，简单的根据彼此的ip来进行投票，并没有考虑数据长度
- 确定Quorum：即大多数，在此之前所有的操作都是针对MonitorMap中所有Monitor节点的，直到这里才有了Quorum，之后的所有Paxos操作便基于当前这个Quorum了。

#### **Recovery阶段：**

在这一过程中，刚选出的Leader收集Quorum当前的Commit位置，并更新整个集群。

- 集群信息一致并更新到最新
- 集群可用

#### **读写阶段：**

- Leader通过两阶段提交完成数据提交，并更新Follower的租约。
- 在租约内的所有Follower可以对外处理读请求。





## **一致性与Paxos**

为了使集群能够对外提供一致性的元信息管理服务，Monitor内部基于Paxos实现了自己的一致性算法。我们知道，Paxos论文中只着重介绍了集群如何对某一项提案达成一致，而距离真正的工程实现还有比较大的距离，众多的细节和方案需要实现中考虑和选择。通过上述对实现的简述，可以看出Ceph Monitor的Paxos实现版本中有许多自己的选择和权衡，总结如下：

- **用Boostrap来简化实现Quorum**：与很多其他的一致性协议实现不同，Ceph Monitor的Quorum是在选主过程结束后就已经确定了的，之后所有Paxos过程都是针对这个Quorum中的节点，需要收到全部答复。任何错误或节点加入退出，都将导致重新的Boostrap过程。这样，Monitor很大的简化了Paxos的实现，但在Quorum变动时会有较大不必要的开销。考虑到Quorum变动相对于读写操作非常少见，因此这种选择也不失明智。
- **仅依据ip选主**：而在Recovery过程中才将Leader数据更新到最新。将选主和数据更新分解到两个阶段。
- **主发起propose**：只有Leader可以发起Propose，并且每次一个值；
- **租约**：将读压力分散到所有的Monitor节点上，并成就其水平扩展能力。在Ceph Monitor这种读多写少的场景下显得格外有用；
- **聚合更新**: 除维护Monitor自身元数据的MonitorMap外，其他PaxosService的写操作均会积累一段时间，合并到一条更新数据中。从而降低对Monitor集群的更新压力，当然可以这么做得益于更智能的OSD节点，他们之间会发现元数据的不一致并相互更新。


本文重点介绍了Ceph Monitor的Paxos实现选择，并简要介绍了其实现阶段和目的。更详细的实现过程请见下一篇博文：[Ceph Monitor实现]()



### **参考：**

[RADOS: A Scalable, Reliable Storage Service for Petabyte-scale Storage Clusters](http://ceph.com/papers/weil-rados-pdsw07.pdf)

[CEPH: RELIABLE, SCALABLE, AND HIGH-PERFORMANCE DISTRIBUTED STORAGE](http://ceph.com/papers/weil-thesis.pdf)

[SOURCE CODE](https://github.com/ceph/ceph)

[分布式存储系统之元数据管理的思考](http://www.cnblogs.com/wuhuiyuan/p/4734012.html)

[CEPH ARCHITECTURE](http://docs.ceph.com/docs/master/architecture)





