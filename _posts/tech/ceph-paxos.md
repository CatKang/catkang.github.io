# 庖丁解Ceph之Paxos

Ceph Monitor作为Ceph服务中的元信息管理角色，肩负着提供高可用的集群配置的维护及提供责任。Ceph选择了实现自己的Multi-Paxos版本来保证Monitor集群对外提供一致性的服务。在Monitor中，其实OSDMap，PGMap等PaxosService才是其对外暴露的元信息管理内容，这部分内容将会在后续的博客中详细介绍。而Multi-Paxos处于低一层级，将上层的元数据变化当成一次提交扩散到整个集群。注意Ceph中简单的用Paxos来指代Multi-Paxos，我们这里也沿用这一简化，本文将介绍Ceph Paxos的算法细节，讨论其一致性选择，与常见Paxos实现进行比较，最后简略的介绍其代码实现。本文的大部分信息来源于Ceph Monitor相关源码，若有偏颇或谬误，敬请指正。



## **算法介绍**

#### **概览**

Paxos节点与Monitor节点绑定，每个Monitor启动一个Paxos。当有大多数的Paxos节点存活时集群可以运行，正常提供服务的过程中，一个节点做为Leader角色，其余为Peon角色。只有Leader可以发起提案，所有Peon角色根据本地历史选择接受或拒绝Leader的提案，并向Leader回复结果。Leader统计并提交超过半数Paxos节点接受的提案。

每个提案都是一组对Monitor元信息的修改操作，序列化后在Paxos层传递。Leader发起提案及Peon接受提案时都会写入本地Log，被提交的Log会最终写入DB，写入DB的提案才最终可见。实现中用同一个DB承载Log和最终数据的存储，并用命名空间进行区分。

除去上面提到的Leader及Peon外，Paxos节点还有可能处于Probing、Synchronizing、Election三种状态之一，如下图所示。其中，Election用来选举新的Leader，Probing用来发现并更新集群节点信息，同时发现Paxos节点之间的数据差异，并在Synchronizing状态中进行数据的追齐，更详细的内容会在稍后的Recovery和Membership中介绍。

![Ceph Monitor Status](http://i.imgur.com/VmofRlH.png)

Leader会向所有Peon发送Lease消息，收到Lease的Peon在租约时间内可以直接以本地数据提供Paxos读服务，来分担Leader的只读请求压力。Lease过期的Peon会退回Probing状态，之后通过新一轮的选举产生新的Leader。

Leader会选择当前集群中最大且唯一的Propose Num，简称Pn，每次新Leader会首先将自己的Pn增加，并用来标记自己作为Leader的阶段，作为Ceph Paxos算法中的逻辑时钟（Logical Clock）。同时，每个提案会被指派一个全局唯一且单调递增的version，实现中作为Log的索引位置。Pn及Version会随着Paxos之间的消息通信进行传递，供对方判断消息及发起消息的Leader的新旧。Paxos节点会将当前自己提交的最大提案的version号同Log一起持久化供之后的恢复使用。




#### **常规过程（Normal Case）**

常规服务状态下存在一个唯一的Leader以及一个已经确认的大多数节点Quorum，Leader将每个写请求被封装成一个新的提案提交到整个集群，其过程如下，注意这里的Quorum固定：

- Leader将提案追加在本地Log，并向Quorum中的所有节点发送**begin**消息，并携带提案值, Pn及指向前一条提案项version的last_commit；
- Peon收到begin消息，如果accept过更高的pn则忽略，否则提案写入本地Log并返回**accept**消息。同时Peon会将当前的lease过期掉，在下一次收到lease前不再提供服务；
- Leader收到**全部**Quorum的accept后进行commit。将Log项在本地DB执行，返回调用方并向所有Quorum节点发送**commit**消息；
- Peon收到commit消息同样在本地DB执行；
- Leader通过**lease**消息将整个集群带入到active状态。

![Ceph Monitor Write](http://i.imgur.com/WnE9Jg1.png)



#### **选主（Leader Election）**

Peon的Lease超时或Leader任何消息超时都会讲整个集群带回到Probing状态，确定新的Members并最终进入Election状态进行选主，注意选主开始时所面向的是所有的Members节点，Ceph中由Monmap表示：

- 将election_epoch加1，向Monmap中的所有其他节点发送**Propose**消息；
- 收到Propose消息的节点进入election状态并仅对更新的election_epoch且Rank值大于自己的消息答复**Ack**。这里的Rank简单的由ip大小决定；
- 发送Propose的节点统计收到的Ack数，超时时间内收到Monmap中大多数的ack后可进入victory过程，这些发送ack的节点形成Quorum，election_epoch加1，结束Election阶段并向Quorum中所有节点发送**Victory**消息，并告知自己的epoch及当前Quorum，之后进入Leader状态；


- 收到VICTORY消息的节点完成Election，进入Peon状态；

![Ceph Monitor Election](http://i.imgur.com/INz6V5X.png)





#### **恢复（Recovery）**

经过了上述的选主阶段，便确定了leader，peon角色，以及quorum成员。在真正的开始一致性读写之前，还需要经过RECOVERY阶段：

- leader生成新的更大的新的pn，并通过collect消息发送给所有的quorum中成员；
- 收到collect消息的节点当pn大于自己已经accept的最大pn时，接受并通过last消息返回自己的commit位置及uncommitted；
- leader收到last消息，更新自己的commit位置及数据，并重复提升pn发送collect消息的过程，直到quorum中所有的节点都接受自己。
- 同时leader会根据收到的commit及uncommitted位置，分别用commit消息和begin消息更新对应的peon；
- leader向quorum中所有节点发送lease消息，使整个集群进入active状态。

这个阶段的交互过程如下图：

![Ceph Monitor Collect](http://i.imgur.com/4EsQ1xe.png)



#### **成员变化（Membership）**



#### **日志截断（Log compaction）**





## **一致性选择**

#### **1，state machine system**

#### **2，每次只能一条日志**



#### **3，指定的 Quorum**



#### **4，双向的Recovery方向**



#### **5，使用Lease优化只读请求**



####  **6，Leader Peon同时检测发起新的Election**





## **代码结构**

TODO ： Paxos及Election暴露接口





## **参考**

[RADOS: A Scalable, Reliable Storage Service for Petabyte-scale Storage Clusters](http://ceph.com/papers/weil-rados-pdsw07.pdf)

[SOURCE CODE](https://github.com/ceph/ceph)