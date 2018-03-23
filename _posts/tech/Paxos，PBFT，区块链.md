# 从Paxos到区块链

本文希望探讨从Paxos到PBFT（Practical Byzantine Fault Tolerance），再到区块链中共识算法Pow的关系和区别，并期望摸索其中一脉相承的思维脉络。



## **问题**

首先需要明白，我们常说的一致性协议或共识算法所针对的问题，简单的说就是要保证：

**即使发生网络或节点异常，整个集群依然能够像单机一样提供一致的服务，即在每次成功操作时都可以看到其之前的所有成功操作按顺序完成。**



## **故障模型**

正式开始之前，还需要了解分布式系统中几个常见的故障模型，这也是这几个不同算法存在的本质原因。按照最理想到最现实的顺序大体有一下几种：

- Crash-stop Failures：故名思议，一旦发生故障，节点就停止提供服务，并且不会恢复。这种故障模型中的节点都按照正确的逻辑运行，可能宕机，可能网络中断，可能延迟增加，但结果总是正确的；
- Crash-recovery Failures：相对于crash-stop failures，这种故障模型允许节点在故障发生后恢复，恢复时可能需要一些持久化的数据恢复状态；
- Byzantine Failures：这种故障模型需要处理拜占庭问题，因此也是最难应对的，相对于上面的两种故障模型，不仅仅节点宕机或网络故障会发生，节点还有可能返回随机或恶意的结果，甚至有可能影响其他节点的正常运行。

