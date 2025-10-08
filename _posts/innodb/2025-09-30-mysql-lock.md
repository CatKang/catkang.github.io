---
layout: post
title: 庖丁解InnoDB之Lock
category: 庖丁解InnoDB
tags: [Database，MySQL，InnoDB，Lock，Isolation，PolarDB]
keywords: InnoDB，Lock，MySQL，Database，Isolation
---


隔离性（Isolation）是关系型数据库非常重要的特性。顾名思义，隔离性是要对并发运行在数据库上的事务做隔离，其本质是在数据库并发性能和事务正确性之间做权衡，为此数据库通常会提供不同程度的隔离级别供用户选择。而并发控制，就是保证不同隔离级别正确性的内部实现机制。Lock是现代数据库，尤其是单机数据库中最常见的并发控制手段，InnoDB采用的就是基于Lock的并发控制。本文将介绍InnoDB所支持的隔离级别，增删改查的过程中是如何完成加锁的，以及InnoDB的Lock自身的实现细节（代码相关主要基于[MySQL 8.0[1]](https://github.com/mysql/mysql-server/tree/8.0)）。

# 隔离级别及并发控制

数据库隔离性的保证其实是在提供给用户一种选择， 愿意牺牲多少单个事务的独立性来换取更高的数据库并发性能。那么，统一且清晰的隔离级别设置，对于用户使用和预期数据库的行为就变得非常重要。1992年ANSI首先尝试指定统一的隔离级别标准，其定义了不同级别的异象(phenomenas)， 包括：**脏读（Dirty Read）**，读到了其他事务还未提交的数据；**不可重复读（Non-Repeatable/Fuzzy Read）**，由于其他事务的修改或删除，对某数据的两次读取结果不同；以及**幻读（Phantom Read）**，由于其他事务的修改，增加或删除，导致Range的结果失效（如where 条件查询）。并通过能排除多少这些异象来定义了，不做限制的**Read Uncommitted**，排除了脏读的**Read Committed**。排除了脏读和不可重复读的**Repeatable Read**，以及排除了所有这三种异象的**Serializable**四种隔离级别，当然这个标准中存在一些问题和歧义，这里不展开讨论，更多的可以参考[数据库事务隔离发展历史[2]](https://catkang.github.io/2018/08/31/isolation-level.html)。

数据库为了实现上述隔离级别的保证，就需要对事务的操作做冲突检测，对有冲突的事务延迟或丢弃，这就是数据库的**并发控制**机制。一方面，根据对冲突的乐观程度，可以分为，在操作甚至是事务开始之前就检测冲突的**基于Lock**的方式；在操作真正写数据的时候检测的**基于Timestamp**的方式；以及在事务Commit时才检测的**基于Validation**的方式三种。另一方面，根据是否采用多版本来避免读写之间的互相阻塞，分为单版本和多版本，也就是**MVCC**。关于这方面更多的讨论可以参考[浅析数据库并发控制机制[3]](https://catkang.github.io/2018/09/19/concurrency-control.html)。

基于Lock的方式降低了冲突发生后回滚的代价，并且更符合数据库使用者的直观感觉，因此成为大多数数据库，尤其是单机数据库的选择。InnoDB采用的就是**Lock + MVCC**的实现方式，具体来说：对与写事务，会在修改记录之前对这一行记录加锁并持有，以此来避免冲突的发生；而对于只读事务，会默认采用MVCC的的方式，这种方式不需要加锁，而是在事务第一次读操作（RR）或者当前语句开始（RC）时，获取并持有一个当时实例全局的事务活跃状态，作为自己的ReadView，相当于对当时的事务状态打了一个Snapshot，后续访问某一行的时候，会根据这一行上面记录的事务ID，通过自己持有的ReadView来判断是否可见，如果不可见，再沿着记录上的Roll Ptr去Undo中查找自己可见的历史版本。这种读的方式我们也称之为**快照读（Snapshot Read）。**与之对应的，InnoDB还支持**加锁读（Lock Read）**的方式，当Select语句中使用了如<u>Select....for Update/Share</u>时，这时查询不再通过MVCC的方式，而是像写操作一样，先对需要访问的记录加锁，之后再读取记录内容，这种方式会跟写请求相互阻塞， 从而读到的也一定是该记录当前最新的值，因此也被称为当前读。

![lock_read](http://catkang.github.io/assets/img/innodb_lock/lock_read.png)

上图展示的是写操作、加锁读以及快照读对数据不同的访问模式，可以看出，写操作和加锁读访问的是记录的当前最新版本，而快照读访问的是一个历史时刻的数据版本，因此在同一个事务中混用两种模式，可能会遇到有些反直觉的现象，比如官方文档中给出的一个[例子[4]](https://dev.mysql.com/doc/refman/8.0/en/innodb-consistent-read.html)：

```
SELECT COUNT(c1) FROM t1 WHERE c1 = 'xyz';
-- Returns 0: no rows match.
DELETE FROM t1 WHERE c1 = 'xyz';
-- Deletes several rows recently committed by other transaction.
```

这个例子展示的是一个事务，先通过正常的Select语句去查找满足条件c1='xyz'的记录，发现没有后，用相同的条件做删除操作。结果造成另一个事务刚刚Commit的满足c1='xyz'的记录被删除。这个现象就是因为前面的Selete语句默认走的是MVCC的方式，并没有对访问的记录加锁。官方文档也是不建议这样混用的，要实现前后Selete和Delete看到数据的一致，需要用上面的提到的**加锁读**的方式，也就是：

```
SELECT COUNT(c1) FROM t1 WHERE c1 = 'xyz' for Update/Share;
```

因此，我们这里对InnoDB隔离级别的讨论，也需要区分是快照访问还是加锁访问。MySQL提供了ANSI中定义的所有四种隔离级别，但对异象的排除其实跟标准是有些差异的，这也引起了很多的误解， 我们这里来整理一下，表格中展示的是ANSI，MySQL InnoDB采用快照方式或者采用加锁方式的时候，在配置不同的隔离级别时，是否可能出现P1（Dirty Read）、P2（Non-Repeatable）、P3（Phantom）三种异象：

|                  | ANSI       | MySQL InnoDB加锁访问 | MySQL InnoDB快照访问 |
| ---------------- | ---------- | -------------------- | -------------------- |
| Read Uncommitted | P1, P2, P3 | P3                   | P1, P2, P3           |
| Read Committed   | P2, P3     | P3                   | P2，P3               |
| Read Repeatable  | P3         |                      |                      |
| Serializable     |            |                      |                      |

不同于ANSI每一个级别多排除一个异象，可以看到：

- 当使用加锁访问，如写操作或者加锁读（Select...for Update/Share）时：在Read Uncommitted及Read Committed都会对Key加锁，并且这个锁是持续整个事务生命周期的，因此都不会有Dirty Read 和Non-Repeatable的问题；而在Read Repeatable及Serializable下，除了对Key加锁外，还需要对访问的Range加锁，同样也是持续整个事务生命周期，因此是没有Phantom问题的。
- 当使用快照读，如正常的Select语句时：在Read Uncommitted下其实是不会持有ReadView判断可见性的，也就是存在Dirty Read，Non-Repeatable及Phantom的，在Read Committed下，每条查询都会重新获取一次Read View，并以之判断可见性，因此是可以排除Diry Read的；而在Read Repeatable隔离级别下，整个事务会在第一次读的时候获取一次ReadView，相当于之后的所有查询看到的都是这个时刻的快照，因此无论是针对单个Key的Non-Repeatable还是针对where条件的Phantom都是可以避免的，这一点跟标准不同，也是经常造成误解的地方；最后在Serializable下，其实是摒弃了MVCC的，正常的Select也隐式转换成加锁读，也可以摒弃三种异象。

在实践中，由于Read Uncommitted太过宽松，而Seriablizable又没有MVCC，因此通常会在Read Committed及Read Repeatable两种隔离级别中选择。关于快照读的具体实现方式会在后面的文章中详细讨论，本文主要关注InnoDB的加锁访问的实现方式。

# InnoDB加锁概述

在进入到InnoDB的Lock实现细节之前，我们先从宏观上简要的介绍下InnoDB中的Lock的作用及维护方式。InnoDB遵循**2PL(Two-Phase Locking)**，也就是将事务生命周期分为两个阶段，增长阶段（Growing Phash）可以不断地对数据库对象加锁，但不能放锁，直到进入到缩减阶段（Shrinking Phase），这时就只能放锁不能再加锁了。InnoDB中的这个缩减阶段的划分就是事务Commit或Rollback。因此，InnoDB的事务一旦对某个对象加锁后，会在整个事务的生命周期全程持有这把锁。InnoDB中的记录锁有**读锁（LOCK_S）和写锁（LOCK_X）**两种模式，读锁之间不互斥，而写锁和读、写锁都互斥，修改操作通常会持有写锁，而只读操作会持有读锁。

![lock_table](http://catkang.github.io/assets/img/innodb_lock/lock_table.png)

所有的锁的等待和持有信息会维护在一个全局的**Lock Table**中，如上图所示，并发访问的事务会通过对Lock Table查找，以及锁冲突的判断来实现对这些对象的正确访问。如图中所示，事务T3需要对数据库对象A做修改操作，所以申请A上的X Lock，查看Lock Table后发现A上已经有事务T1和T2同时持有S Lock。因此，T3在Lock Table中注册自己的Lock，并挂在A的Lock链表的末尾，标记为Waiting，之后T3挂起等待，直到前面的事务T1及T2提交或回滚后，释放Lock并唤醒T3继续运行。

可以看出，对这个加锁的数据库对象，也就是上图中的A的选择，会成为影响并发性能的关键因素。B+Tree数据库在过去几十年，也经历了一系列的探索进步，从对整颗树加锁，到对多个或一个Page加锁，再到ARIES/KVL将逻辑内容和物理内容分离，实现对Record维度的加锁。InnoDB采用的就是这种**对B+Tree上的Record加Lock**的实现方式（更多参考[B+树数据库加锁历史[5]](https://catkang.github.io/2022/01/27/btree-lock.html)）。对Record全程加Lock可以很自然的实现对Dirtry Read以及Non-Repeatable Read的摒弃，但对于Repeatable Read隔离级别下对Phantom 异象的阻止就比较麻烦了，因为需要对查询的整个范围加锁，也就是需要对可能还不存在的记录进行加锁。针对这个问题，传统的实现方式是**谓词锁(Predicate Lock)**，也就是直接对查询条件加锁，这个是比较麻烦的，因为查询条件千变万化，还需要判定他们之间的互斥关系。幸运的是，在B+Tree上，记录之间已经天然维护了顺序关系，ARIES/KVL提出了**Key Range Locking**，也就是对Key加锁，来保护其旁边的区间范围。之后KRL认为同时对Key和Key之间的Range加锁的方式一定程度上限制了对Key和对Gap的访问并发，提出将二者进行分别加锁（更多参考[B+树数据库加锁历史[5]](https://catkang.github.io/2022/01/27/btree-lock.html)）。InnoDB采用的就是这种方式，分为三种锁类型：只对记录加锁的**Record Lock**（LOCK_REC_NOT_GAP），对当前记录之前的到前一个记录的区间加锁的**Gap Lock**（LOCK_GAP），以及同时对记录和其之前的区间加锁的**Next Key Lock**（LOCK_ORDINARY），他们的加锁对象范围如下图所示：

![lock_mode](http://catkang.github.io/assets/img/innodb_lock/lock_mode.png)

相对于锁单个Record的Record Lock而言，Next Key Lock的加锁的范围更大，有可能带来更多的锁冲突，从而影响整个数据库的性能，学术上其实提出过很多的优化手段，比如对Insert短暂加锁后就释放的**Instant Locking**；将删除操作转换为修改操作的**Ghost Locking**；避免跨节点判断锁的**Fence Key**。很多这些思想其实在InnoDB中都是有类似实现的，这些会在本文后面的章节中详细讨论。

加锁及锁判断的操作，是在SQL语句对数据库的访问过程中进行的，因此如何加锁就跟SQL语句如何访问数据息息相关。从访问模式上来看其实可以大体分为两类：一种根据某种查询条件，找到所有的符合条件的Record，之后对这些Record进行读写操作，这种模式对应的是Select、Update以及Delete语句；另一种是插入语句，其访问模式是找到当前记录应该的插入点，然后完成插入，当然这里针对主键和唯一二级索引，还需要保证插入后的的唯一性。接下来就分别针对这两种访问模式，讨论其加锁过程。

# Select、Update、Delete 加锁过程

InnoDB采用了前面所说的Ghost Locking的Delete实现，也就是对记录Delete的时候，并不会做真正的删除，而是仅仅在这条Record上设置Delete Mark标记，也就是将Delete操作转换成一次Update操作，依赖后台的Undo Purge过程清理。这样的好处是避免了Delete操作对其右侧区间锁的需要，又可以规避Rollback时Insert可能的空间不足问题。因此，Delete操作可以看做是一种特殊的只修改记录Delete Mark标记的Update操作，他们的加锁过程也是一致的。

Selete、Update以及Delete语句，经过MySQL前面的SQL解析、优化、生成执行计划后，确定要使用的索引或者直接进行主键索引的全表扫描，之后就是通过一种迭代器的访问方式来遍历这个索引上的记录：首先，通过**ha_innobase::index_read**定位到满足where条件的第一条记录，加锁并访问、修改或者删除；然后，通过**ha_innobase::general_fetch**依次去遍历下一条满足条件的记录，同样加锁并访问、修改或者删除，直到遇到不满足条件的记录或结尾。这种SQL层和InnoDB层的交互模式如下如所示：

![locking_for_select](http://catkang.github.io/assets/img/innodb_lock/lock_for_select.png)

index_read和general_fetch这两个函数的核心逻辑都实现在**row_search_mvcc**中，row_search_mvcc中会根据上层指定的查找条件，在选定的索引上搜索满足条件的记录，这个函数是InnoDB非常核心但也非常冗长的函数。之所以复杂，是因为其中融合了太多的逻辑和优化，本文这里会先忽略掉为了优化而存在的，Record Buffer以及Adaptive Hash Index的相关逻辑，对于快照读实现的MVCC也将在后面的文章再详细介绍，这里仅关注这个函数中为修改或者加锁读服务的加锁逻辑。对于第一条的查询，也就是通过index_read的访问，需要通过**btr_pcur_open_with_no_init**先去对应索引B+Tree上去搜索，获得指向满足条件记录的cursor，而对于后续general_fetch进来的查询，会利用前一次查询缓存的cursor，通过cursor所指向记录的next指针或者叶子节点之间的链表指针，可以实现对当前索引B+Tree上之后记录的一次遍历，通过**sel_set_rec_lock**加合适的锁，并检查是否满足条件，其中会区分是主索引还是二级索引，分别调用**lock_clust_rec_read_check_and_lock**和**lock_sec_rec_read_check_and_lock**函数；对于修改操作或者非覆盖索引的查询，还需要回表主索引，通过**lock_clust_rec_read_check_and_lock**对主索引上的对应记录加**Record Lock**（LOCK_REC_NOT_GAP）。row_search_mvcc的加锁规则，可以总结为一句话：

> **对所有扫描到的记录(2)加合适的锁(1)，并尽量缩小加锁范围(3)**

这里我们分别解释这句话中的三个关键的点：

**（1）合适的锁：**

所谓合适的锁，首先是Lock Mode的选择，这个比较简单，对于写操作加写锁（X_LOCK），对于只读操作加读锁（S_LOCK）。其次是Lock Type的选择，在Read Committed及以下的隔离级别时，只对记录加**Record Lock**（LOCK_REC_NOT_GAP）。在Read Repeatable隔离级别下，对当前记录及其之前的区间加**Next Key Lock**（LOCK_ORDINARY）。这里说的合适的锁是最充分的，第3点钟会介绍其中可以优化的地方。

**（2）所有扫描到的记录**

一次SQL访问，扫描到的记录跟这张表上的索引，以及执行计划中的索引选择有关，比如命中索引的查询，会从二级索引的B+Tree入手，依次对扫描到的记录加锁；而没有合适的二级索引，或者执行计划没有选择到最优的索引的情况下，可能需要通过主索引走全表扫描，这个时候就会对全表的记录都进行加锁。需要注意的是，这里需要加锁的记录不止包括用户可见的记录，还包括Delete Mark的记录，这种记录并不会被用户看到，但是确实存在在B+Tree上，并且可以作为加锁的对象。产生Delete Mark记录的原因主要有两个，一个是上面提到的对Delete操作的Ghost Record的设计，被删除的记录在事务提交并被后台Purge操作清除之前，就会一直以Delete Mark的状态存在；第二个原因是，InnoDB的二级索引实现，所有对二级索引的修改除了修改Delete Mark标记本身，都会转换成一次删除和一次新纪录的插入，这次删除同样会遗留一个Delete Mark的记录。当然对于Delete Mark记录的加锁是可以优化的，这点在下面第3点中介绍。

**（3）尽量缩小加锁范围**

按照上述的方式加锁并在事务生命周期持有这把锁，是足够保证对应隔离级别下对Non-Repeatable或者Phantom异象的排除的。在一些确定性的场景下，存在一些缩小加锁范围来降低所冲突，提升并发的空间，InnoDB的这种优化包括两种，一种是减少加锁对象，比如将**Next Key Lock**（LOCK_ORDINARY）变成**Record Lock**（LOCK_REC_NOT_GAP）或者**Gap Lock**(LOCK_GAP)，另一种是缩短持有锁的时间，比如一些可以提前放锁的场景。具体的优化如下：
1. Read Committed及以下隔离级别时，对不满足条件的记录会在加到锁后提前放锁，包括上面提到的Delete Mark的记录，以及InnoDB返回MySQL后，MySQL判断不符合Where条件的记录。这是由于Read Committed隔离级别并不保证不出现幻读（Phantom Read），而这些记录又属于非用户可见的，可以看做是由于MySQL的底层实现带来的多余加锁，因此虽然看似违反了2PL但并不会造成错误的后果。但需要注意的是这些锁还是在加锁之后才又释放的，因此虽然窗口很小但还是会有锁等待甚至是死锁的可能。这也是一些极端情况下，在Read Committed隔离级别下访问不同Key的事务也有概率出现死锁的原因[[6]](https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-isolation-levels.html)。
1. Read Repeatable及以上隔离级别时，对于等值查询，当遍历到第一个不满足查询条件的记录时，对这个记录加**Gap Lock**(LOCK_GAP)，而不是正常的**Next Key Lock**（LOCK_ORDINARY）来降低锁冲突。
1. Read Repeatable及以上隔离级别时，对于等值查询，对于唯一索引上的非Delete Mark的记录，加**Record Lock**（LOCK_REC_NOT_GAP）而不是**Next Key Lock**（LOCK_ORDINARY）。这是因为在唯一索引上满足等值查询的记录最多只能有一条，所以只要对这个记录加记录锁就不存在后续同样满足条件的记录被插入的问题。但对Delete Mark记录是不可以的，比如二级索引上就可以存在重复的Delete Mark记录。

我们这里以一个Read Repeatable隔离级别下的加锁读为例，如下图所示，t1和t2的表结构类似，都有一个主键id、一个整形的k1和一个content列，区别只是k1上的二级索引，左边的t1表是非唯一二级索引idx_k1，右边的t2表是唯一二级索引un_k1。对两张表通过k1列做等值加锁读。

![lock_select](http://catkang.github.io/assets/img/innodb_lock/lock_select_example.png)

先来看左边的t1表，按照我们上面介绍的加锁过程，由于where条件命中索引idx_k1，先通过index_read定位到idx_k1上第一条满足k1=10的记录（10, 2），加**Next Key Lock**（LOCK_ORDINARY），如图中的记录标红及指向前一个字段的红色箭头，并回表对对应的主键记录加**Record Lock**（LOCK_REC_NOT_GAP）；之后，general_fetch同样对（10, 5）加**Next Key Lock**（LOCK_ORDINARY），对主键记录加**Record Lock**（LOCK_REC_NOT_GAP）；最后，general_fetch扫描到（18, 4），由于已经不满足条件，且是等值查询，因此，根据上面讲到的第2种缩小锁范围优化，退化为**Gap Lock**（LOCK_GAP）。而对于右边的t2表，由于是唯一索引上的等值查询，根据第3种缩小范围优化，**Next Key Lock**（LOCK_ORDINARY）退化为**Record Lock**（LOCK_REC_NOT_GAP），并回表对主键项加**Record Lock**（LOCK_REC_NOT_GAP）。这个加锁的结果从performance_schema.data_locks中也可以看到，如下图所示：

![lock_select_screen](http://catkang.github.io/assets/img/innodb_lock/lock_select_screen.png)

对于Update和Delete操作，在第一步通过index_read和general_fetch这两个函数中的row_search_mvcc获取到一条满足条件的记录的同时，已经持有了必要的二级索引或主索引上合适的锁，之后再通过**row_upd**去真正做几路的Update或Delete的时候，可能还需要获取额外的锁，一个简单的例子是，经过主索引的查找之后，需要Update一个二级索引的列，那么这个时候在row_upd中最终会调用**lock_sec_rec_modify_check_and_lock**对要修改的二级索引上的记录也加上锁，不过这里如果不需要等待，会走隐式锁的逻辑，关于这部分我们会在后面介绍。



# Insert加锁过程

与上面所讲到Selete、Update、Delete不同，Insert操作的访问模式不需要根据Where条件的Search，而是直接定位目标记录在B+Tree上的位置，然后完成插入，在插入之前需要通过Lock的判断来避免出现Non-Repeatable或者Phantom。除此之外，索引的唯一性保证的要求会使得Insert过程变得稍微复杂一些，这种唯一性的要求，包括主索引（Primary Index）和唯一二级索引（Unique Index），简单的Insert语句在遇到唯一性冲突（Duplicate Key）的时候会直接报错返回，如果是Insert on duplicate key update，这个Insert操作就会转换为一次Update，而如果是Replace，就会转换为一次Delete加Insert的操作，如下图交互图所示：

![lock_insert](http://catkang.github.io/assets/img/innodb_lock/lock_insert.png)

为了InnoDB能够正确区分，MySQL会首先将操作的不同类型记录在trx->duplicates中，TRX_DUP_IGNORE表示是Insert ... on duplicate key update，TRX_DUP_REPLACE表示是Replace，都没有的话就是普通的Insert。之后通过**write_row**接口，并终会调用到**row_ins**函数，这个函数中会依次对主索引和所有二级索引完成插入。其中对主索引调用**row_ins_clust_index_entry_low**函数，对二级索引调用**row_ins_sec_index_entry_low**函数。这两个函数中的操作都可以分为**唯一性检查**和**插入**两个部分。

**唯一性检查：**

对于主索引和唯一二级索引，当通过btr_pcur_open定位到这个索引B+Tree的插入位点后，如果发现要插入的值已经存在，就触发了唯一性检查的失败，这是需要对已经存在的记录加锁，然后返回DB_DUPLICATE_KEY的错误。主索引上的唯一性检查失败的处理函数是**row_ins_duplicate_error_in_clust**，这个函数的主要作用，就是对遇到的重复记录加锁，来保证当前事务的隔离级别要求，其中会通过**lock_clust_rec_read_check_and_lock**对已存在的重复Key完成加锁。主索引上的加锁规则比较简单，首先，是锁模式的判断，对于普通的Insert，由于其后续在MySQL会直接报错返回，因此对重复Key可以当做是一次只读操作，加读锁（LOCK_S）即可，而对于Duplicate Key Update或者Replace语句，由于当前语句后续会对这个重复Key做写操作，需要加写锁（LOCK_X）。对于锁类型也很明确，在Read Committed及以下的隔离级别时加**Record Lock**（LOCK_REC_NOT_GAP），在Read Repeatable及以上隔离级别时，加**Next Key Lock**（LOCK_ORDINARY）。

唯一二级索引的唯一性检查失败处理函数在**row_ins_scan_sec_index_for_duplicate**，从名字上看比主索引多了一个scan的概念，其实已经阐明了唯一二级索引相对于主索引最大的区别，就是Duplicate Key可能有多个，这是由于InnoDB对二级索引的实现导致的，二级索引上的记录包含了二级索引的字段和对应的主键字段，并且二级索引上的所有修改都会转换为一次Delete和Insert。因此，即使是唯一二级索引，同样的Key也可能存在多条主键不同的，标记为Delete Mark的记录，这些记录也是需要加正确的锁来保证隔离级别的。当发现插入点有重复的记录时，**row_ins_scan_sec_index_for_duplicate**中首先会以PAGE_CUR_GE模式重新搜索B+Tree，来找到有相同二级索引Key的第一条记录，然后向后依次遍历每一条Delete Mark的相同Key记录，直到遍历到非相同Key或者非Delete Mark的记录，对遇到的每一个记录通过**lock_sec_rec_read_check_and_lock**加合适的锁。

普通的Insert语句加加读锁（LOCK_S），Duplicate Key Update或者Replace语句需要加写锁（LOCK_X）。然而，在锁类型的选择上却跟主索引非常不同，无论是什么隔离级别这里加的都是**Next Key Lock**（LOCK_ORDINARY）。 这一点非常特殊，意味着即使是RC隔离级别，事务依然有可能持有**Next Key Lock**（LOCK_ORDINARY）这种范围比较大的锁。为了保证每一个区间都安全，这种加锁甚至要加到第一个Key不相等的记录上，虽然在8.0.26之后的版本，最后这个不相等记录上的锁已经优化为了**Gap Lock**(LOCK_GAP)。如下图所示：

![lock_insert_example](http://catkang.github.io/assets/img/innodb_lock/lock_insert_example.png)

这个示例中在Read Commited隔离级别下，在阻止后台Purge后上删除2，插入5，再删除5，构造了唯一二级索引uk_k1上有两个k1=10的Delete Mark记录，然后在插入（10, 'G'）的时候，在uk_k1上的加锁情况，可以看出在（10, 2, DEL）和（10, 5, DEL）上加了**Next Key Lock**（LOCK_ORDINARY），并在（18, 4）上加了**Gap Lock**（LOCK_GAP）。

这种在Read-Committed隔离级别加**Next Key Lock**（LOCK_ORDINARY） 的行为在一些场景下会导致明显的锁冲突上升甚至是死锁[[7]](https://baotiao.github.io/2022/04/22/unique-key-check.html)[[8]](https://baotiao.github.io/2023/06/11/innodb-replace-into.html)[[9]](https://baotiao.github.io/2024/03/19/primary-key-deadlock.html)，在社区也引发广泛的讨论[[10]](https://bugs.mysql.com/bug.php?id=68021)，一度被当做是Bug修复，改成在Read-Committed隔离级别加**Record Lock**（LOCK_REC_NOT_GAP），不过这个修复很快被回退掉，因为他引发了更严重的唯一性被破坏的问题。**根本原因在于，这里得Next Key Lock（LOCK_ORDINARY） 不仅仅承担了隔离性保证的问题，还承担了唯一性保证的责任**，按照我们上面的讨论，如果仅仅是为了隔离性，在Read Committed隔离级别下只需要加**Record Lock**（LOCK_REC_NOT_GAP）即可，甚至这种Delete Mark的记录上的锁都是可以提前释放的。但为了保证唯一性，就需要做到唯一性检查成功之后的插入一定不会遇到冲突，Primary Key上比较简单，因为相同的Key的记录最多只能有一个，持有这个记录的**Record Lock**（LOCK_REC_NOT_GAP）就是足够的，但二级索引由于InnoDB的实现，同样的Key是可以存在多个主键不同的Delete Mark记录的，这就要求这些重复的Key之间的所有区间在唯一性检查到Insert之间的都是安全的，不会有其他Insert进来，因此需要持有**Next Key Lock**（LOCK_ORDINARY） 来进行保护。这种责任上的复用，导致了锁类型的扩大化，并且由于锁的生命周期是到事务提交的，就会导致上面提到的冲突扩大。有两种可行的优化思路，一种是用生命周期更小的Latch代替事务锁做唯一性检查；另一种是缩小用于唯一性检查的锁的生命周期到语句级，而不是事务级[[10]](https://bugs.mysql.com/bug.php?id=68021)。

**实际插入过程：**

经过唯一性检查后，如果发现有重复，InnoDB会返回DB_DUPLICATE_KEY错误。如果没有发现冲突，会继续当前索引上的插入。这里需要注意的是对Delete Mark记录的处理，对于Delete Mark的记录，会在上述流程中加锁，但不会真正的被当做重复Key返回DB_DUPLICATE_KEY的，而是转换成一次对Delete Mark标记的Update，对于二级索引上只有Key相同的Delete Mark记录会当做没有重复继续Insert。我们这里重点还是关注其中的加锁过程，这里对Delete Mark的Update会调用**btr_cur_optimistic_update/btr_cur_pessimistic_update**完成[[13]](https://catkang.github.io/2025/03/03/mysql-btree.html)，这两个函数里面最终都会调用**lock_rec_lock**对要修改的记录加锁，这里无论是什么隔离级别都是加**Record Lock**（LOCK_REC_NOT_GAP）写锁。

对于Insert操作，会调用**btr_cur_optimistic_insert/btr_cur_pessimistic_insert**完成，其中会统一调用**lock_rec_insert_check_and_lock**对要插入位点的后面一个Record尝试加**Gap Lock(LOCK_GAP) | LOCK_INSERT_INTENTION**锁。注意到这里相对于普通的**Gap Lock**(LOCK_GAP)多了一个**LOCK_INSERT_INTENTION**标记，并且只有在发生冲突的时候这个锁才会真正放到锁等待队列中。这其实是**Instant Lock优化**的一种实现[[5]]((https://catkang.github.io/2022/01/27/btree-lock.html))，其本质是利用Insert操作之后新的记录就会存在的特点，将事务生命周期的Gap Lock转换为Latch，也就是InnoDB中的Page mutex。假设事务T要插入记录M，其后继记录是Y，M所在的Page是q，那么这个加锁过程如下图伪代码显示：



```c++
Search（M，Y）and Hold Latch(q);

/* XLock(Gap Y) no need any more */
XCheck(Gap Y); // LOCK_INSERT_INTENTION

Insert M into q
XLock(M); // Implicit Lock
  
Unlatch(q);
....

T Commit and Unlock(M)
```



可以看出，（M，Y）之间的Gap锁被一次LOCK_INSERT_INTENTION Check代替，并没有真正的产生锁，这个过程和插入新的Record是在Page q的Latch保护下进行的，因此这个中间过程是不会有其他事务进来的，等Latch释放的时候，新的Record其实已经插入，这个（X，Y）的区间已经被划分成了，（X，M）以及（M，Y），新的事务只需要对自己关心的Gap加锁即可。除此之外，伪代码中的XLock(M)这一步，其实在InnoDB实现上也没有真实的动作，而是利用了新插入记录上维护了当前事务的事务ID这个特点，来做隐式的锁判断，对于隐式锁（ Implicit Lock）后面的章节会做更详细的介绍。通过隐式锁可以进一步减少Insert过程的加锁本身的开销。

另外，InnoDB的还实现了**Fence Key**的优化，我们知道**Next Key Lock**（LOCK_ORDINARY）是加在区间的右侧记录上的。前面讲到，当插入一条记录的时候，需要去判断其下一个记录上是不是有**Next Key Lock**（LOCK_ORDINARY）保护。如果正好是当前Page的最后一条记录，这个时候就需要去访问这个Page的后继节点，如果这个Page不在Buffer Pool还需要从磁盘加载。但我们其实并不需要访问后面Page的数据，这个操作就会引入了不必要的开销。而InnoDB的实现上，通过在Page的哨兵记录Supremum[[13]](庖丁解InnoDB之B+Tree)上维护**Gap Lock**（LOCK_GAP），来避免了这种情况的发生。为了维护这个Lock，所有遍历Record加锁的过程中，如果遇到Supremum，也是需要留一个**Gap Lock**（LOCK_GAP）的，并且发生Page合并分裂这种操作的时候，Page Supremum上的Lock也需要被合适地处理，后面的物理层修改的部分会介绍这部分内容。

# Lock信息维护

上面介绍的Select、Update、Delete以及Insert等SQL语句的加锁需要最终都会在锁管理系统（Lock Management）中完成，这里把他们放到一起，如下图所示：

![lock_entrance](http://catkang.github.io/assets/img/innodb_lock/lock_entrance.png)

锁管理系统需要(1)维护当前全局的事务加锁和锁等待的信息，(2)在有新的加锁需求的时候，需要判断跟当前已有事务锁是否冲突，如果冲突需要将新的加锁需求挂起。(3)当有事务锁被释放掉的时候，挂起等待在这个锁上的请求应该被唤醒并重新完成加锁，继续后续的操作。同时，(4)为了避免过长的锁等待，还需要有锁超时，以及死锁检测及处理机制。

首先我们来看锁信息的维护方式，InnoDB的加锁对象是索引叶子节点上的Record或者是Record之间的区间，而对区间的加锁最终也是作用于区间的右边界Record上的。实现上，采用了叶子节点的Page No号加**Heap No**的方式来唯一定位一个索引上的Record，Heap No是一条Record在这个Page上的唯一编号，在这个Record加入到Page上的时候递增分配，相当于Page内部的物理偏移。

内存中维护一个Lock信息的结构是**lock_t**，其中记录了这个Lock所加锁的Record的Page No以及Heap No信息。一把锁（lock_t）是属于某一个事务的，从这个事务持有的堆内存上分配空间。一个事务的生命周期中可能持有很多Lock，这些Lock在事务的内存结构trx_t上，穿成一个链表**trx_locks**。同时，锁（lock_t）又是针对Record对象的，需要有全局的锁持有和等待信息，这个信息维护在全局数据结构**lock_sys_t**上，其中维护了名为**rec_hash**的哈希表，采用链表的方式处理冲突，承担前面讲到的Lock Table的作用。需要注意的是这个哈希表是以Space ID加Page No来做哈希的，并不包含Heap No，也就是说同一个Page上的所有Record的会串在同一个Hash Key的链表上。这样的选择可以有效的控制哈希表的元素膨胀，但带来的代价就是判断锁冲突的时候可能需要做较长的链表遍历。如下图所示：

![lock_manager](http://catkang.github.io/assets/img/innodb_lock/lock_manager.png)

可以看出**lock_t**结构中，通过trx_locks串到其所属于的事务结构的**trx_locks**链表上；又通过hash指针挂到全局的锁哈希表**rec_hash**上；通过trx_t指针和dict_index_t指针，分别指向其属于的事务和Record所在的索引；通过Space Id和Page No表明加锁对象Record所在的Page；出于空间优化的考虑，Heap No信息被记录在lock_t结构结束后的后续**n_bits**长度的**Bitmap**中，持有的Heap No对应的位置会标1，也就是说，一个lock_t可以表示同一个Page上多个Record的相同类型的锁信息，这在有Record遍历加锁的场景下会非常友好；最后lock_t上还维护了一个32位的**type_mode**，紧凑地标记了当前Lock的模式及类型信息。需要说明的是，表锁在InnoDB中也是相同的一套维护方式，只是这里的lock_rec_t部分会替换成表锁需要的信息，同时type_mode中的前四位中可能出现LOCK_IX、LOCK_IS的锁类型，这里不过多展开。

# Lock的申请与等待

大多数的加锁请求最终都会进入**lock_rec_lock**函数中，其中的加锁逻辑分为Fast和Slow两个路径，Fast路径处理一些简单的、不需要做冲突判断，但可能更常见的情况，比如当前Page上还没有锁，或者当前Page上只有一个lock_t结构，还是当前事务的，且锁类型跟本次需求相同，这种情况在遍历加锁的场景很常见，那么就可以直接设置这个lock_t上的Bitmap的对应位置即可。

Fast路径不能处理的才会进入到Slow路径**lock_rec_lock_slow**，也是InnoDB核心的加锁逻辑，这里首先，通过**lock_rec_has_expl**过滤掉当前事务已经持有了更高级别的锁的情况；然后，通过**lock_rec_other_has_conflicting**判断要加的锁与当前已经存在的锁之间有没有冲突，如果没有冲突进入**lock_rec_add_to_queue**直接创建锁结构，注意这里同样会尝试寻找设置Bitmap的机会；如果有冲突需要等待，则进入**add_to_waitq**，这个函数在创建锁结构后，还需要通过**deadlock_check**函数来做死锁检测，关于死锁的内容会在后面介绍。Insert场景的加锁逻辑比较特殊，前面提到过，Insert会先用Gap Lock(LOCK_GAP) | LOCK_INSERT_INTENTION通过**lock_rec_other_has_conflicting**判断锁冲突，只有需要等待才进入add_to_waitq。如下图所示：

![lock_function](http://catkang.github.io/assets/img/innodb_lock/lock_function.png)

判断是否需要等待的函数是**lock_rec_other_has_conflicting**，其中会从全局的**rec_hash**哈希表中用要加锁的Page No查找到对应链表，然后从开头向后遍历这个链表中所有关于要加锁的Record的的Lock（lock_t），针对这样每一个Lock，用**lock_rec_has_to_wait**去判断是不是需要等待，抛开一定不需要等待的同事务情况，这里会进行两个部分的检查。首先是锁mode的兼容性检查，对记录锁而言，只包含读锁（LOCK_S）和写锁（LOCK_X）两种，比较简单，这里O表示不互斥，X表示互斥：

|                   | 读锁（LOCK_S) | 写锁（LOCK_X） |
| ----------------- | ------------- | -------------- |
| **读锁（LOCK_S)** | O             | X              |
| 写锁（LOCK_X）    | X             | X              |

也就是只有读锁（LOCK_S)之间是相互兼容的，可以直接判定不需要等待，除此之外的情况，都需要进一步去比较锁的类型：

|                                                 | **Next Key Lock**（LOCK_ORDINARY） | **Gap Lock**（LOCK_GAP） | **Gap Lock（LOCK_GAP）+ LOCK_INSERT_INTENTION** | **Record Lock**（LOCK_REC_NOT_GAP） |
| ----------------------------------------------- | ---------------------------------- | ------------------------ | ----------------------------------------------- | ----------------------------------- |
| **Next Key Lock（LOCK_ORDINARY）**              | X                                  | O                        | O                                               | X                                   |
| **Gap Lock（LOCK_GAP）**                        | O                                  | O                        | O                                               | O                                   |
| **Gap Lock（LOCK_GAP）+ LOCK_INSERT_INTENTION** | X                                  | X                        | O                                               | O                                   |
| **Record Lock（LOCK_REC_NOT_GAP）**             | X                                  | O                        | O                                               | X                                   |

这个表格的第一列是新来的Lock请求类型，而第一行是在哈希表中遍历遇到的一个已有的Lock的类型，这里来简单介绍下这个表格中所包含的信息：

- **Next Key Lock**（LOCK_ORDINARY）和**Record Lock**（LOCK_REC_NOT_GAP）同样对这个Heap No上的Record有加锁的需求，因此他们是互斥的，表格的四个角都是X；
- **Gap Lock**（LOCK_GAP）和**Next Key Lock**（LOCK_ORDINARY）中对Gap的保护部分的唯一作用，就是阻止后续这个区间的插入，而他们之间是相互兼容的，也就是同一个Gap上可以有多个**Gap Lock**（LOCK_GAP）同时存在，所以表格中只有在**Gap Lock（LOCK_GAP）+ LOCK_INSERT_INTENTION**这一行的前两个是X；
- **Gap Lock（LOCK_GAP）+ LOCK_INSERT_INTENTION**这种锁的唯一作用就是检查这个区间上是不是有对Gap的锁保护，一旦发现需要等待，产生并加入到**rec_hash**之后，他对后面的锁请求是没有任何影响的，所以可以看到他这一列全都是O；

通过冲突判断后，**lock_rec_add_to_queue**和**add_to_waitq**函数最终都会通过**lock_alloc**从事务上分配**lock_t**结构需要的内存空间，并完成上述成员的填充，为了避免lock_t频繁分配释放空间带来的开销，事务会在初始化的时候准备一些（8个）缓存的lock_t在事务的**rec_pool**结构上作为备用。之后，通过**lock_add**加入到事务的**trx_locks**链表末尾，以及全局的锁哈希表**rec_hash**上的对应cell链表的末尾。其中需要等待的Lock会在32位的type_mode中标记LOCK_WAIT。同时，由于都是加载链表的末尾，一个LOCK_WAIT状态的锁本身也会造成后续Lock锁的等待。一旦发生锁等待，这一系列的**xxx_check_and_lock**函数都会最终向外返回**DB_LOCK_WAIT**错误，外层在收到这个报错后就会进入**row_mysql_handle_errors**处理并最终将当前线程挂起，并且在全局的lock_sys->waiting_threads中找一个空闲的slot来注册event，供后续Lock需求被满足的时候唤醒。



# 死锁检测

被Lock阻塞的事务需要等到对应的锁被释放后，才能继续后面的操作，但如果不同的事务之间发生互相等待，也就是死锁，那么这种等待将会无限持续下去，虽然MySQL提供了**innodb_lock_wait_timeout**参数来配置等锁的超时时间，可以一定程度缓解这个问题，但超时时间内的无效等待还是存在的。同时，由于事务对记录的访问顺序是外部数据库的使用者决定的，站在数据库的角度是没有办法像内部Latch那样，通过良好设计的加锁顺序来避免死锁的。因此，尽快发现并解决这种可能的死锁是必要的。

![lock_deadlock](http://catkang.github.io/assets/img/innodb_lock/lock_deadlock.png)

如上图所示，是某一个时刻，红黄蓝三个事务持有的锁及他们的等关系，其中实线是事务持有锁的链表，而虚线表示需要等待的锁，可以看出，这一时刻他们三个已经出现了互相等待的环，三个事务都陷入了无限的等待中。所谓的死锁检测，就是要发现这些等锁事务之间可能存在的等待环，一旦存在这样的环，就需要选择事务回滚，来打破死锁等待。在8.0.18之前的版本中，这个事情是在需要加锁等待的**add_to_waitq**函数中，通过**deadlock_check**函数来处理的，其中会从新加入等待的这个事务出发，沿着事务所等待的Lock，以及Lock之前有冲突的事务，对这个事务及锁的等待图，做深度优先遍历（DFS），来发现可能的等待环。发现环后，会从当前新增Lock的这个事务，和等待这个新增Lock的事务，这两个事务中根据优先级、修改的记录行数以及持有的Lock数，选择一个影响较小的作为**victim**回滚掉。由于是在每次有新增Lock等待的时候，都发起全局视图的检测，这种检测方式一定是最及时、最准确的，但整个DFS遍历的过程中为了保持这个等待图稳定需要持有Lock系统的Mutex，在大压力并且有大量锁等待的时候，死锁检测本身就会成为瓶颈，当死锁检测的开销超过死锁本身的时候这种做法就得不偿失了。

因此，在8.0.18之后的版本MySQL对这里做了大幅度的改造，总结起来包括三点：1）死锁检测过程从每次产生等待的用户线程add_to_waitq函数中，移到了后台线程中定时触发；2）从全程持有Lock系统的大锁到短暂持有，只用来获取一个当前等待的关系快照，之后基于这个快照做死锁检测，因此发现死锁后还需要重新获取Lock系统的大Mutex，并对候选事务做再次检查；3）检测的视角从事务->锁->事务的关系，简化为事务->事务的等待关系，这其中的信息丢失会导致一些场景下的死锁不能在第一时间发现。这种优化其实是一定程度上牺牲掉死锁检测的及时和准确，来换取整个系统开销的降低。从数据库整体角度来看，我认为这种权衡是划算的。无论如何，死锁检测本身会带来开销，可以通过**innodb_deadlock_detect**参数来关闭死锁检测，转而依赖**innodb_lock_wait_timeout**来结束锁等待。



# Lock的释放和唤醒

![lock_release](http://catkang.github.io/assets/img/innodb_lock/lock_release.png)

上图是InnoDB中发生锁的释放及后续锁的唤醒的调用场景。InnoDB采用2PL的加锁策略，也就是说在1）在事务生命周期的结尾，提交或者回滚的阶段才去释放全部持有的Lock。这个动作发生在**lock_trx_release_locks**函数里，其中会遍历当前事务的**trx_locks**链，依次对每一个Lock调用**lock_rec_dequeue_from_page**，将其从trx_locks以及全局的**rec_hash**上摘除。除了正常的，由用户语句发起的Commit或者Rollback之外，2）一些异常情况导致的事务终止，也会触发事务回滚以及Lock的释放，比如线程被Kill、锁等待超时、被更高优先级的事务抢占，或者被死锁检测当做victim回滚。发生这些异常情况的时候，这些事务本身可能还在锁等待的状态中，因此在进入到事务回滚释放全部锁之前，首先需要将这个事务从等待状态唤醒，这个过程同样会调用**lock_rec_dequeue_from_page**对这个等待的Lock先进行释放，之后被唤醒的中断事务重新获得线程执行，并在row_mysql_handle_error函数中完成事务回滚，并在lock_trx_release_locks中释放剩余的全部Lock。

上面的两种释放锁的时机，其实还都是符合直观的2PL（two Phase Locking）的，也就是在事务最后的放锁阶段进行。但其实在Read Commited及以下的隔离级别时，在事务运行的中间，也是有可能有放锁发生的。上面介绍过，在Select、Update、Delete 加锁过程中，SQL层会循环地通过index_read和general_fetch接口，从InnoDB中查找满足条件的记录并完成加锁，这个过程中，无论是否有条件下推，InnoDB一定需要先加锁，然后才能安全的访问这个记录，之后才能确定这个记录是否满足条件。如果遇到不满足条件，或者是被标记Delete Mark的记录，为了优化，会在InnoDB层（Delete Mark或者有条件下推）或者MySQL SQL层，在获取到记录之后，再对这个记录进行放锁。这个行为乍一看是违背2PL的，但由于这些记录本身就是本次访问不可见的，也就不会破坏MySQL Read Committed级别对可重复读的保证。虽然对不满足条件记录的加锁再放锁的间隔时间很短，但这个对不满足条件的记录加锁的动作，还是有可能导致一些极端情况下，即使是访问完全不同的记录的两个事务，也有发生互相等待甚至是死锁的可能。这种提前放锁的动作最终都会在**row_unlock_for_mysql**函数中完成，不同于之前的两种情况，这里只是清除了Lock对象上的Bitmap对应位，从而完成了放锁，而并不会对Lock结构做析构，也就是这个被释放的Lock对象依然会存在于rec_hash哈希表及事务的trx_locks链表中。这么做也是因为当前事务的生命周期其实还并没有结束，后续很有可能还有更多的锁的申请，保留的这个Lock对象后续可以在Fast加锁路径中设置Bitmap后即可使用，避免了频繁的Lock对象的申请和析构。

当一把锁被释放以后，之前等待在这把锁上的事务就有机会获得锁并继续运行，唤醒后续等待的事务的过程就是Lock Grant，上述三种放锁的场景最终都会通过**lock_grant**函数来完成锁的唤醒和授予。如果有多把锁都在同一个记录上，这个时候应该唤醒谁呢？InnoDB中很长时间以来采用的都是**FCFS(First Come First Served)**算法，也就是根据加入rec_hash中的顺序，先来的先被唤醒，这是一种很简单的算法，但由于缺乏对事务状况的判断，很多时候并不是最优的。《ContentionAware Lock Scheduling for Transactional Databases》提出，由于事务未来执行不可知，并且实际场景中可能有很复杂的依赖关系，再叠加各种锁的类型模式，选择最优解几乎是做不到的，但我们依然可以参考一些启发式的指标来判断优先唤醒谁会更好，比如哪个事务持有的锁比较多，哪个事务持有的锁阻塞的事务比较多，以及哪个事务持有的锁间接的阻塞的事务更庞杂。也就是[**CATS(Contention-Aware Transaction Scheduling)**[14]](https://www.vldb.org/pvldb/vol11/p648-tian.pdf)算法，InnoDB中在8.0.3开始在高锁争抢环境下引入CATS，并且在8.0.20彻底抛弃FCFS。

![lock_cats](http://catkang.github.io/assets/img/innodb_lock/lock_cats.png)

CATS的实现思路是为每个Lock赋予一个权重（Age or Weight），这个权重指示的是有多少个事务直接或者间接的等待在这把Lock上，如上图所示。当一把Lock被释放后，就会优先选择拥有更高权重的Lock进行唤醒（lock_grant)。8.0.20之前这个权重需要在每次有新的Lock加入时，持有lock_sys的大锁对所有受影响的Lock进行第一时间的更新，开销比较大， 8.0.20开始牺牲了一些这个权重的更新及时性，而将其更新任务交给后台的lock_wait_timeout_thread线程，同时增加了时间维度的权重考虑。



# 隐式锁和故障恢复

加锁的时候需要申请内存空间，初始化Lock对象，持有全局Lock Sys的Mutex将这个Lock对象加入到rec_hash，以及事务的trx_locks链表中，开销是不可忽略的。因此，InnoDB在实现上对这里做了一个优化，就是隐式锁。在有明确Record写入的场景中，比如新记录的Insert，或者Record修改之前的加锁，如果不存在锁冲突，加锁过程是跳过的。当后续有请求访问这条记录并尝试加锁的时候，在**lock_rec_lock**加锁之前，需要先判断当前记录上有没有这种隐式加锁的存在。主键上的判断比较简单，在**lock_clust_rec_some_has_impl**函数中，会直接检查记录上的Trx ID信息，结合当前的事务系统中的活跃事务链表，来判断写入的事务是不是已经提交，如果已经提交，那么可以安全的继续加锁访问这条记录，但如果这个事务还没有提交，就认为这条记录还是被写入事务持有锁的，也就是隐式加锁的，这个时候会通过**lock_rec_convert_impl_to_expl**将这个隐含存在的Lock，转换成一个显式的Lock对象并加入队列（**lock_rec_add_to_queue**）。这种利用记录上的Trx ID来隐含代表持有锁的方式就是隐式锁的核心思路。

但对于二级索引这个问题会变得复杂很多，因为InnoDB的二级索引上并没有记录对应事务的Trx ID，无法直接判断当前二级索引上的记录是谁写的， 需要回表到对应的主索引上判断，其实就是找当前主索引上对应的记录，**如果存在最新的还未提交的事务，有没有可能造成了我们看到的这个二级索引记录的写入**。如果有，那么就认为存在隐式锁需要升级成显式锁。简单的讲，这个可能性判断的流程是：定位到对应的主键索引记录， 判断其Trx ID，如果是一个未提交的事务，那么通过Roll Ptr溯源该事务所有在这条Record上的更改，通过比较记录主索引记录和二级索引记录的内容及Delete Mark标记，来做出可能性的判断。这里不再详细展开，只附流程图供参考：[Secondary Index Impl Lock](http://catkang.github.io/assets/img/innodb_lock/lock_impl.png)。也可以参考[Deep Dive into MySQL - Implicit Locks[15]](https://kernelmaker.github.io/MySQL-implicit-locks)中的相应介绍。

除了对加锁开销优化外，隐式锁在**故障恢复阶段**也起着重要的作用。从本文前面的介绍可以看出，所有的加锁状态的维护其实都是在内存中的，并没有持久化，那么一旦发生故障重启，这些加锁信息就全部都丢失了，但事务及其所有的修改还是在的：InnoDB在故障恢复流程中，会先通过Redo Log的回放还原所有Page级别的修改，然后扫描已经被Redo还原到最新的Undo Log Page中的活跃事务信息[[16]](https://catkang.github.io/2021/10/30/mysql-undo.html)，拿到尚未提交的事务列表，这些事务的内存结构会被重新创建出来，并在后台异步的完成回滚。但在这些事务异步回滚的过程中，InnoDB已经在接受并处理新的请求了，同样需要保证新的用户事务和后台回滚事务之间的正确性。这个时候，这些缺乏内存Lock信息，但其实已经被修改的记录，天然地就形成了一种隐式锁的场景，新的事务通过上述隐式锁的发现和转换机制，自然而然的解决掉了这个问题。



# 物理层修改

Lock是一个逻辑层的概念，负责的是事务之间的访问数据库的正确性，但维护Lock本身的结构又是物理层的，是维护在**rec_hash**哈希表中的，以Record的物理位置Heap no为加锁对象的物理结构。因此，当记录的物理位置发生变化的时候，不可避免的需要对上面的Lock做出调整，并且这个过程中，完全不应该影响Lock的逻辑语义，也就是事务之间的等待和被等待关系。本节就来介绍这些物理层变化导致Lock变化的操作，所有的这些调整一定要持有Lock Sys的大Mutex，来阻止同时刻的其他锁的判断及申请释放流程。首先来看单个Record变化的情况：

**新的Record插入**：前面介绍过，InnoDB通过对区间的右边界加**Next Key Lock**（LOCK_ORDINARY）或者**Gap Lock**（LOCK_GAP）来保护区间。那么，当新的Record完成插入之后，原来的区间就被切分成了前后两段。加入之前已经有在这个大区间上等待的Lock，这种切分会导致其保护的区间范围不足，因此，这个时候InnoDB会通过**lock_update_insert**将所有后继节点上的这种对区间保护的Lock，继承一份在新的Record上，作为一个**Gap Lock**（LOCK_GAP）。如下图所示，在插入10005之前10010上存在一个**Next Key Lock**（LOCK_ORDINARY），在10005插入完成后，区间被拆分为两段，并且在10005上从10010那里继承来一个**Gap Lock**（LOCK_GAP），还是由原来的事务持有：

![lock_physical_insert](http://catkang.github.io/assets/img/innodb_lock/lock_physical_insert.png)

**Record被真正删除**：由于采用了前面讲到的Ghost Record的方式，用户请求对Record的删除被变成了一次对Delete Mark标记的修改，来避免Delete过程对区间锁的依赖。但最终在Undo Purge流程中，这个Delete Marked的记录还是会被删除的，删除之后，原来的前后两个区间会合并成一个大的区间，因此，在InnoDB会通过**lock_update_delete**将之前所有对要删除Record上的，Gap保护Lock都继承一份到其后继节点上，还是由原来的事务持有。需要注意的是，在Read Repeatable隔离级别下，在要删除Record上的**Record Lock**（LOCK_REC_NOT_GAP）也会被后继节点继承为一个**Gap Lock**（LOCK_GAP），存在锁类型的放大，如下图所示：

![lock_physical_delete](http://catkang.github.io/assets/img/innodb_lock/lock_physical_delete.png)

**Record修改**：主键索引上在Key不变的修改，在逻辑上前后还是被认为是同一条记录的，但如果修改前后造成了Record长度的变大，之前的空间就不够放了，此时在物理上，这个Record会被换一个地方存放，对应的锁也会从旧的Heap No变化到新的上面去，这个过程中InnoDB的实现会借助Page上的Infimum Record来暂存Lock信息。不过由于Lock Sys全局Mutex的互斥，这个中间状态对其他事务是完全透明的。除了单个Record的变化外，B+Tree本身结构的变化也会导致Lock信息的改变。

**Page Reorganize**：当Page发生记录重排列之后，Page上的记录批量的发生位置变化，对应的Lock也会在**lock_move_reorganize_page**移动到新的位置上去，这个过程通过清除旧的Lock的Bitmap，然后通过**lock_rec_add_to_queue**对新的位置加Lock实现。

**Page分裂及合并**：类似的，当发生Page的分裂或合并的时候，会有批量的记录跨节点的移动，对应的Lock信息也会在**lock_move_rec_list_start**或**lock_move_rec_list_end**中对应的指向新的位置。除此之外，由于前面讲到的**Fence Key**的实现，Page上最右的哨兵记录Supermum会承担其后继节点第一个记录的Lock信息，因此发生Page分裂合并时，涉及到的Supermum记录上的Lock也需要做对应的处理，这里以常见的节点右分裂为例，如下图所示，首先，分裂点之后的Record移动到新的右节点的同时，上面的Lock也会通过**lock_move_rec_list_end**移动到新Page上去；之后在**lock_update_split_right**函数中调整两个Supermum记录上的Lock，包括将左节点的Supermum上的Lock移动到新的右节点的Supermum上，以及将右节点第一个Record上的保护Gap的Lock继承一份到左节点的Supermum上。如下图所示：

![lock_physical_split](http://catkang.github.io/assets/img/innodb_lock/lock_physical_split.png)

Page A分裂成Page A和Page B之后，一部分的记录从A转移到了B，他们上的Lock也跟着移动到新的Page No + Heap No上，之后，原Page上的Supermum上的Lock移动一份到Page B的Supermum上，并且将Page B上的第一个记录4上的**Next Key Lock**（LOCK_ORDINARY）继承一份成为Page A的Supermum的新的**Gap Lock**（LOCK_GAP）。



# 总结

本文首先介绍了MySQL的隔离级别实现，指出需要区分加锁访问和快照访问来进行讨论，并对比了MySQL跟标准ANSI的区别。之后概要介绍了InnoDB的Lock系统的设计及其作用。紧接着分别讨论了对于两种不同的SQL访问模式（Select、Update、Delete和Insert）下的加锁过程。之后引出InnoDB中的锁管理系统，并分别从Lock信息维护、加锁及等待、放锁及唤醒、死锁检测、隐式锁与故障恢复以及物理层修改的对应动作做详细的讨论。



# 参考

[1] [MySQL 8.0 Code. https://github.com/mysql/mysql-server/tree/8.0](https://github.com/mysql/mysql-server/tree/8.0)

[2] [数据库事务隔离发展历史. https://catkang.github.io/2018/08/31/isolation-level.html](https://catkang.github.io/2018/08/31/isolation-level.html)

[3] [浅析数据库并发控制机制. https://catkang.github.io/2018/09/19/concurrency-control.html](https://catkang.github.io/2018/09/19/concurrency-control.html)

[4] [MySQL 8.0 Reference Manual. 17.7.2.3  Consistent Nonlocking Reads. https://dev.mysql.com/doc/refman/8.0/en/innodb-consistent-read.html](https://dev.mysql.com/doc/refman/8.0/en/innodb-consistent-read.html)

[5] [B+树数据库加锁历史. https://catkang.github.io/2022/01/27/btree-lock.html](https://catkang.github.io/2022/01/27/btree-lock.html)

[6]  [MySQL 8.0 Reference Manual.17.7.2.1 Transaction Isolation Levels. https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-isolation-levels.html](https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-isolation-levels.html)

[7] [InnoDB unique check 的问题. https://baotiao.github.io/2022/04/22/unique-key-check.html](https://baotiao.github.io/2022/04/22/unique-key-check.html)

[8] [MySQL 常见死锁场景 -- 并发Replace into导致死锁. https://baotiao.github.io/2023/06/11/innodb-replace-into.html](https://baotiao.github.io/2023/06/11/innodb-replace-into.html)

[9] [MySQL 常见死锁场景-- 并发插入相同主键场景. https://baotiao.github.io/2024/03/19/primary-key-deadlock.html](https://baotiao.github.io/2024/03/19/primary-key-deadlock.html)

[10] [Unexplainable InnoDB unique index locks on DELETE + INSERT with same values. https://bugs.mysql.com/bug.php?id=68021](https://bugs.mysql.com/bug.php?id=68021)

[11] [Deep Dive into MySQL - Transaction lock - PART 1. https://kernelmaker.github.io/MySQL-Lock-1](https://kernelmaker.github.io/MySQL-Lock-1)

[12] [Deep Dive into MySQL - Transaction lock - PART 2. https://kernelmaker.github.io/MySQL-Lock-2](https://kernelmaker.github.io/MySQL-Lock-2)

[13] [庖丁解InnoDB之B+Tree. https://catkang.github.io/2025/03/03/mysql-btree.html](https://catkang.github.io/2025/03/03/mysql-btree.html)

[14] [Tian, Boyu, et al. "Contention-aware lock scheduling for transactional databases." *Proceedings of the VLDB Endowment* 11.5 (2018): 648-662.](https://www.vldb.org/pvldb/vol11/p648-tian.pdf)

[15] [Deep Dive into MySQL - Implicit Locks. https://kernelmaker.github.io/MySQL-implicit-locks.](https://kernelmaker.github.io/MySQL-implicit-locks)

[16] [庖丁解InnoDB之Undo LOG. https://catkang.github.io/2021/10/30/mysql-undo.html](https://catkang.github.io/2021/10/30/mysql-undo.html)
