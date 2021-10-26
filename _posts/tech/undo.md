# 庖丁解InnoDB之Undo Log



Undo Log是InnoDB十分重要的组成部分，它的作用横贯InnoDB中两个最主要的部分，并发控制（Concurrency  Control）和故障恢复（Crash Recovery），InnoDB中Undo Log的实现上亦日志亦数据。本文将从其作用、设计思路、记录内容、组织结构，以及各种功能实现等方面，整体介绍InnoDB中的Undo Log，文章会深入一定的代码实现，但在细节上还是希望用抽象的实现思路代替具体的代码。本文基于MySQL 8.0，但在大多数的设计思路上MySQL的各个版本都是一致的。



# Undo Log的作用

[数据库故障恢复机制的前世今生](http://catkang.github.io/2019/01/16/crash-recovery.html)中提到过，Undo Log用来记录每次修改之前的历史值，配合Redo Log用于故障恢复。这也就是InnoDB中Undo Log的第一个作用：

### 1. 事务回滚

在设计DB时，我们假设数据库可能在任何时刻，由于如硬件故障，软件Bug，运维操作等原因突然崩溃。这个时候尚未完成提交的事务可能已经有部分数据写入了磁盘，如果不加处理，会违反数据库对Atomic的保证，也就是任何事务的修改要么全部提交，要么全部取消。针对这个问题，直观的想法是等到事务真正提交时，才能允许这个事务的任何修改落盘，也就是No-Steal策略。显而易见，这种做法一方面造成很大的内存空间压力，另一方面提交时的大量随机IO会极大的影响性能。因此，数据库实现中通常会在正常事务进行中，就不断的连续写入Undo Log，来记录本次修改之前的历史值。当Crash真正发生时，可以在Recovery过程中通过回放Undo Log将未提交事务的修改抹掉。InnoDB采用的就是这种方式。

既然已经有了在Crash Recovery时支持事务回滚的Undo Log，自然地，在正常运行过程中，死锁处理或用户请求的事务回滚也可以利用这部分数据来完成。



### 2. MVCC（Multi-Versioin Concurrency Control）

[浅析数据库并发控制机制](http://catkang.github.io/2018/09/19/concurrency-control.html)中提到过，为了避免只读事务与写事务之间的冲突，避免写操作等待读操作，几乎所有的主流数据库都采用了多版本并发控制（MVCC）的方式，也就是为每条记录保存多份历史数据供读事务访问，新的写入只需要添加新的版本即可，无需等待。InnoDB在这里复用了Undo Log中已经记录的历史版本数据来满足MVCC的需求。



# 什么样的Undo Log

InnoDB中为了用Undo Log来实现MVCC，DB运行过程中是允许有历史版本的数据存在的。因此，Crash Recovery时利用Undo Log的事务回滚完全可以在后台，像正常运行的事务一样异步回滚，从而让数据库先恢复服务。因此，Undo Log的设计思路，不同于[庖丁解InnoDB之REDO LOG](http://catkang.github.io/2020/02/27/mysql-redo.html)中讲过的基于Page的Redo Log，Undo Log需要的是事务之间的并发，以及方便的多版本数据维护，其重放逻辑不希望因DB的物理存储变化而变化，如索引Page的Split或Merge。因此，InnoDB中的Undo Log采用了**Logical Logging**的方式。

同时，更多的责任意味着更复杂的管理逻辑，InnoDB中其实是把Undo当做一种数据来维护和使用的，也就是说，Undo Log日志本身也像其他的数据库数据一样，会写自己对应的Redo Log，通过Redo Log来保证自己的原子性。因此，更合适的称呼应该是**Undo Data**。

除此之外，每个写事务都需要维护自己的Undo Log，为了更好的事务间并发， Undo Log应该是单个事务独享的的，相对于Page-Oriented Redo我们可以称之为**Transaction-Oriented Undo**。





# Undo Record中的内容

每当InnoDB中需要修改某个Record时，都会将其历史版本写入一个Undo Log中，这种Undo Record是Update类型。当插入新的Record时，还没有一个历史版本，但为了方便事务回滚时做逆向（Delete）操作，这里还是会写入一个Insert类型的Undo Record。

### Insert类型的Undo Record

这种Undo Record在代码中对应的是TRX_UNDO_INSERT_REC类型。不同于Update类型的Undo Record，Insert Undo Record仅仅是为可能的事务回滚准备的，并不在MVCC功能中承担作用。因此只需要记录对应Record的Key，供回滚时查找Record位置即可。

![insert_undo_record](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/insert_undo_record-5261142.png)

其中Undo Number是Undo的一个递增编号，Table ID用来表示是哪张表的修改。下面一组Key Fields的长度不定，因为对应表的主键可能由多个field组成，这里需要记录Record完整的主键信息，回滚的时候可以通过这个信息在索引中定位到对应的Record。除此之外，在Undo Record的头尾还各留了两个字节用户记录其前序和后继Undo Record的位置。



### Update类型的Undo Record

由于MVCC需要保留Record的多个历史版本，当某个Record的历史版本还在被使用时，这个Record是不能被真正的删除的。因此，当需要删除时，其实只是修改对应Record的Delete Mark标记。对应的，如果这时这个Record又重新插入，其实也只是修改一下Delete Mark标记，也就是将这两种情况的delete和insert转变成了update操作。再加上常规的Record修改，因此这里的Update Undo Record会对应三种Type：TRX_UNDO_UPD_EXIST_REC、TRX_UNDO_DEL_MARK_REC和TRX_UNDO_UPD_DEL_REC。他们的存储内容也类似：

TODO 图

![image-20211020004615521](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/image-20211020004615521.png)

Undo Number、Table ID以及Key Fields跟上面的Insert类型Undo Record类似， 不同的是Update类型的Undo Record下面还有一组Updated Fields，这个记录的是当前这个历史版本相对于最新版本的不同之处，也就是本次修改所有变化的Field都需要在这里记录其变化信息。



其中所有的Undo Record都会包含两项：**trx_id**用来标明创建当前Undo Record的事务id；**Rollptr**指向当前Record再往前的一个版本，通过Rollptr可以顺藤摸瓜找到某个Record的所有历史版本。

![image-20211021105008711](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/image-20211021105008711.png)

TODO：

- 三种type存储内容上确定有没有区别
- Updated Field是相对于更老的一个版本的还是更新的一个版本的







# Undo Record的组织方式

### 逻辑组织方式 - Undo Log



![image-20211020162935560](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/image-20211020162935560.png)

![image-20211020163925748](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/image-20211020163925748.png)

上面介绍了一个**Undo Record**中的存放的内容，而每个事务其实会修改一组的Record，对应的也就会产生一组Undo Record，这些Undo Record收尾相连就组成了这个事务的**Undo Log**。由于之后会讲到Purge和事务回滚会从两个不同的方向遍历Undo Record，为了能快速的定位到下一条Undo Record，InnoDB在每条Undo Record的前后各加了两个自己分别指向Next Undo Record和Previous Undo Record。

除此之外，还需要为每个Undo Log添加一些元信息，如下图所示，



![image-20211020102503922](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/image-20211020102503922.png)

如上图所示是一条完整的事务的Undo Log，除了连续的Undo Records外，还在头部记录了一组元信息，包括该事务的ID，事务提交编号Trx No，Undo Log中是否包含Delete Mark的Undo Record，Undo Log的开始位置，以及一些Flag等信息。Next Undo Log和Prev Undo Log记录同一个Undo Segment中前序和后继Undo Log的位置。事务提交后会将自己的History List Node挂到Rollback Segment的History List，等到后台的Purge。



### 物理组织格式 - Undo Segment

上面描述了一个Undo Log的结构，一个事务会产生多大的Undo Log本身是不可控的，而最终写入磁盘却是按照固定的块大小为单位的，InnoDB中默认是16KB，那么如何用固定的块大小承载不定长的Undo Log，以实现高效的空间分配、复用，避免空间浪费。下面我们就看看这部分的物理存储方式：

![image-20211020144533097](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/image-20211020144533097.png)

如上所示，是一个**Undo Segment**的示意图，每个写事务开始写操作之前都需要持有一个Undo Segment，一个Undo Segment中的所有磁盘空间的分配和释放，也就是16KB Page的申请和释放，都是由一个FSP的Segment管理的，这个跟索引中的Leaf Node Segment和Non-Leaf Node Segment的管理方式是一致的，这部分之后会有单独的博客来进行介绍。

Undo Segment会持有至少一个**Undo Page**，每个Undo Page会在开头38字节到56字节记录**Undo Log Header**，其中记录Undo Page的类型、最后一条Undo Record的位置，当前Page还空闲部分的开头。Undo Segment中的第一个Undo Page还会在56字节到86字节记录**Undo Segment Header**，这个就是这个Undo Segment中磁盘空间管理的Handle，其中齐鲁的是这个Undo Segment的状态，最后一条Undo Record的位置，这个FSP Segment的Header，以及当前分配出来的所有Undo Page的链表。

Undo Page剩余的空间都是用来存放Undo Log的，对于像上图Undo Log 1，Undo Log 2这种较短的Undo Log，为了避免Page内的空间浪费，InnoDB会复用Undo Page来存放多个Undo Log，而对于像Undo Log 3这种比较长的Undo Log可能会分配多个Undo Page来存放。需要注意的是Undo Page的复用只会发生在第一个Page。







### 文件组织方式 - Undo Tablespace

每一时刻一个Undo Segment都是被一个事务独占的。当有大量事务并发运行时，就需要存在多个Undo Segment。InnoDB中，会将这些Undo Segment按照1024一组划分为**Rollback Segment**。每个Undo Tablespace会包含128个Rollback Segment，每个Rollback Segment本身会占用一个Page，其中记录**Rollback Segment Header**，其中包含1024个Slot，每个Slot占四个字节，指向一个Undo Segment的First Page，以及该Rollback Segment中已提交事务的History List，后续的Purge过程会顺序从这里开始回收工作。

可以看出Rollback Segment的个数会直接影响InnoDB支持的最大事务并发数。MySQL 8.0由于支持了最多128个独立的Undo Tablespace，一方面避免了ibdata1的膨胀，方便undo空间回收，另一方面也大大增加了最大的Rollback Segment的个数。如下图所示：

![image-20211020160100612](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/image-20211020160100612.png)



TODO

- 每个事务持有几个Undo Segment
- 80最多有多少个undo tablespace



### 内存组织结构

trx_rseg_t对应Rollback Segment，其中除了对应的一些元信息，供Purge使用的下一条Purge位置和四个trx_undo_t的链表，分别对应

trx_undo_t对应Undo Segment

![image-20211020164029152](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/image-20211020164029152.png)





# Undo的写入

当写事务开始时，会先通过**trx_assign_rseg_durable**分配一个Rollback Segment，这里的分配策略也很简单，就是依次尝试下一个Active的Rollback Segment。之后当第一次真正产生修改需要写Undo Record的时，会调用**trx_undo_assign_undo**来获得一个Undo Segment。这里会优先使用cached trx_undo_t来进行复用，也就是已经分配出来但没有正在使用的Undo Segment，如果没有才调用**trx_undo_create**来选择当期Rollback Segment中可用的Slot，Slot中如果是FIL_NUL，则代表该slot还没有被占用，轮询获得一个这样的slot，并创建新的Undo Segment和Undo Page，初始化Header等元信息。

获得了可用的Undo Segment之后，该事务会在合适的位置初始化自己的Undo Log Header，之后，其所有修改产生的Undo Record都会顺序的通过**trx_undo_report_row_operation**顺序的写入当前的Undo Log，其中会根据是insert还是update类型，分别调用**trx_undo_page_report_insert**或者**trx_undo_page_report_modify**。本文开始已经介绍过了具体的Undo Record内容。简单的讲，insert类型会记录插入Record的主键，update类型除了记录主键以外还会有一个update fileds记录这个历史值跟索引值的diff。之后指向当前Undo Record位置的Rollptr会返回写入索引的Record上。

当一个Page写满后，会调用**trx_undo_add_page**来在当前的Undo Segment上添加新的Page，新Page写入Undo Page Header之后继续供事务写入Undo Record，为了方便维护，这里有一个限制就是单条Undo Record不跨page，如果当前Page放不下，会将整个Undo Record写入下一个Page。

当事务结束（commit或者rollback）之后，如果只占用了一个Undo Page，且当前Undo Page使用空间小于page的3/4，这个Undo Segment会保留并加入到对应的insert/update cached list中。否则，insert类型的Undo Segment会直接回收，而update类型的Undo Segment会等待后台的Purge做完后回收。根据不同的情况，Undo Segment Header中的State会被从TRX_UNDO_ACTIVE改成TRX_UNDO_TO_FREE，TRX_UNDO_TO_PURGE或TRX_UNDO_CACHED，这个修改其实就是**InnoDB的事务结束的标志**，无论是Rollback还是Commit。



# Undo for Rollback

InnoDB中的事务可能会由用户主动触发Rollback，也可能因为遇到死锁等异常Rollback，或者发生Crash，重启后对未提交的事务回滚。在Undo层面来看，这些回滚的操作是一致的，基本的过程就是从该事务的Undo Log中，从后向前依次读取Undo Record，并根据其中内容做逆向操作，恢复索引记录。

回滚的入口是函数**row_undo**，其中会先调用**trx_roll_pop_top_rec_of_trx**获取并删除该事务的最后一条Undo Record，回忆上面介绍的Undo Segment的结构，从Undo Segment Header中记录的Page List可以找到当前事务的最后一个Undo Page的Header，并根据Header上记录的Lastest Log Record Offset便可以方便的定位最后一条Undo Record。之后根据Undo Record上面的前序指针找到前一个Undo Record，依次进行处理。如下图：

TODO 图

拿到Undo Record之后，自然地，就是对其中内容的解析，这里会调用**row_undo_ins_parse_undo_rec**，从Undo Record中获取修改行的table，解析出其中记录的主键信息，如果是update类型，还会拿到一个update vector记录其相对于更新的一个版本的变化。

**TRX_UNDO_INSERT_REC**类型的Undo回滚在**row_undo_ins**中进行，insert的逆向操作当然就是delete，根据从Undo Record中解析出来的主键，用**row_undo_search_clust_to_pcur**定位到对应的ROW， 分别调用**row_undo_ins_remove_sec_rec**和**row_undo_ins_remove_clust_rec**在二级索引和主索引上将当前行删除。

update类型的undo包括TRX_UNDO_UPD_EXIST_REC，TRX_UNDO_DEL_MARK_REC和TRX_UNDO_UPD_DEL_REC三种情况，他们的Undo回滚都是在**row_undo_mod**中进行，首先会调用**row_undo_mod_del_unmark_sec_and_undo_update**，其中根据从Undo Record中解析出的update vector来回退这次操作在所有二级索引上的影响，可能包括重新插入被删除的二级索引记录、去除其中的Delete Mark标记，或者用update vector中的diff信息将二级索引记录修改之前的值。之后调用**row_undo_mod_clust**同样利用update vector中记录的diff信息将主索引记录修改回之前的值。

完成回滚的Undo Log部分，会调用**trx_roll_try_truncate**进行回收，对不再使用的page调用**trx_undo_free_last_page**将磁盘空间交还给Undo Segment，这个写入过程中**trx_undo_add_page**的逆操作。



# Undo for MVCC

多版本的目的是为了避免写事务和读事务的互相等待，那么每个读事务都需要在不对Record加Lock的情况下， 找到对应的应该看到的历史版本。所谓历史版本就是假设在该只读事务开始的时候对整个DB打一个快照，之后该事务的所有读请求都从这个快照上获取。当然实现上不能真正去为每个事务打一个快照，这个时间空间都太高了。InnoDB的做法，是在读事务第一次读取的时候获取一份ReadView，并一直持有，其中记录所有当前活跃的写事务ID，由于写事务的ID是自增分配的，通过这个ReadView我们可以知道在这一瞬间，哪些事务已经提交哪些还在运行，根据Read Committed的要求，未提交的事务的修改就是不应该被看见的，对应地，已经提交的事务的修改应该被看到。

作为存储历史版本的Undo Record，其中记录的trx_id就是做这个可见性判断的，对应的主索引的Record上也有这个值。当一个读事务拿着自己的ReadView访问某个表索引上的记录时，会通过比较Record上的trx_id确定是否是可见的版本，如果不可见就沿着Record或Undo Record中记录的rollptr一路找更老的历史版本。

TODO 图

前面提到过，作为Logical Log，Undo中记录的其实是前后两个版本的diff信息，而读操作最终是要获得完整的Record内容的，也就是说这个沿着rollptr指针一路查找的过程中需要用Undo Record中的diff内容依次构造出对应的历史版本，这个过程在函数**row_search_mvcc**中，其中**trx_undo_prev_version_build**会根据当前的rollptr找到对应的Undo Record位置，这里如果是rollptr指向的是insert类型，或者找到了已经Purge了的位置，说明到头了，会直接返回失败。否则，就会解析对应的Undo Record，恢复出trx_id、指向下一条Undo Record的rollptr、主键信息，diff信息update vector等信息。之后通过**row_upd_rec_in_place**，用update vector修改当前持有的Record拷贝中的信息，获得Record的这个历史版本。之后调用自己ReadView的**changes_visible**判断可见性，如果可见则返回用户。完成这个历史版本的读取。





# Undo for Crash Recovery

Crash Recovery时，需要利用Undo中的信息将未提交的事务的所有影响回滚，以保证数据库的Failure Atomic。前面提到过，InnoDB中的Undo其实是像数据一样处理的，也从上面的组织结构中可以看出来，Undo本身有着比Redo Log复杂得多、按事务分配而不是顺序写入的组织结构，其本身的Durability像InnoDB中其他的数据一样，需要靠Redo来保证，像[庖丁解InnoDB之REDO LOG](http://catkang.github.io/2020/02/27/mysql-redo.html)中介绍的那样。除了通用的一些MLOG_2BYTES、MLOG_4BYTES类型之外，Undo本身也有自己对应的Redo Log类型：**MLOG_UNDO_INIT**类型在Undo Page舒适化的时候记录初始化；在分配Undo Log的时候，需要重用Undo Log Header或需要创建新的Undo Log Header的时候，会分别记录**MLOG_UNDO_HDR_REUSE**和**MLOG_UNDO_HDR_CREATE**类型的Redo Record；**MLOG_UNDO_INSERT**是最常见的，在Undo Log里写入新的Undo Record都对应的写这个日志记录写入Undo中的所有内容；最后，**MLOG_UNDO_ERASE_END** 对应Undo Log跨Undo Page时抹除最后一个不完整的Undo Record的操作。

如[数据库故障恢复机制的前世今生](http://catkang.github.io/2019/01/16/crash-recovery.html)中讲过的ARIES过程，Crash Recovery的过程中会先重放所有的Redo Log，整个Undo的磁盘组织结构，也会作为一种数据类型也会通过上面讲到的这些Redo类型的重放恢复出来。之后在**trx_sys_init_at_db_start**中会扫描Undo的磁盘结构，遍历所有的Rollback Segment和其中所有的Undo Segment，通过读取Undo Segment Header中的State，可以知道在Crash前，最后持有这个Undo Segment的事务状态。如果是TRX_UNDO_ACTIVE，说明当时事务需要回滚，否则说明事务已经结束，可以继续清理Undo Segment的逻辑。之后，就可以恢复出Undo Log的内存组织模式，包括活跃事务的内存结构trx_t，Rollback Segment的内存结构trx_rseg_t，以及其中的trx_undo_t的四个链表。

Crash Recovery完成之前，会启动在**srv_dict_recover_on_restart**中启动异步回滚线程**trx_recovery_rollback_thread**，其中对Crash前还活跃的事务，通过**trx_rollback_active**进行回滚，这个过程更上面提到的Undo for Rollback是一致的。



# Undo的清理

我们已经知道，InnoDB在Undo Log中保存了多份历史版本来实现MVCC，当某个历史版本已经确认不会被任何现有的和未来的事务看到的时候，就应该被清理掉。因此就需要有办法判断哪些Undo Log不会再被看到。InnoDB中每个写事务结束时都会拿一个递增的编号**trx_no**作为事务的提交序号，而每个读事务会在自己的ReadView中记录自己开始的时候看到的最大的trx_no为**m_low_limit_no**。那么，如果一个事务的trx_no小于当前所有活跃的读事务Readview中的这个**m_low_limit_no**，说明这个事务在所有的读开始之前已经提交了，其修改的新版本是可见的， 因此不再需要通过undo构建之前的版本，这个事务的Undo Log也就可以被清理了。

TODO 图

Undo的清理工作是由专门的后台线程**srv_purge_coordinator_thread**进行扫描和分发， 并由多个**srv_worker_thread**真正清理的。coordinator会首先在函数**trx_purge_attach_undo_recs**中扫描innodb_purge_batch_size配置个Undo Records，作为一轮清理的任务分发给worker。

### 扫描一批要清理Undo Records

事务结束的时候，对于需要Purge的Update类型的Undo Log，会挂载到Rollback Segment Header的**History List**上。Undo Log的回收的基本思路，就是遍历所有Rollback Segment Header的History List，依次做清理操作。Undo Log的清理顺序应该是按照trx_no从小到大进行，那么就需要在多个History List上找一个全局有序的序列，如下图所示：

![image-20211026010007239](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/image-20211026010007239.png)

以四个History List为例，每次都需要从多个History List中找到下一个拥有最小trx_no的Undo Log，InnoDB这里引入了一个成为**purge_queue**的优先队列：

![image-20211026010144439](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/image-20211026010144439.png)

事务结束的时候，除了挂载History List之外，还需要将当前的Undo Log，以其trx_no push进purge_queue。后台的Purge 过程会依次从purge_queue中获取，拥有最小trx_no的Undo Log，调用**trx_purge_get_next_rec**从前往后，依次获得其中的每一条Undo Record，并作为Purge的任务分发给worker。当一条Undo Log处理完成后，调用**trx_purge_choose_next_log**从purge_queue中获取下一条trx_no最小的Undo Log，并且将当前Rollback Segment上的下一条Undo Log继续push进purge_queue，等待后续的顺序处理。



对每个要Purge的Undo Record，在真正删除它本身之前，可能还需要处理一些索引上的信息，这是由于正常运行过程中，当需要删除某个Record时，为了保证其之前的历史版本还可以通过Rollptr找到，Record是没有真正删除的，只是打了Delete Mark的标记，并作为一种特殊的Update操作记录了Undo Record。那么在对应的TRX_UNDO_DEL_MARK_REC类型的Undo Record被清理之前，需要先从索引上真正地删除对应的delete

mark的记录。因此Undo Record的清理工作会分为两个过程：

- TRX_UNDO_DEL_MARK_REC类型Undo Record对应的Record的真正删除，称为**Undo Purge**；
- 以及Undo Record本身从旧到新的删除，称为**Undo Truncate**。

除此之外，当配置的独立undo tablespace大于两个的时候，InnoDB支持通过truncate来缩小超过配置大小的undo tablespace：

- undo tablespace的重建缩小，成为**Undo Tablespace Truncate**





### Undo Purge

这一步主要针对的是TRX_UNDO_DEL_MARK_REC类型的Undo Record，用来真正的删除索引上被标记为Delete Mark的Record。worker线程会在**row_purge**函数中，循环处理coordinator分配来的每一个Undo Records，先通过**row_purge_parse_undo_rec**，依次从Undo Record中解析出type、table_id、rollptr、对应记录的主键信息以及update vector。之后，针对TRX_UNDO_DEL_MARK_REC类型，调用**row_purge_remove_sec_if_poss**将需要删除的记录从所有的二级索引上删除，调用**row_purge_remove_clust_if_poss**从主索引上删除。另外，TRX_UNDO_UPD_EXIST_REC类型的Undo虽然不涉及主索引的删除，但可能需要做二级索引的删除，也是在这里处理的。



### Undo Truncate

coordinator线程会等待所有的worker完成一批Undo Records的Purge工作，之后尝试清理不再需要的Undo Log，**trx_purge_truncate**函数中会遍历所有的Rollback Segment中的所有Undo Segment，如果其状态是TRX_UNDO_TO_PURGE，调用trx_purge_free_segment释放占用的磁盘空间并从History List中删除。否则，说明该Undo Segment正在被使用或者还在被cache（TRX_UNDO_CACHED类型），那么只通过**trx_purge_remove_log_hd**将其从History List中删除。

需要注意的是，Undo Truncate的动作并不是每次都会进行的，它的频次是由参数**innodb_rseg_truncate_frequency**控制的，也就是说要攒**innodb_rseg_truncate_frequency**个batch才进行一次，前面提到每一个batch中会处理**innodb_purge_batch_size**个Undo Records，这也就是为什么我们从show engine innodb status中看到的Undo History List的缩短是跳变的。







### Undo Tablespace Truncate

如果**innodb_trx_purge_truncate**配置打开，在函数**trx_purge_truncate**中还会去尝试重建Undo Tablespaces以缩小文件空间占用。Undo Truncate之后，会在函数**trx_purge_mark_undo_for_truncate**中扫描所有的Undo Tablespace，文件大小大于配置的**innodb_max_undo_log_size**的Tablespace会被标记为inactive，每一时刻最多有一个Tablespace处于inactive，inactive的Undo Tablespace上的所有Rollback Segment都不参与给新事物的分配，等该文件上所有的活跃事务退出，并且所有的Undo Log都完成Purge之后，这个Tablespace就会被通过**trx_purge_initiate_truncate**重建，包括重建Undo Tablespace中的文件结构和内存结构，之后被重新标记为active，参与分配给新的事务使用。





# 总结：





