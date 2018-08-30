---
layout: post
title: 数据库事务的隔离级别
category: 技术
tags: [Isolation Level，Transaction]
keywords: 隔离级别, 并行控制，事务，Isolation，Concurrent Control，Transaction
---


事务隔离是数据库系统设计中根本的组成部分，本文主要从标准层面来讨论隔离级别的划分方式，先解释事务隔离分级的原因以及标准制定的目标；之后概述其发展历史；最后介绍Atul Adya给出的比较合理的隔离级别定义。



# 为什么要分级

事务隔离是事务并发产生的直接需求，最直观的、保证正确性的隔离方式，显然是让并发的事务依次执行，或是看起来像是依次执行。但在真实的场景中，有时并不需要如此高的正确性保证，因此希望牺牲一些正确性来提高整体性能。**通过区别不同强度的隔离级别使得使用者可以在正确性和性能上自由权衡。**



# 目标

随着数据库产品数量以及使用场景的膨胀，带来了各种隔离级别选择的混乱，数据库的众多设计者和使用者亟需一个对隔离级别划分的共识，这就是标准出现的意义。一个好的隔离级别定义有如下两个重要的**目标**：

- **正确**：每个级别的定义，应该能够将所有损害该级别想要保证的正确性的情况排除在外。也就是说，**只要实现满足某一隔离级别定义，就一定能获得对应的正确性保证**。
- **实现无关**：常见的并发控制的实现方式包括，锁、OCC以及多版本 。而一个**好的标准不应该限制其实现方式**。



# 探索

### ANSI SQL标准：基于异象

