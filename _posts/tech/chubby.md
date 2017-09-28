最近在完成Zeppelin的中心节点重构的过程中，反思了我们对分布式锁的实现和使用。因此重读了Chubby论文[The Chubby lock service for loosely-coupled distributed systems](http://static.googleusercontent.com/media/research.google.com/en//archive/chubby-osdi06.pdf)，收益良多的同时也对其中的细节有了更感同身受的理解，论文中将众多的设计细节依次罗列，容易让读者产生眼花缭乱之感。本文希望能够更清晰的展现Chubby的设计哲学和实现方式，以及带给我们的思考和启发。首先介绍Chubby的定位和设计初衷，这也是Chubby众多细节的目标和本质；之后从一致性、锁的实现和锁的使用三个方面介绍Chubby作为分布式锁的设计和实现；最后总结一些Chubby对我们设计开发分布式系统的一般性的经验和启发。



## **定位**

Chubby的设计初衷是为了解决分布式系统中的一致性问题，其中最常见的就是分布式系统的选主需求及一致性的数据存储。Chubby选择通过提供粗粒度锁服务的方式实现：

> Chubby: A coarse-grained locking as well as reliable storage for a loosely-coupled distributed system.

这里的粗粒度(Coarse-grained)锁服务相对于细粒度(Fine-grained)锁服务，指的是应用加锁时间比较长的场景，达到几个小时或者几天。Chubby的三个重要的设计目标是：可靠性(reliability)、可用性(availability)、易于理解(easy-to-understand)，除此之外，一致性当然也是锁服务的立命之本。这些就是稍后会提到的各种设计细节所追求的目标。对于为什么选择锁服务，而不是一致性库或者一致性服务的问题，作者总结了如下几点：

- 用户系统可能并不会在开发初期考虑高可用，而锁服务使得这些应用在后期需要一致性保证的时候能够以最小的代价接入；
- 分布式系统在选主的同时需要存储少量数据供集群其他节点读取，而锁服务本身就可以很好的提供这个功能；
- 开发者更熟悉锁接口的使用；
- 锁服务使得需要一致性或互斥的应用节点数不受quorum数的限制。



## **分布式锁**

分布式锁是Chubby的设计初衷，我们这里就以分布式锁来展开其设计实现，Chubby的结构如下图所示：

TODO 结构图

- Chubby包括客户端和服务端两个部分；
- 客户端通过一个Chubby Library通服务端进行交互；
- 服务端由多个节点组成集群的方式提供高可用的服务。

我们[认为](http://baotiao.github.io/2017/09/12/distributed-lock/)分布式锁的问题其实包含三个部分，分别是一致性协议、分布式锁的实现、分布式锁的使用。三个部分自下而上完成了在分布式环境中对锁需求，下面我们就将从这三个方面介绍Chubby的设计。

TODO（图）



#### **1， 一致性协议**

一致性协议其实并不是锁需求直接相关的，假设我们有一个永不宕机的节点和永不中断的网络，那么一个单点的存储即可支撑上层的锁的实现及使用。但这种假设在互联网环境中是不现实的，所以才引入了一致性协议，来保证我们可以通过副本的方式来容忍节点或网络的异常，同时又不引起正确性的风险，作为一个整体对上层提供一个高可用的服务。

Chubby采用的是一个有强主的Multi-Paxos，其概要实现如下：

- 多个副本组成一个集群，副本通过一致性协议选出一个Master，集群在一个确定的租约时间内保证这个Master的领导地位；
- Master周期性的向所有副本刷新延长自己的租约时间；
- 每个副本通过一致性协议维护一份数据的备份，而只有Master可以发起读写操作；
- Master挂掉或脱离集群后，其他副本发起选主，得到一个新的Master；

具体的Paxos实现可以参考论文[Paxos Made Simple](http://140.123.102.14:8080/reportSys/file/paper/lei/lei_5_paper.pdf)，在这里我们只需要把它近似看做一个不会宕机不会断网的节点，能保证所有成功写入的操作都能被后续成功的读取读到。



#### **2，分布式锁的实现**

这部分是Chubby实现的重点，为了更好的梳理这部分的脉络，我们先看看Chubby提供的API以及给Client的使用机制，这些一起组成了Chubby对外的接口；之后围绕这些接口，结合Chubby的定位引出了Cache，Session，故障恢复等内部机制。

##### **接口**

Chubby的对外接口是外部使用者直接面对的使用Chubby的方式，是连接分布式锁的实现及使用之间的桥梁：

- Chubby提供类似UNIX文件系统的数据组织方式，包括**Files**和**Directory**来存储数据或维护层级关系，统称**Node**；提供跟Client同生命周期的**Ephemeral**类型Node来方便实现节点存活监控；通过类似于UNIX文件描述符的**Handle**方便对Node的访问；Node除记录数据内容外还维护如ACL、版本号及Checksum等**元信息**。
- 提供众多方便使用的**API**，包括获取及关闭Handle的Open及Close接口；获取释放锁的Aquire，Release接口；读取和修改Node内容的GetContentAndStat，SetContent，Delete接口；以及其他访问元信息、Sequencer，ACL的相关接口。
- 提供**Event**的事件通知机制来避免客户端轮训的检查数据或Lock的变化。包括Node内容变化的事件；子Node增删改的事件；Chubby服务端发生故障恢复的事件；Handle失效事件。客户端收到事件应该做出对应的响应。



##### **Cache**

上面提到的接口是客户端可见的，从这里开始要提到的Chubby的机制就是对Client透明的了。Chubby对自己的定位是需要支持大量的Client，并且读请求远大于写请求的场景，因此引入一个对读请求友好的Client端Cache来减少大量读请求对Chubby Master的压力便十分自然，客户单可以完全不感知这个Cache的存在。Cache对读请求的极度友好体现在它牺牲写性能实现了一个一致语义的Cache：

- Cache可以缓存几乎所有的信息，包括数据，数据元信息，Handle信息及Lock；
- Master收到写请求时，会先阻塞写请求，通过返回所有客户端的KeepAlive来通知客户端Invalid自己的Cache；
- Client直接将自己的Cache清空并标记为Invalid，并发送KeepAlive向Master确认；
- Master收到所有Client确认或等到超时后再执行写请求。



##### Session and KeepAlive

Session可以看做是Client在Master上的一个投影，Master通过Session来掌握并维护Client：

- 每个Session包括一个租约时间，在租约时间内Client是有效的，Session的租约时间在Master视角和Client视角由于网络传输时延及两端的时钟差异可能略有不同；
- Master和Client之间通过KeepAlive进行通信，Client发起KeepAlive，会被Master阻塞在本地，直到Session租约临近过期，此时Master会延长租约时间，并返回阻塞的KeepAlive通知Client。除此之外，Master还可能在Cache失效或Event发生时返回KeepAlive。
- Master除了正常的在创建连接及租约临近过期时延长租约时间外，故障恢复也会延长Session的租约。
- Client的租约过期会先阻塞本地的所有请求，进入jeopardy状态，等待额外的45s，以期待与Master的通信恢复。如果事与愿违，则返回用户失败。



##### **故障恢复**

Master发生故障或脱离集群后，它锁维护的Session信息会被集群不可见，一致性协议选举新的Master，新Master启动后需要恢复必要的信息，并尽量较少集群停止服务过程的影响：

- 选择新的epoch
- 根据持久化的副本内容恢复Session及Lock信息，并重置Session租约到一个保守估计的时长
- 接受并处理Client的KeepAlive请求，第一个KeepAlive会由于epoch错误而被Maser拒绝，Client也因此获得了最新的epch；之后第二个KeepAlive直接返回以通知Client设置本地的Session租约时间；接着Master Block第三个KeepAlive，恢复正常的通信模式。
- 从新请求中发现老Master创建的Handle时，新Master也需要重建，一段时间后，删除没有Handle的临时节点。

TODO failed over图





#### 3， 分布式锁的使用