如下图([图来源](http://danielw.cn/history-of-distributed-systems-2))所示，三种错误模型的限制逐渐放宽，逐步复杂：

![Fault Model](https://i.imgur.com/DKTbZLu.png)

本文涉及三种算法便是基于不同的故障模型的产物：

- Paxos基于Crash-recovery Failures，因此适用于安全的网络环境，因此在内网服务的存储或协调服务大量使用；
- PBFT和区块链则是基于Byzantine Failures，面向更复杂的网络环境。



## **Paxos**

从上面的讨论已经知道，Paxos面临的是一个可能失败但绝不会出错的相对安全的网络环境，因此可以无条件的信任所有节点的交互结果。

#### **单个提案**

为了保证最终一定有value被chosen，Paxos要求每个acceptor必须接受收到的第一个value：

> P1. An acceptor must accept the first proposal that it receives.

同时，单个Paxos实例允许不止一个propose最终被chosen，但要求所有被chosen的propose必须有相同的值，从而保证只有一个value最终被chosen。

> P2. If a proposal with value v is chosen, then every higher-numbered pro- posal that is chosen has value v.

算法分为Prepare和Accept两个阶段，

- Prepare阶段：
  - Proposer选取proposal number n并向所有acceptor发送Prepare消息；
  - Acceptor收到Prepare消息后，如果n不小于其Promise过的任何其他Prepare消息，则答复Promise，保证不再响应小于n的Accept消息，并返回当前number最大的proposal内容。
- Accept阶段：
  - Proposer收到过半数对Prepare消息的答复后，用proposal n及收到的最大number最大proposal内容，向所有acceptor发起Accept请求；
  - Acceptor在不违背自己做出的承诺的情况下Accept。



#### **Multi-paxos**

上面的算法针对的只是一个提案的过程，当有一系列提案时，需要依次对每一个提案执行上述Paxos过程，那么很自然的一个想法就是通过一个主节点来承担Propose责任。如此一来，整体的算法可以分为两个过程：

- Common过程：大多数情况下，有一个稳定的主负责所有提案的Propose，相当于只执行了Accept阶段。
- Recover过程：当主节点失败时，就需要选取新主，主会对所有未Accept的提案执行完整的Paxos过程，并用新的更大的propose number对所有Prepare过程获得的值再次提交。

而保证算法正确无误，为一致性保驾护航的根本是其中一个不起眼的点：**大多数（Majority）**，这也是包括Paxos在内的所有一致性算法证明正确性的关键所在，正式由于每个提案内容都收到了大多数节点的认可，那么只要有大多数节点可以正常服务时，就一定可以拿到已经Accept的提案内容，从而也阻止任何提案Accept不同的值。解释可能有f个节点同时宕机，那么总节点数需要大于**2f + 1**。





## PBFT

如果将Paxos面对的故障模型放宽到Byzantine Failures，假设这时可能存在一定量的恶意节点：

- 可能做出随机的或错误的答复或请求
- 可能延迟或拒绝应答
- 可能通过拒绝服务攻击正常节点，使之不能正常提供服务
- 但不能破坏当前的加密技术

这就是PBFT(Practical Byzantine Fault Tolerance)算法所面临的环境了，先通过一个图直观的了解PBFT实现的思路：

// TODO 解决拜占庭问题的三个节点的图



PBFT的算法过程如下图：



#### **Common过程**

// TODO 交互图



- Cient 向Primary发送Request
- Primary向所有节点发送Pre-prepare消息，包括view号、sequence以及Requst消息；
- Acceptor验证消息，如果v是accept过最大的，则进入Accept状态，并将这个Request联通对应的Primary的签名及自己签名以Prepare消息在集群中广播；
- 当某个节点集齐一个Pre-prepare加2f个Prepare消息时，进入Commit，并发送Commit，并广播Commit消息
- 再收到2f+1个Commit消息后，执行并向用户返回。



#### **Recovery过程**

- Client在发出Request后，等待一段时间，如果能收到大于f+1个结果一样的答复，则成功
- 否则，想所有节点Acceptor再次发送Request
- Acceptor如果已经完成执行，直接返回，否则转发给Primary并等一定超时时间；
- 如果依然没有收到Primary的对应的合法消息，则任务Primary故障，增加view值并广播View-Change消息，包括当前所有完成执行的消息历史及还在Prepare的消息；
- 对应新的view值的的primary收到2f个View-Change消息后，通过New-View

消息用v+1从新对所有未执行的消息重新执行

- 剩下的流程通Common过程



可以看出，PBFT依然很大程度上参考了Paxos并作出适合的改进，

- 所有通信消息需要加上发送者的签名，供接受者验明真伪；
- Accept不能由Primary发起，因此Promise过程由答复Primary改变成向整个集群广播自己收到的Prepare内容及对应的数字签名。
- Recovery过程跟Paxos类似，都是用新的view值重新进行提交
- todo



同样PBFT也依赖**大多数**来保证算法正确，但这里的大多数需要超过三分之二，即假设最多有f个恶意节点，那么集群总数需要达到3f+1。这是由于假设有f个节点在超时时间内没有返回，我们并不能确定他们全都是恶意节点，也有可能是被拒绝服务攻击而无法响应的正常节点；也就是说剩下的响应节点中仍然有可能包括全部f个恶意节点，为了摒除他们的影响，就需要正常节点至少达到f+1个，从而节点总是为3f+1；



## 区块链共识算法

PBFT虽然已经解决了拜占庭问题，但有两个明显的缺陷：

- 大量的网络交互：每个阶段的大量广播消息
- 对大多数的判断是跟节点总结数相关的，因此集群成员需要稳定很难变化

这两个问题导致其不能更广泛的使用在常规的互联网环境中。这就需要一种新的对**大多数**的定义和判断。区块链中提出了一种即聪明又昂贵的思路：工作量证明（Proof-of-Work）。

先来看区块链的基本思路：

- 为了能在无中心的环境中避免重复支出问题，就需要将所有的交易广播到整个网络，并且整个集群需要对交易历史顺序达成一致；
- 因此引入了区块Block，每个Block中包含多个当前网络中的交易事务；
- 每个区块会对当前区块事务以及前一个区块计算一个哈希值，从而将Block串成一个链表。这个哈希值也证明某一时刻某个事务的存在；

// TODO Timestamp Server

现在问题变成了：**如何让集群中的大多数对同一个Block链达成一致。**在这样一个节点可以随时加入或退出的开放的网络环境中，基于节点数量的大多数判断不再适用。工作量证明（Proof-of-Work）用计算能力来确定**大多数**：

- 极大增加生成Block需要的计算能力：要求Block在计算哈希值时，通过选择参与哈希值计算的Nonce，来获得一个前缀有指定个0的哈希值：hash(Pre-Block + Nonce + All Transaction)  < X；


- 由于Block链的生成方式，篡改任何一个Block都需要对其后所有Block的哈希值重新计算；
- 当一个Block后有足够数量个后继Block时，认为攻击者不足以获得足够颠覆整个链的计算能力时，就算对当前最长的主链达成了**大多数**，从而完成记账；
- 给予消耗计算能力创建Block的矿工一定奖励，从而：
  - 加快主链的生成速度，增加恶意节点难度，加快记账时间；
  - 对于拥有足够大量计算能力的节点，诚实的参与到主链的创建中比篡改Block能获得更大的收益，这就是属于博弈论的内容了。



## 总结

无论Paxos，PBFT还是Pow，都是要解决不同网络环境下的一致性问题，而一致性问题的重点在**大多数**，无论正常的处理流程还是故障恢复流程，都依赖两个不同的**大多数**一定有交集的特性。

- 内网安全环境下的Paxos，超过半数节点即可确定大多数；
- 考虑拜占庭容错的PBFT，由于需要面对的恶意节点不仅可能作出错误答复或不答复，还有可能阻止正常节点响应，因此需要在至少2/3个能响应的节点中达到过半数。
- 工作量证明（Pow）用维持一定数量主链领先的计算能力作为大多数，从而满足任意节点可能随时加入退出的更为广泛的网络环境。

虽然区块链有这明显的局限和场景的缺失，前途扑朔迷离，但这里还是不禁要感慨下。凯文凯利在《失控》中曾写到：

> This is a universal law of vivisystems: higher-level complexities cannot be inferred by lower-level existences.

是说群体会表现出其组成个体无法理解的复杂性，而人类作为一个群体， 一直以来最伟大的两个群体表现，互联网和金融体系，在群体最本质的特征，分布式上相遇，无论未来如何，都会像遥远的星辰留下海面的波光粼粼。

> That out of three sounds he frame, not a fourth sound, but a star.



## 参考

http://catkang.github.io/2017/06/30/raft-subproblem.html

http://danielw.cn/network-failure-models

http://catkang.github.io/2017/11/30/raft-safty.html

[Paxos made simple](https://www.google.com/url?sa=t&rct=j&q=&esrc=s&source=web&cd=1&ved=0ahUKEwjUx7L9_-XXAhUES7wKHbENAw8QFggnMAA&url=https%3a%2f%2flamport%2eazurewebsites%2enet%2fpubs%2fpaxos-simple%2epdf&usg=AOvVaw2LqxhZNPEfgaMeyvZEm9xs)

[Paxos Made Live - An Engineering Perspective](http://www.read.seas.harvard.edu/~kohler/class/08w-dsi/chandra07paxos.pdf)