# Zeppelin不是飞艇之概述

过去的一年多的时间中，大部分的工作都围绕着[Zeppelin](https://github.com/Qihoo360/zeppelin)这个项目展开，经历了Zeppelin的从无到有，再到逐步完善稳定。见证了Zeppelin的成长的同时，Zeppelin也见证了我的积累进步。对我而言，Zeppelin就像是孩提时代一同长大的朋友，在无数次的游戏和谈话中，交换对未知世界的感知，碰撞对未来的憧憬，然后刻画出更好的彼此。这篇博客中就向大家介绍下我的这位老朋友。



## **定位**

[Zeppelin](https://github.com/Qihoo360/zeppelin)是一个分布式的KV存储平台，在设计之初，我们对他有如下几个主要期许：

- 高性能；


- 大集群，因此需要有更好的可扩展性和必要的业务隔离及配额；
- 作为支撑平台，向上支撑更丰富的协议；

Zeppelin的整个设计和实现都围绕这三个目标努力，本文将从API、数据分布、元信息管理、一致性、副本策略、数据存储、故障检测几个方面来分别介绍。



## **API**

为了让读者对Zeppelin有个整体印象，先介绍下其提供的接口：

- 基本的KV存储相关接口：Set、Get、Delete；
- 支持TTL；
- HashTag及针对同一HashTag的Batch操作，Batch保证原子，这一支持主要是为了支撑上层更丰富的协议。





## **数据分布**

最为一个分布式存储，首要需要解决的就是数据分布的问题。另一篇博客[浅谈分布式存储系统数据分布方法](http://catkang.github.io/2017/12/17/data-placement.html)中介绍了可能的数据分布方案，Zeppelin选择了比较灵活的分片的方式，如下图所示：

![Partition](https://i.imgur.com/ZYGmw35.png)

用逻辑概念Table区分业务，并将Table的整个Key Space划分为相同大小的分片（Partition），每个分片的多副本分别存储在不同的Node Server上，因而，每个Node Server都会承载多个Partition的不同副本。Partition个数在Table创建时确定，更多的Partition数会带来更好的数据均衡效果，提供扩展到更大集群的可能，但也会带来元信息膨胀的压力。实现上，Partition又是数据备份、数据迁移、数据同步的最小单位，因此更多的Partition可能带来更多的资源压力。Zeppelin的设计实现上也有意降低这种影响。

可以看出，分片的方式将数据分布问题拆分为两层隐射：从Key到Partition的映射可以简单的用Hash实现。而Partition副本到存储节点的映射相对比较复杂，需要考虑稳定性、均衡性、节点异构及故障域隔离（更多讨论见[浅谈分布式存储系统数据分布方法](http://catkang.github.io/2017/12/17/data-placement.html)）。关于这一层映射，Zeppelin的实现参考了CRUSH对副本故障域的层级维护方式，但摈弃了CRUSH对降低元信息量稍显偏执的追求。

在进行创建Table及扩容缩容等集群变化的操作时，用户需要提供整个集群分层部署的拓扑信息（包含节点的机架、机器等部署信息）、存储节点权重以及各个故障层级的分布规则。Zeppelin根据这些信息及当前的数据分布直接计算出完整的目标数据分布，这个过程会尽量保证数据均衡及需要的副本故障域。下图举例展示了，副本在机架（cabinet）级别隔离的规则及分布方式。更详细的介绍见[Zeppelin的数据分布方式](http://)

![Partition Placement](https://i.imgur.com/WPH4VBj.png)



## **元信息管理**

上面确定了分片的数据分布方式，可以看出，包括各个分片副本的分布情况在内的元信息需要在整个集群间共享，并且在变化时及时的扩散，这就涉及到了元信息管理的问题，通常有两种方式：

- 有中心的元信息管理：由中心节点来负责整个集群元信息的检测、更新和维护，这种方式的优点是设计简洁清晰，容易实现，且元信息传播总量相对较小并且及时。最大的缺点就是中心节点的单点故障。以BigTable和Ceph为代表。
- 对等的元信息管理：将集群元信息的处理负担分散到集群的所有节点上去，节点间地位一致。元信息变动时需要采用Gossip等协议来传播，限制了集群规模。而无单点故障和较好的水平扩展能力是它的主要优点。Dynamo和Redis Cluster采用的是这种方式。

考虑到对大集群目标的需求，Zeppelin采用了有中心节点的元信息管理方式。其整体结构如下图所示：

![Architecture](https://i.imgur.com/dO3puHH.png)

可以看出Zeppelin有三个主要的角色，中心节点Meta Server、存储节点Node Server及Client。Client的首次访问需要先从Meta Server获得当前集群的完整数据分布信息，对每个用户请求计算正确的Node Server位置，并发起直接请求。

为了减轻上面提到的中心节点的单点问题。我们采取了如下策略：

- Meta Server以**集群的方式**提供服务，之间以一致性算法来保证数据正确。
- **良好的Meta设计**：包括一致性数据的延迟提交；通过Lease让Follower分担读请求；粗粒度的分布式锁实现；合理的持久化及临时数据划分等。更详细的介绍见：[Zeppelin不是飞艇之元信息节点](https://)
- **智能Client**：Client承担更多的责任，比如缓存元信息；维护到Node Server的链接；计算数据分布的初始及变化。
- **Node Server分担更多责任**：如元信息更新由存储节点发起；通过MOVE，WAIT等信息，实现元信息变化时的客户端请求重定向，减轻Meta压力。更详细的介绍见：[Zeppelin不是飞艇之存储节点](https://)

通过上面几个方面的策略设计，尽量的降低对中心节点的依赖。即使Meta集群整个异常时，已有的客户端请求依然能正常进行。



## **一致性**

上面已经提到，中心元信息Meta节点以集群的方式进行服务。这就需要一致性算法来保证：

> 即使发生网络分区或节点异常，整个集群依然能够像单机一样提供一致的服务，即在下一次的成功操作可以看到之前的所有成功操作按顺序完成。

Zeppelin中采用了我们的一致性库[Floyd](https://github.com/Qihoo360/floyd)来完成这一目标，Floyd是[Raft](https://raft.github.io/)的C++实现。更多内容可以参考：[Raft和它的三个子问题](http://catkang.github.io/2017/06/30/raft-subproblem.html)。

利用一致性协议，Meta集群需要完成Node节点的存活检测、元信息更新及元信息扩散等任务。这里需要注意的是，由于一致性算法的性能相对较低，我们需要控制写入一致性库的数据，只写入重要、不易恢复且修改频度较低的数据。



## **副本策略**

由于对高性能的定位，我们选择了Master，Slave的副本策略。每个Partition包含至少三个副本，其中一个为Master，其余为Slave。所有的用户请求由Master副本负责，读写分离的场景允许Slave也提供读服务。Master处理的写请求会在修改DB前写WAL，称为Binlog，并异步的将Binlog同步给Slave。

![Imgur](https://i.imgur.com/Df4bO1A.png)

上图所示的是Master，Slave之间建立主从关系的过程，右边为Slave。中心节点元信息变化时，存储节点发现自己是某个Partition新的Slave时，将TrySync任务通过Buffer交给TrySync Moudle；TrySync Moudle向Master的Command Module发起Trysync；Master生成Binlog Send任务到Send Task Pool；Binlog Send Module向Slave发送Binlog，完成数据异步复制。更详细内容见：[Zeppelin不是飞艇之存储节点](https://)



## **数据存储**

Zeppelin目前采用了Rocksdb作为最终的数据存储，每个Partition副本都会占有单独的Rocksdb实例。采用LSM方案也是为了对高性能的追求，LSM通过将随机写转换为顺序写来大幅提升了写性能，同时，通过内存缓存保证了相对不错的读性能。[庖丁解LevelDB之概览](http://catkang.github.io/2017/01/07/leveldb-summary.html)中以LevelDB为例介绍了LSM的设计和实现。

然而在数据Value较大的场景下，LSM写放大问题严重，在使用SSD时让通过多次重复写换来的高性能优势不太划算。而Zeppelin需要对上层不同协议的支撑，又不可避免的会出现大Value，[LSM upon SSD](http://catkang.github.io/2017/04/30/lsm-upon-ssd.html)针对做了更多的讨论，包括这种改进在内的其他针对不同场景的存储引擎及可插拔的设计也是未来的发展方向。



## **故障检测**

一个好的故障检测的机制应该能做到如下几点：

- **及时**：节点发生异常如宕机或网络中断时，集群可以在可接受的时间范围内感知；
- **适当的压力**：包括对节点的压力，和对网络的压力；
- **容忍网络抖动**
- **扩散机制**：节点存活状态改变导致的元信息变化需要通过某种机制扩散到整个集群；

Zeppelin 中的故障可能发生在元信息节点集群或存储节点集群，元信息节点集群的故障检测依赖下层的Floyd的Raft实现，并且在上层通过Jeopardy阶段来容忍抖动。更详细内容见：[Zeppelin不是飞艇之元信息节点](https://)。

而存储节点的故障检测由元信息节点集群负责， 感知到异常后，元信息节点集群修改元信息、更新元信息版本号，并通过心跳通知所有存储节点，存储节点发现元信息变化后，主动拉去最新元信息并作出相应改变。

最后，Zeppelin还提供了丰富的运维、监控数据，以及相关工具。方便通过Prometheus等工具监控展示。



## **相关**

[Zeppelin](https://github.com/Qihoo360/zeppelin)

[Floyd](https://github.com/Qihoo360/floyd)

[Raft](https://raft.github.io/)

[浅谈分布式存储系统数据分布方法](http://catkang.github.io/2017/12/17/data-placement.html)

[Zeppelin的数据分布方式（未完）](http://)

[Zeppelin不是飞艇之元信息节点（未完）](https://)

[Zeppelin不是飞艇之存储节点（未完）](https://)

[Raft和它的三个子问题](http://catkang.github.io/2017/06/30/raft-subproblem.html)

[庖丁解LevelDB之概览](http://catkang.github.io/2017/01/07/leveldb-summary.html)

[LSM upon SSD](http://catkang.github.io/2017/04/30/lsm-upon-ssd.html)