[ANSI](http://www.adp-gmbh.ch/ora/misc/isolation_level.html)先定义不同级别的异象(phenomenas)， 并依据能避免多少异象来划分隔离标准。其定义的异象包括：

- 脏读（Dirty Read）: 读到了其他事务还未提交的数据；
- 不可重复读（Non-Repeatable/Fuzzy Read）：由于其他事务的修改或删除，对某数据的两次读取结果不同； 
- 幻读（Phantom Read）：由于其他事务的修改，增加或删除，导致Range的结果失效（如where 条件查询）。

通过阻止不同的异象发生，得到了四种不同级别的隔离标准：

![ANSI Define](http://catkang.github.io/assets/img/isolation_level/ansi_def.png) ANSI SQL标准看起来是非常直观的划分方式，不想要什么就排除什么，并且做到了实现无关。然而，现实并不像想象美好。因为它并**不正确**。



### Critique of ANSI：基于锁

[A Critique of ANSI SQL Isolation Levels](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf)一文中对ANSI的标准进行了系统的批判，指出其存在两个致命的问题：

**1，不完整，缺少对Dirty Write的排除**

ANSI SQL标准中所有的隔离级别都没有将Dirty Write这种异象排除在外，所谓Dirty Write指的是两个未提交的事务先后对同一个对象进行了修改。而Dirty Write之所以是一种异象，主要因为他会导致下面的一致性问题：

> H0: w1[x] w2[x] w2[y] c2 w1[y] c1

这段历史中，假设有相关性约束x=y，T1尝试将二者都修改为1，T2尝试将二者都修改为2，顺序执行的结果应该是二者都为1或者都为2，但由于Dirty Write的发生，最终结果变为x=2，y=1，不一致。

**2，歧义**

ANSI SQL的英文表述有歧义。以Dirty Read为例，标准中提到假设T1读到了T2未提交的值，如果T2最终abort，那么T1读到的就是脏数据。但如果T2最终commit了，是不是就没有问题了？

> H1: r1[x=50]w1[x=10]r2[x=10]r2[y=50]c2 r1[y=50]w1[y=90]c1

H1历史中，假设有相关性约束x+y=100，T1尝试将(x=50, y=50)修改为(x=10, y=90)，T2明显在T1尚未commit前读到了其对x的修改x=10，虽然T1最终正常commit，但T2读到了不满足约束的x=10，y=90。类似的情况同样存在于Non-Repeatable/Fuzzy Read和Phantom Read中。



那么，如何解决上述两个问题呢？Critique of ANSI的答案是：**宁可错杀三千，不可放过一个，即给ANSI标准中的异象最严格的定义**。Critique of ANSI改造了异象的定义：

> P0: w1[x]…w2[x]…(c1 or a1) 						(Dirty Write)
>
> P1: w1[x]…r2[x]…(c1 or a1) 						(Dirty Read)
>
> P2: r1[x]…w2[x]…(c1 or a1) 						(Fuzzy or Non-Repeatable Read)
>
> P3: r1[P]…w2[y in P]…(c1 or a1) 					(Phantom)

此时定义已经很严格了，直接阻止了对应的读写组合顺序。仔细可以看出，此时得到的其实就是基于锁的定义:

- Read Uncommitted，阻止P0：整个事务阶段对x加长写锁
   Read Commited，阻止P0，P1：短读锁 + 长写锁
- Repeatable Read，阻止P0，P1，P2：长读锁 + 短谓词锁 + 长写锁
- Serializable，阻止P0，P1，P2，P3：长读锁 + 长谓词锁 + 长写锁





# 问题本质

可以看出，这种方式的隔离性定义保证了正确性，但却产生了依赖实现方式的**问题：太过严格的隔离性定义，阻止了Optimize或Multi-version的实现方式中的一些正常的情况**：

- 针对P0：Optimize的实现方式可能会让多个事务各自写自己的本地副本，提交的时候只要顺序合适是可以成功的，只在需要的时候才abort，但这种选择被P0阻止；
- 针对P2：只要T1没有在读x，后续没有与x相关的操作，且先于T2提交。在Optimize的实现中是可以接受的，却被P2阻止。

显而易见，想要解决这个问题，**思路**是：**弱化上述异象的限制，使其能精准打击，只限制需要限制的**，但这并不容易，Lock的限制范围如下图所示：

![Isolation Cover](http://catkang.github.io/assets/img/isolation_level/Isolation_cover.png)

图中黑色部分是ANSI的某一个异象描述的异常情况，灰色部分是Critique of ANSI所描述的由于object之间的约束关系导致的异常情况，回忆Critique of ANSI对ANSI的修正时所面对的问题，其实都在这个区域内，而这部分正是Critique of ANSI没有办法精确的定义的，因此其只能退而求其次，扩大限制的范围到黄色部分。

由此，可以看出问题的**本质**：**由于异象的描述只针对单个object，缺少描述多object之间的约束关系，导致需要用锁的方式来作出超出必须的限制。**

相应地，解决问题的**关键：要有新的定义异象的模型，使之能精准的描述多object之间的约束关系，从而使得我们能够精准地限制上述灰色部分，而将黄色的部分解放出来**。Adya的答案是序列化图。



# Adya定义：基于序列化图

Adya在[Weak Consistency: A Generalized Theory and Optimistic Implementations for Distributed Transactions](http://pmg.csail.mit.edu/papers/adya-phd.pdf)中给出了基于序列化图得定义，过程为先定义冲突关系；并以冲突关系为有向边形成序列化图；再以图中的环类型定义不同的异象；最后通过阻止不同的异象来定义隔离级别。

### 冲突关系：

根据上述不同异象涉及的访问冲突，定义三种冲突关系：

- Directly Write-Depends，写写冲突
- Directly Read-Depends，先写后读冲突，其中item-read-depends为对某个object的先写后读冲突，predicate-read-depends为对Range的先写后读冲突
- Directly Anti-Depends，先读后写冲突，其中item-anti-depends为对某个object的先读后写冲突，predicate-anti-depends为对Range的先读后写冲突



### 序列化图（Direct Serialization Graph, DSG）

每个节点表示一个事务，每个有向边表明存在一种冲突关系，有向边T1 -> T2的意义是若要避免该冲突导致的不一致，需要T1先于T2提交，因此通过依次从图中去掉没有入边的节点，可以完成事务的序列化，如下图的序列化顺序为：T1，T2，T3：

![GSG Edge](http://catkang.github.io/assets/img/isolation_level/andy_dsg_edge.png)

![GSG](http://catkang.github.io/assets/img/isolation_level/andy_dsg.png)



可以看出，只要两个事务有一个object相互冲突，就会在DSG中存在一条有向边，因此多个object的冲突关系可以表示在一张图中，从而可以更准确的做异象的限制。



### 基于DSG的异象定义：

按照之前的讨论，这里的异象定义尽量最小化到上一节示意图中的灰色部分，下面依次对每个异象定义最小化：

**1，P0(Dirty Write) -> G0(Write Cycles)：**DSG中包含两条边都为Directly write-depends组成的环

![Write Cycle](http://catkang.github.io/assets/img/isolation_level/ww_cycle.png)

**2，P1(Dirty Read) -> G1**

Dirty Read异象的最小集包括三个部分G1 = G1a + G1b + G1c：

- G1a(Aborted Reads): 读到的uncommitted数据最终被abort，可以在commit时检查所有依赖的事务是否被abort
- G1b(Intermediate Reads) ：读到其他事务中间版本的数据，可以在commit的时候检查所有读到的数据是否为最终数据
- G1c(Circular Information Flow)：DSG中包含两条边都为Directly write-depends或Directly read-depends组成的环

**3，P2(Fuzzy or Non-Repeatable Read) -> G2-item(Item Anti-dependency Cycles)** ：DSG中包含环，其中至少有一条是item-anti-depends edges

**4，P3(Phantom) - G2(Anti-dependency Cycles):** DSG中包含环，并且其中至少有一条是anti-dependency edges

![Anti-dependency Cycles](http://catkang.github.io/assets/img/isolation_level/anti_dependency_cycles.png)

### 对应的隔离级别：

- PL-1（Read Uncommitted）：阻止G0
- PL-2（Read Commited）：阻止G1
- PL-2.99（Repeatable Read）：阻止G1，G2-item
- PL-3（Serializable）：阻止G1，G2



# 其他隔离级别：

除了上述的隔离级别外，在正确性的频谱中还有着大量空白，也就存在着各种其他隔离级别的空间，商业数据库的实现中有两个比较常见：

### 1，Cursor Stability

该隔离界别介于Read Committed和Repeatable Read之间，通过对游标加锁而不是对object加读锁的方式避免了Lost Write异象。

### 2， Snapshot Ioslation

事务开始的时候拿一个Start-Timestamp的snapshot，所有的操作都在这个snapshot上做，当commit的时候拿Commit-Timestamp，检查所有有冲突的值不能再[Start- Timestamp, Commit-Timestamp]被提交，否则abort。长久以来，Snapshot Ioslation一直被认为是Serializable，但其实Snapshot Ioslation下还会出现Write Skew的异象。之后的文章会详细介绍如何从Snapshot Ioslation出发获得Serializable。



# 参考

[A History of Transaction Histories](https://ristret.com/s/f643zk/history_transaction_histories)

[ANSI isolation levels](http://www.adp-gmbh.ch/ora/misc/isolation_level.html)

[A Critique of ANSI SQL Isolation Levels](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf)

[Weak Consistency: A Generalized Theory and Optimistic Implementations for Distributed Transactions](http://pmg.csail.mit.edu/papers/adya-phd.pdf)

[Generalized Isolation Level Definitions](http://pmg.csail.mit.edu/papers/icde00.pdf)
