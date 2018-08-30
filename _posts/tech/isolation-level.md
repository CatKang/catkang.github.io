# 浅谈事务隔离级别

事务隔离是数据库系统设计中根本的组成部分，并发控制、索引管理、垃圾回收等众多问题都与其息息相关，本文主要在标准层面来讨论隔离级别的划分方式，先解释事务隔离分级的原因以及标准制定的目标；之后概述其发展历史；最后介绍Atul Adya给出的比较合理的隔离级别定义。



# 为什么要分级

事务隔离是事务并发产生的直接需求，而最直观的保证正确性的隔离显然是让并发的事务像是依次执行。但显然这种串行化的做法会带来极差的性能。在真实的场景中，有时并不需要如此高的正确性保证，因此希望牺牲一些正确性来提高整体性能。**通过区别不同强度的隔离级别使得使用者可以在正确性和性能上自由权衡。**



# 目标

随着数据库产品数量以及使用场景的膨胀，带来了各种隔离级别选择的混乱，数据库的众多设计者和使用者亟需一个对隔离级别划分的共识，这就是标准出现的意义。对于任意一个多事务执行的历史，根据隔离级别的定义，应该可以准确地判断其是否满足该级别。

一个好的隔离级别定义有如下两个重要的**目标**：

- **正确**：每个级别的定义，应该能够将所有损害该级别想要保证的正确性的情况排除在外。也就是说，**只要实现满足某一隔离级别定义，就一定能获得对应的正确性保证**。
- **实现无关**：常见的并发控制的实现方式包括，锁、OCC以及多版本 。而一个**好的标准不应该限制其实现方式**。



# 探索

### 1，ANSI SQL标准：基于异象

[ANSI](http://www.adp-gmbh.ch/ora/misc/isolation_level.html)**先定义不同级别的异象(phenomenas)， 并通过能避免多少异象来划分隔离标准**。其定义的异象包括：

- 脏读（Dirty Read）: 读到了其他事务还未提交的数据；
- 不可重复读（Non-Repeatable/Fuzzy Read）：由于其他事务的修改或删除，对某数据的两次读取结果不同； 
- 幻读（Phantom Read）：由于其他事务的修改，增加或删除，导致Range的结果失效（如where 条件查询）。

通过阻止不同的异象发生，得到了四种不同级别的隔离标准：

![p5638.png](/Users/wangkang/Desktop/p5638.png) ANSI SQL标准看起来是非常直观的划分方式，不想要什么就排除什么，并且做到了实现无关。然而，现实并不像想象美好。因为它并**不正确**。



## 2， Critique of ANSI：基于锁

[A Critique of ANSI SQL Isolation Levels](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf)一文中对ANSI的标准进行了系统的批判，指出其存在两个致命的问题：

##### 1，不完整，缺少对Dirty Write的排除

ANSI SQL标准中所有的隔离级别都没有将Dirty Write这种异象排除在外，所谓Dirty Write指的是两个未提交的事务先后对同一个对象进行了修改。而Dirty Write之所以是一种异象，主要因为他会导致下面的一致性问题：

> H0: w1[x] w2[x] w2[y] c2 w1[y] c1

这段历史中，假设有相关性约束x=y，T1尝试将二者都修改为1，T2尝试将二者都修改为2，顺序执行的结果应该是二者都为1或者都为2，但由于Dirty Write的发生，最终结果变为x=2，y=1，不一致。

##### 2，歧义

ANSI SQL的英文表述有歧义。以Dirty Read为例，标准中提到假设T1读到了T2未提交的值，如果T2最终abort，那么T1读到的就是脏数据。但如果T2最终commit了，是不是就没有问题了？

> H1: r1[x=50]w1[x=10]r2[x=10]r2[y=50]c2 r1[y=50]w1[y=90]c1

H1历史中，假设有相关性约束x+y=100，T1尝试将(x=50, y=50)修改为(x=10, y=90)，T2明显在T1尚未commit前读到了其对x的修改x=10，虽然T1最终正常commit，但T2读到了不满足约束的x=10，y=90。类似的情况同样存在于Non-Repeatable/Fuzzy Read和Phantom Read。



那么，针对上述两个问题，应该如何对待这种歧义呢？[A Critique of ANSI SQL Isolation Levels](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf)的答案是：**宁可错杀三千，不可放过一个，即给ANSI标准中的异象最严格的定义**，只要出现对应的读写顺序就加以否定。Critique of ANSI改造了异象的定义：

> P0: w1[x]…w2[x]…(c1 or a1) (Dirty Write)
>
> P1: w1[x]…r2[x]…(c1 or a1) (Dirty Read)
>
> P2: r1[x]…w2[x]…(c1 or a1) (Fuzzy or Non-Repeatable Read)
>
> P3: r1[P]…w2[y in P]…(c1 or a1) (Phantom)

此时定义已经很严格了，直接阻止了对应的读写组合顺序。仔细可以看出，排除对应异象的定义，其实就是基于锁的定义:

- 阻止P0（Read Uncommitted）：整个事务阶段对x加长写锁
- 阻止P0，P1（Read Commited）：短读锁 + 长写锁
- 阻止P0，P1，P2（Repeatable Read）：长读锁 + 短谓词锁 + 长写锁
- 阻止P0，P1，P2，P3（Serializable）：长读锁 + 长谓词锁 + 长写锁





# 问题本质及解决思路





批判Critique

实现相关，过于严格，损失了OPtimize机会



为什么需要Optimize



本质原因：



解决方案	 



# Generalized 定义：基于依赖图



定义依赖 图



定义隔离级别



# Intermediate 级别及其他贡献



# 评价



# 参考

