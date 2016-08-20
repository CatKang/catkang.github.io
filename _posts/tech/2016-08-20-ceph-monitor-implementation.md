---
layout: post
title: Ceph Monitor实现
category: 技术
tags: [Ceph, Ceph Monitor, Paxos, 源码, 实现, 源码介绍, 分布式存储, 元信息管理, 一致性协议]
keywords: Ceph, Ceph Monitor, Paxos, 源码, 实现, 源码介绍, 分布式存储, 元信息管理, 一致性协议
---


在之前的一篇博客[Ceph Monitor and Paxos](http://catkang.github.io/2016/07/17/ceph-monitor-and-paxos.html)中介绍了Ceph Monitor利用改进的Paxos算法，以集群的形式对外提供元信息管理服务。本文讲分别从Ceph Monitor的架构，其初始化过程、选主过程、Recovery过程、读写过程、状态转换六个方面介绍Ceph Monitor的实现。本文假设读者已经了解Paxos算法的基本过程，了解Prepare、Promise、Commit、Accept、Quorum等概念。注意Ceph Monitor中的Accept概念其实相当于Paxos中的Promise。



## **架构**

![Ceph Monitor Architecture](http://i.imgur.com/pmj3VAj.png)

上图所示是Ceph Monitor的结构图，自下而上有以下几个部分组成：

- DBStore层：数据的最终存储组件，以leveldb为例；


- Paxos层：在集群上对上层提供一致的数据访问逻辑，在这一层看来所有的数据都是kv；上层的多中PaxosService将不同的组件的map数据序列化为单条value，公用同一个paxos实例。
- PaxosService层：每个PaxosService代表集群的一种状态信息。对应的，Ceph Moinitor中包含分别负责OSD Map，Monitor Map, PG Map, CRUSH Map的几种PaxosService。PaxosService负责将自己对应的数据序列化为kv写入Paxos层。Ceph集群所有与Monitor的交互最终都是在调用对应的PaxosSevice功能。




## **初始化**

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



## **选主**

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




## **RECOVERY阶段**

经过了上述的选主阶段，便确定了leader，peon角色，以及quorum成员。在真正的开始一致性读写之前，还需要经过RECOVERY阶段：

- leader生成新的更大的新的pn，并通过collect消息发送给所有的quorum中成员；
- 收到collect消息的节点当pn大于自己已经accept的最大pn时，接受并通过last消息返回自己的commit位置及uncommitted；
- leader收到last消息，更新自己的commit位置及数据，并重复提升pn发送collect消息的过程，直到quorum中所有的节点都接受自己。
- 同时leader会根据收到的commit及uncommitted位置，分别用commit消息和begin消息更新对应的peon；
- leader向quorum中所有节点发送lease消息，使整个集群进入active状态。

这个阶段的交互过程如下图：

![Ceph Monitor Collect](http://i.imgur.com/4EsQ1xe.png)

**目的**：

- 将leader及quorum节点的数据更新到最新且一致；
- 整个集群进入可用状态。




## **读写流程**

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



## **状态**

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




### **参考：**

[RADOS: A Scalable, Reliable Storage Service for Petabyte-scale Storage Clusters](http://ceph.com/papers/weil-rados-pdsw07.pdf)

[SOURCE CODE](https://github.com/ceph/ceph)







