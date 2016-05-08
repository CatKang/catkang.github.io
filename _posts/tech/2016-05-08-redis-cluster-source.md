---
layout: post
title: Redis Cluster
category: 技术
tags: [Redis, Redis Cluster, Source]
keywords: Redis, Redis Cluster, Source
---

本文将从设计思路，功能实现，源码几个方面介绍Redis Cluster。假设读者已经了解Redis Cluster的使用方式，否则可以首先阅读[Redis Cluster Tutorial](http://redis.io/topics/cluster-tutorial)。


## 简介
Redis Cluster作为Redis的分布式实现，主要做了方面的事情：
#### 数据分片
- Redis Cluster将数据按key，Hash到16384个slot上
- Cluster中的不同节点负责一部分slot

#### 故障恢复
- Cluster中直接提供服务的节点为Master
- 每个Master可以有一个或多个Slave
- 当Master不能提供服务时，Slave会自动FailOver

## 设计思路
通过上述简介可以看出，Redis Cluster做了如下权衡：

#### 性能为第一目标

- 每一次数据处理都是由负责当前slot的Master直接处理的

#### 提高可用性

- **水平扩展**能力 ：由于slot的存在，增加机器节点时只需要将之前由其他节点处理的一部分slot重新分配给新增节点。slot可以看做机器节点和用户数据之间的一个抽象层。
- **故障恢复**：Slave会在需要的时候自动提升为Master

#### 损失一致性

- Master与Slave之之间**异步复制**，即Master先向用户返回结果后再异步将数据同步给Slave，这就导致Master宕机后一部分已经返回用户的数据在新Master上不存在
- **网络分区**时，由于开始Failover前的超时时间，会有一部分数据继续写到马上要失效的Master上

## 功能实现
### 1，数据分片

我们已经知道数据会按照key哈希到不同的slot，而每个节点仅负责一部分的slot，客户端根据slot将请求交给不同的节点。将slots划分给不同节点的过程称为数据分片，对应的还可以进行分片的重新分配。这部分功能依赖外部调用命令：

#### 数据分片

- 对每个集群执行`CLUSTER ADDSLOTS slot [slot ...]`
- RedisCluster将命令指定的slots作为自己负责的部分 

#### 分片再分配
再分配要做的是将一些slots从当前节点(**source**)迁移到其他节点(**target**)

- 对**target**执行`CLUSTER SETSLOT slot IMPORTING [node-id]`，target节点将对应slots记为importing状态；
- 对**source**执行`CLUSTER SETSLOT MIGRATING[node-id]`，source节点将对应slots记为migrating状态，与importing状态一同在之后的请求重定向中使用
- 获取所有要迁移slot对应的keys，`CLUSTER GETKEYSINSLOT slot count`
- 对**source** 执行`MIGRATE host port key db timeout REPLACE [KEYS key [key ...]]`
- MIGRATE命令会将所有的指定的key通过`RESTORE key ttl serialized-value REPLACE`迁移给**target**
- 对所有节点执行`CLUSTER SETSLOT slot NODE [node-id]`，申明**target**对这些slots的负责，并退出importing或migrating

### 2，请求重定向

由于每个节点只负责部分slot，以及slot可能从一个节点迁移到另一节点，造成客户端有可能会向错误的节点发起请求。因此需要有一种机制来对其进行发现和修正，这就是请求重定向。有两种不同的重定向场景：

#### 1)，MOVE

- ‘我’并不负责‘你’要的key，告’你‘正确的吧。
- 返回`CLUSTER_REDIR_MOVED`错误，和正确的节点。
- 客户端向该节点重新发起请求，注意这次依然又发生重定向的可能。

#### 2），ASK

- ‘我’负责请求的key，但不巧的这个key当前在migraging状态，且‘我’这里已经取不到了。告诉‘你’importing他的‘家伙’吧，去碰碰运气。
- 返回`CLUSTER_REDIR_ASK`，和importing该key的节点。
- 客户端向新节点发送`ASKING`，之后再次发起请求
- 新节点对发送过`ASKING`，且key已经migrate过来的请求进行响应

#### 3），区别
区分这两种重定向的场景是非常有必要的：

- MOVE，申明的是slot所有权的转移，收到的客户端需要更新其key-node映射关系
- ASK，申明的是一种临时的状态，所有权还并没有转移，客户端并不更新其映射关系。前面的加的ASKING命令也是申明其理解当前的这种临时状态

### 3，状态检测及维护
Cluster中的每个节点都维护一份在自己看来当前整个集群的状态，当集群状态变化时，如新节点加入、slot迁移、节点宕机、slave提升为新Master，我们希望这些变化尽快的被发现并传播到整个集群的所有节点并达成一致。

#### 心跳 + Gossip

#### 广播
当需要发布一些非常重要需要立即送达的信息时，上述心跳加Gossip的方式就显得捉襟见肘，这时就需要向所有集群内机器的广播信息，使用广播发的场景：

- **节点的Fail信息**：当发现某一节点不可达时，探测节点会将其标记为PFAIL状态，并通过心跳传播出去。当某一节点发现这个节点的PFAIL超过半数时修改其为FAIL并发起广播。
- **Failover Request信息**：slave尝试发起FailOver时广播其要求投票的信息
- **新Master信息**：Failover成功的节点向整个集群广播自己的信息

### 4，故障恢复（Failover）

## 源码
### 1，数据结构
### 2，启动过程
### 3，客户端请求重定向
### 4，定时任务
### 5，集群消息处理

## 参考
- Tutorial：[Redis Cluster Tutorial](http://redis.io/topics/cluster-tutorial)
- Specification: [Redis Cluster Specification](http://redis.io/topics/cluster-spec)
- Source：[Github](https://github.com/antirez/redis)
- [Life in a Redis Cluster: Meet and Gossip with your neighbors](http://cristian.regolo.cc/2015/09/05/life-in-a-redis-cluster.html)