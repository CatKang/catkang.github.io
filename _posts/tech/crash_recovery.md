# 数据库故障恢复历史



### 背景

在数据库系统发展的历史长河中，故障恢复问题始终伴随左右，也深刻影响着数据库结构的发展变化。通过故障恢复机制，可以实现数据库的两个至关重要的特性：Durability of Updates以及Failure Atomic，也就是我们常说的的ACID中的A和D。磁盘数据库由于其卓越的性价比一直以来都占据数据库应用的主流位置。然而，由于需要协调内存和磁盘两种截然不同的存储介质，在处理故障恢复问题时也增加了很多的复杂度。随着学术界及工程界的共同努力及硬件本身的变化，磁盘数据库的故障恢复机制也不断的迭代更新，尤其近些年来，随着NVM的浮现，围绕新硬件的研究也如雨后春笋出现。本文希望通过分析不同时间点的关键研究成果，来梳理数据库故障恢复问题的本质，其发展及优化方向，以及随着硬件变化而发生的变化。
文章将首先描述故障恢复问题本身；然后按照基本的时间顺序介绍传统数据库中故障恢复机制的演进及优化；之后思考新硬件带来的机遇与挑战；并引出围绕新硬件的两个不同方向的研究成果；最后进行总结。



### 问题

数据库系统运行过程中可能遇到的故障类型主要包括，Transaction Failure，Process Failure，System Failure以及Media Failure。其中Transaction Failure可能是应用程序的主动回滚，或者是[并发控制机制](http://catkang.github.io/2018/09/19/concurrency-control.html)发现冲突后的强制Abort；Process Failure指的是由于各种原因导致的进程退出，进程内存内容会丢失；System Failure来源于操作系统或硬件故障，同样会导致内存丢失；Media Failure则是存储介质的不可恢复损坏。

数据库系统需要正确合理的处理这些故障，从而保证系统的正确性。为此需要提供两个特性：

- **Durability：事务一旦Commit，即使发生故障，其影响的数据也会在回复后存在；**
- **Atomic：失败事务的所有修改都不可见**。

因此，故障恢复的问题描述为：**即使在出现故障的情况下，数据库能够通过提供Durability及Atomic特性，保证恢复后的数据库状态正确。**

然而，要解决这个问题并不是一个简单的事情，由于内存及磁盘不同的数据组织方式及性能差异，为了不显著牺牲数据库性能，长久以来人们对故障恢复机制进行了一系列的探索。



### Shadow Paging
1981年，JIM GRAY等人在《[The Recovery Manager of the System R Database Manager](http://courses.cs.washington.edu/courses/cse550/09au/papers/CSE550.GrayTM.pdf)》采用了一种非常直观的解决方式Shadow Paging[1]。System R的磁盘数据采用Page为最小的组织单位，一个File由多个Page组成，并通过称为Direcotry的元数据进行索引，每个Directory项纪录了当前文件的Page Table，指向其包含的所有Page。采用Shadow Paging的文件称为Shadow File，如下图中的File B所示，这种文件会包含两个Directory项，Current及Shawing。

![shadow paging](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/shadow paging.png)

事务对文件进行修改时，会获得新的Page，并加入Current的Page Table，所有的修改都只发生在Current Directory；事务Commit时，Current指向的Page刷盘，并通过原子的操作将Current的Page Table合并到Shadow Directory中，之后再返回应用Commit成功；事务Abort时也只需要简单的丢弃Current指向的Page；如果过程中发生故障，恢复时只需要恢复Shadow Directory，相当于对所有未提交事务的回滚操作。Shadow Paging很方便的实现了：

- Durability：事务完成Commit后，所有修改的Page已经落盘，合并到Shadow后，其所有的修改可以在故障后恢复出来。
- Atomic：无论是正常的回滚事务还是故障恢复后回滚的未提交事务，由于从未影响Shadow Directory，因此其所有修改不可见。

虽然Shadow Paging设计简单直观，但它的一些**缺点**导致其并没有成为主流，首先不支持Page内并发，Shadow操作是在Page级别做的，因此Commit或Abort也是以Page为单位整体进行的，一个Commit操作会导致其Page上所有事务的修改被提交，因此一个Page内只能包含一个事务的修改；其次不断修改Page的物理位置，导致很难将相关的页维护在一起；另外，对大事务而言，Commit过程中需要在关键路劲上修改Shadow Directory，其本身开销可能很大，同时这个操作还必须保证原子；最后，增加了垃圾回收的负担，包括对失败事务的Current Pages和提交事务的Old Pages的回收。



## WAL

由于传统磁盘顺序写远大于顺序写的特征，采用Logging的故障恢复机制意图利用顺序写的Log来记录对数据库的操作，并在故障恢复后通过Log内容将数据库恢复到正确的状态。简单的说，采用Log机制的数据库需要在每次修改数据内容前先写顺序写对应的Log，同时**为了保证恢复时可以从Log中看到最新的数据库状态，要求Log要先于对应的数据内容落盘，也就是常说的Write Ahead Log，WAL**。除此之外，事务完成Commit前还需要在Log中记录对应的Commit标记，以供恢复时通过Log了解当前的事务状态，因此还需要关注Commit标记和事务中数据内容的落盘顺序。根据Log中记录的内容可以分为三类：Undo-Only，Redo-Only，Redo-Undo。

#### Undo-Only Logging
Undo-Only Logging的Log记录可以表示未<T, X, v>，事务T修改了X的值，X的旧值是v。事务提交时，需要通过强制Flush保证Commit标记落盘前，对应事务的所有数据落盘，即**落盘顺序为Log记录->Data->Commit标记**。恢复时可以根据Commit标记判断事务的状态，并通过Undo Log中记录的旧值将未提交事务的修改回滚。我们来审视一下Undo-Only对Durability及Atomic的保证：

- Durability：Data强制刷盘保证，已经Commit的事务由于其所有Data都已经在Commit标记之前落盘，因此会一直存在；
- Atomic：Undo Log内容保证，失败事务的已刷盘的修改会在恢复阶段通过Undo日志回滚，不再可见。

然而Undo-Only依然有Page内并发的问题，如果两个事务的修改落到一个Page中，一个事务提交前需要的强制Flush操作会导致同Page所有事务的Data落盘，可能会早于对应的Log项从而损害WAL。同时，Commit前的强制数据刷盘会导致关键路径上过于频繁的磁盘随机访问。

#### Redo-Only Logging
不同于Undo-Only，采用Redo-Only的Log中记录的是修改后的新值。对应地，Commit时需要保证Log中的Commit标记需要在事务的任何事务罗盘前落盘，即**落盘顺序为Log记录->Commit标记->Data**。恢复时同样根据Commit标记判断事务状态，并通过Redo Log中记录的新值将已经Commit，但数据没有落盘的事务修改重放。

- Durability：Redo Log内容保证，已提交事务的未刷盘的修改，利用Redo Log中的内容重放，之后可见；
- Atomic：阻止Commit前Data落盘保证，失败事务的修改不会出现在磁盘上，自然不可见。

Redo-Only同样有Page内并发的问题，同Page中的多个不同事务，只要有一个未提交就不能刷盘，这些数据全部都需要维护在内存中，会造成较大的内存压力。

#### Redo-Undo Logging

可以看出的只有Undo或Redo的Logging方式的问题主要来自与对Commit标记及Data落盘顺序的限制，而这种限制归根结底来源于Log信息中对新值或旧值的缺失。因此Redo-Undo采用同记录新值和旧值的方式来取消对刷盘顺序的限制。

- Durability：Redo 内容保证，已提交事务的未刷盘的修改，利用Redo Log中的内容重放，之后可见；
- Atomic：Undo内容保证，失败事务的已刷盘的修改会在恢复阶段通过Undo日志回滚，不再可见。

如此一来，同Page的不同事务提交就变得很简单。同时可以将连续的数据攒着进行批量的刷盘已利用磁盘较高的顺序写性能。


#### Force and Steal

从上面看出，**Redo和Undo内容分别可以保证Durability和Atomic两个特性，其中一种的缺失需要用严格的刷盘顺序来弥补**。我们将Commit时是否需要强制刷盘称为**Force or No-Force**，Commit前数据是否可以提前刷盘，称为**Steal or No-Steal**，如果把Shadow-Paging看做是No-Redo+No-Undo，上面提到的故障恢复机制的刷盘需要如下图所示：

TODO 图

#### Loggical or Physical



## ARIES，一统江湖

1992年，IBM的研究员们发表了《[ARIES: a transaction recovery method supporting fine-granularity locking and partial rollbacks using write-ahead logging](https://cs.stanford.edu/people/chrismre/cs345/rl/aries.pdf)》	[2]，其中提出的ARIES逐步成为磁盘数据库实现故障恢复的标配，ARIES本质是一种Redo-Undo的WAL实现。

**Normal过程：**修改数据之前先追加Log记录，Log内容同时包括Redo和Undo信息，并通过PrevLSN指针指向属于当前事务的上一条Log记录位置，每个日志记录产生对应一个标记其在日志中位置的递增的LSN（Log Sequence Number）；数据Page中记录最后修改的日志项LSN，以此来判断Page中的内容的新旧程度。故障恢复阶段需要通过Log中的内容恢复数据库状态，为了减少恢复时需要处理的日志量，ARIES会在正常运行期间周期性的生成Checkpoint，Checkpoint中除了当前的日志LSN之外，还需要记录当前活跃事务的最新LSN，以及所有脏页，供恢复时决定重放Redo的开始位置。需要注意的是，由于生成Checkpoint时数据库还在正常提供服务（Fuzzy Checkpoint），其中记录的活跃事务及Dirty Page信息并不一定准确，因此需要Recovery阶段通过Log内容进行修正。

**Recover过程：**故障恢复包含三个阶段：Analysis，Redo和Undo。Analysis阶段的任务主要是利用Checkpoint及Log中的信息确认后续Redo和Undo阶段的操作范围，通过Log修正Checkpoint中记录的Dirty Page集合信息，并用其中涉及最小的LSN位置作为下一步Redo的开始位置RedoLSN。同时修正Checkpoint中记录的活跃事务集合（未提交事务），作为Undo过程的回滚对象；Redo阶段从Analysis获得的RedoLSN出发，重放所有的Log中的Redo内容，注意这里也包含了未Commit事务；最后Undo阶段对所有未提交事务利用Undo信息进行回滚，通过Log的PrevLSN可以顺序找到事务所有需要回滚的修改。

除此之外，ARIES还包含了许多优化设计，例如通过特殊的日志记录类型CLRs避免嵌套Recovery带来的日志膨胀，支持细粒度锁，并发Recovery等。[3]认为，ARIES有两个主要的设计目标：

1. **Feature：提供丰富灵活的实现事务的接口：**包括提供灵活的存储方式、通过提供细粒度的锁来获得高并发、支持基于Savepoint的事务部分回滚、通过Logical-Undo以获得更高的并发、通过Page-Oriented Redo实现简单的可并发的Recovery过程。
2. **Performance：充分利用内存和磁盘介质特性，获得极致的性能：**采用No-Force避免大量同步的磁盘随机写、采用Steal及时重用宝贵的内存资源、基于Page来简化恢复和缓存管理。







## NVM带来的机遇与挑战

从Shadow Paging到WAL，再到ARIES，一直围绕着两个主题：减少同步写以及尽量用顺序写代替随机写。而这些正是由于磁盘性能远小于内存，且磁盘顺序访问远好于随机访问。然而随着NVM磁盘的出现以及对其成为主流的预期，使得我们必须要重新审视我们所做的一切。

相对于传统的HDD及SSD，NVM最大的优势在于：

- 接近内存的高性能，顺序访问和随机访问差距不大
- 基于字节而不是Block的接口

因此，为了利用磁盘顺序写性能和减少同步写的缓存管理机制已经变得多余，而为了迁就磁盘Block而维护Page所带来的复杂度也有机会去掉。近年来，众多的研究尝试为NVM量身定制更合理的故障恢复机制，我们这几介绍其中两种比较有代表性的研究成果，MARS希望充分利用NVM并发及内部带宽的优势，将更多的任务交给硬件实现；而WBL则尝试重构当前的Log方式。



## MARS

["From ARIES to MARS: Transaction support for next-generation, solid-state drives." ](https://cseweb.ucsd.edu/~swanson/papers/SOSP2013-MARS.pdf)



## WBL

[ "Write-behind logging." ](http://www.vldb.org/pvldb/vol10/p337-arulraj.pdf)


## 总结



## 参考

- [[1] Gray, Jim, et al. "The recovery manager of the System R database manager." ACM Computing Surveys (CSUR) 13.2 (1981): 223-242.](http://courses.cs.washington.edu/courses/cse550/09au/papers/CSE550.GrayTM.pdf)
- [[2] Mohan, C., et al. "ARIES: a transaction recovery method supporting fine-granularity locking and partial rollbacks using write-ahead logging." ACM Transactions on Database Systems (TODS) 17.1 (1992): 94-162.](https://cs.stanford.edu/people/chrismre/cs345/rl/aries.pdf)
- [[3] Coburn, Joel, et al. "From ARIES to MARS: Transaction support for next-generation, solid-state drives." Proceedings of the twenty-fourth ACM symposium on operating systems principles. ACM, 2013.](https://cseweb.ucsd.edu/~swanson/papers/SOSP2013-MARS.pdf)
- [[4] Arulraj, Joy, Matthew Perron, and Andrew Pavlo. "Write-behind logging." Proceedings of the VLDB Endowment 10.4 (2016): 337-348.](http://www.vldb.org/pvldb/vol10/p337-arulraj.pdf)
- [5] Garcia-Molina, Hector. Database systems: the complete book. Pearson Education India, 2008.
- [[6] Zheng, Wenting, et al. "Fast Databases with Fast Durability and Recovery Through Multicore Parallelism." OSDI. Vol. 14. 2014.](https://15721.courses.cs.cmu.edu/spring2018/papers/12-logging/zheng-osdi14.pdf)
- [[7] Hellerstein, Joseph M., and Michael Stonebraker, eds. *Readings in database systems*. MIT Press, 2005.](https://books.google.com/books?hl=en&lr=&id=7a48qSMuVcUC&oi=fnd&pg=PR9&dq=readings+in+database+systems&ots=tblf0ASm5j&sig=YLabEvheOluYbDVX7EKQL8AVHHc#v=onepage&q=readings%20in%20database%20systems&f=false)
- [8] http://catkang.github.io/2018/08/31/isolation-level.html
- [9] http://catkang.github.io/2018/09/19/concurrency-control.html
- [10] [https://www.classle.net/#!/classle/book/shadow-paging-recovery-technique](https://www.classle.net/#!/classle/book/shadow-paging-recovery-technique/)









