# 庖丁解InnoDB之Lock

并发控制是数据库中非常核心的功能，是我们常说的数据库必须具备的属性ACID中的I，也就是隔离性（Isolation）。顾名思义，隔离性是要对并发运行在数据库上的事务做隔离，其本质是在数据库并发性能和事务正确性之间做权衡选择，为此数据库通常会提供不同程度的隔离级别供用户选择，更高的隔离级别对每个事务而言都更接近于其独占数据库运行，但通常也意味着更低的事务并发度。而并发控制就是对不同隔离级别需要的保证的内部实现机制，Lock是现代数据库，尤其是单机数据库中最常见的并发控制手段，MySQL中的InnoDB就是采用基于Lock的并发控制实现。本文我们从InnoDB所支持的隔离级别、并发控制机制、Lock加锁方式，以及Lock的实现来进行介绍。

## 数据库隔离级别及并发控制

数据库隔离性的保证其实是在提供给用户一种选择， 愿意牺牲多少单个事务的独立性来换取更高的数据库并发性能。那么，统一且清晰的隔离级别设置对于用户使用和预期数据库的行为就变得非常重要。1992年ANSI首先尝试指定统一的隔离级别标准，其定义了不同级别的异象(phenomenas)， 包括：

- 脏读（Dirty Read）: 读到了其他事务还未提交的数据；
- 不可重复读（Non-Repeatable/Fuzzy Read）：由于其他事务的修改或删除，对某数据的两次读取结果不同；
- 幻读（Phantom Read）：由于其他事务的修改，增加或删除，导致Range的结果失效（如where 条件查询）。

并通过能排除多少这些异象来定义了，不做限制的Read Uncommitted，排除了脏读的Read Committed。排除了脏读和不可重复读的Repeatable Read，以及排除了所有这三种异象的Serializable四种隔离级别，当然这个标准中存在一些问题和歧义，这里不展开讨论，更多的可以参考[数据库事务隔离发展历史](https://catkang.github.io/2018/08/31/isolation-level.html)。

数据库为了实现隔离级别的保证，就需要对事务的操作做冲突检测，对有冲突的事务延迟或丢弃，这就是数据库的**并发控制**机制。一方面，根据对冲突的乐观程度，可以分为，在操作甚至是事务开始之前就检测冲突的基于Lock的方式；在操作真正写数据的时候检测的基于Timestamp的方式；以及在事务Commit时才检测的基于Validation的方式三种。另一方面，根据是否采用多版本来避免读写之间的互相阻塞，分为单版本和多版本，也就是MVCC。关于这方面更多的讨论可以参考[浅析数据库并发控制机制](https://catkang.github.io/2018/09/19/concurrency-control.html)。

## InnoDB的隔离级别及并发控制

InnoDB采用的是**Lock + MVCC**的实现方式，具体来说：对与写事务，会在修改记录之前对这一行记录加锁并持有，以此来避免冲突的发生；而对于只读事务，会默认采用MVCC的的方式，而不是加锁的方式，也就是在事务第一次读操作（RR）或者当前语句开始（RC）时，持有一个当时实例全局的事务活跃状态作为自己的ReadView，相当于对当时的实例状态打了一个Snapshot，后续访问某一行的时候，会根据这一行上面记录的事务ID，通过自己持有的ReadView来判断是否可见，如果不可见，再沿着记录上的RollPtr去Undo中查找自己可见的历史版本。这种读的方式我们也称之为**快照读。**与之对应的，InnoDB还支持**加锁读**的方式，当Select语句中使用了如<u>Select....for Update/Share</u>时，这时查询不在通过MVCC的方式，而是像写操作一样，先对需要访问的记录加锁，之后再读取记录内容，这种方式会跟写请求相互阻塞， 从而读到的也一定是该记录当前最新的值，因此这种读的方式我们也称为当前读。

TODO图

上图展示的是写操作、加锁读以及快照读对数据不同的访问模式，可以看出，写操作和加锁读访问的是记录的当前最新版本，而快照读访问的是一个历史时刻的数据版本，因此在同一个事务中混用两种模式，可能会遇到有些反直觉的现象，比如官方文档中给出的一个[例子](https://dev.mysql.com/doc/refman/8.0/en/innodb-consistent-read.html)：

```
SELECT COUNT(c1) FROM t1 WHERE c1 = 'xyz';
-- Returns 0: no rows match.
DELETE FROM t1 WHERE c1 = 'xyz';
-- Deletes several rows recently committed by other transaction.
```

这个例子展示的是一个事务，先通过正常的Select语句去查找满足条件c1='xyz'的记录，发现没有后，用相同的条件做删除操作。结果造成另一个事务刚刚Commit的满足c1='xyz'的记录被删除。这个有些反直觉的现象就是因为前面的Selete语句默认走的是MVCC的方式，并没有对访问的记录加锁。官方文档也是不建议这样混用的，要实现前后Selete和Delete看到数据的一致，需要用上面的提到的**加锁读**的方式，也就是：

```
SELECT COUNT(c1) FROM t1 WHERE c1 = 'xyz' for Update/Share;
```

因此，我们这里对InnoDB隔离级别的讨论，需要区分是快照访问及加锁访问。MySQL提供了ANSI中定义的所有四种隔离级别，但对异象的排除其实是跟标准有些差异的，这也引起了很多的误解， 我们这里来整理一下，表格中展示的是ANSI，MySQL InnoDB中采用快照方式或者加锁方式的时候，在配置不同的隔离级别时，可能出现的P1（Dirty Read）、P2（Non-Repeatable）、P3（Phantom）三种异象的可能：

|                  | ANSI       | MySQL InnoDB加锁访问 | MySQL InnoDB快照访问 |
| ---------------- | ---------- | -------------------- | -------------------- |
| Read Uncommitted | P1, P2, P3 | P3                   | P1, P2, P3           |
| Read Committed   | P2, P3     | P3                   | P2，P3               |
| Read Repeatable  | P3         |                      |                      |
| Serializable     |            |                      |                      |

不同于ANSI每一个级别多排除一个异象，可以看到：

- 当使用加锁访问，如写操作或者加锁读（Select...for Update/Share）时：在Read Uncommitted及Read Committed都会对Key加锁，并且这个锁是持续整个事务生命周期的，因此都不会有Dirty Read 和Non-Repeatable的问题；而在Read Repeatable及Serializable下，除了对Key加锁外，还需要对访问的Range加锁，同样也是持续整个事务生命周期，因此是没有Phantom问题的。
- 当使用快照读，如正常的Select语句时：在Read Uncommitted下其实是不会持有ReadView判断可见性的，也就是存在Dirty Read，Non-Repeatable及Phantom的，在Read Committed下，每条查询都会重新获取一次Read View，并以之判断可见性，因此是可以排除Diry Read的；而在Read Repeatable隔离级别下，整个事务会在第一次读的时候获取一次ReadView，相当于之后的所有查询看到的都是这个时刻的快照，因此无论是针对单个Key的Non-Repeatable还是针对where条件的Phantom都是可以避免的，这一点跟标准不同，也是经常造成误解的地方；最后在Serializable下，其实是摒弃了MVCC的，正常的Select也隐式转换成加锁读，也可以摒弃三种异象。

在实践中，由于Read Uncommitted太过宽松，而Seriablizable又没有MVCC，因此通常会在Read Committed及Read Repeatable两种隔离级别种选择。关于快照读的具体实现方式会在后面的文章中详细讨论，本文主要关注InnoDB的加锁访问的实现方式。

## B+Tree数据库加锁范式

相对于选择在事务提交时再判断冲突并回滚的OCC来说，Lock的实现方式基于对冲突更悲观的预测，会在一开始就对要访问的数据进行加锁互斥。这种方式降低了冲突发后的回滚的代价，并且更符合数据库使用者的直觉，因此成为大多数数据库，尤其是单机数据库的选择。基于Lock的数据库并发控制，通常会维护一个Lock Table，其中维护一系列的加锁对象，以及这些加锁对象上，不同事务持有或等待的Lock信息，并发访问的事务会通过对Lock Table查找，锁冲突的判断以及加入自己的锁等待，来实现对这些对象的正确访问。对这个加锁的数据库对象的选择，会成为影响并发性能的关键因素。不同的数据结构下这个数据库对象的选择，也会不同。B+Tree数据库在过去几十年，也经历了一些列的探索进步，从对整颗树加锁，到对多个或一个Page加锁，再到ARIES/KVL将逻辑内容和物理内容分离，实现对Record维度的加锁。InnoDB采用的就是这种对B+Tree上的Record加Lock的实现方式（更多参考[B+树数据库加锁历史](https://catkang.github.io/2022/01/27/btree-lock.html)）。

InnoDB遵循**2PL(Two-Phase Locking)**，也就是将事务加锁分为两个阶段，加锁阶段可以不断地对数据库对象加锁，但不能放锁，直到进入到放锁阶段，这时就只能放锁了。InnoDB中的这个阶段的划分就是事务Commit阶段。简单的说，就是InnoDB的事务，一旦对某个对象加锁后，会在整个事务的生命周期全程持有这把锁。因此，可以很自然的实现对Dirtry Read以及Non-Repeatable Read的摒弃，但对于Repeatable Read隔离级别下对Phantom Read的阻止就比较麻烦，因为需要对查询的整个Range加锁，也就是需要对可能还不存在的记录进行加锁。针对这个问题，传统的实现方式是**谓词锁(Predicate Lock)**，也就是直接对查询条件加锁，这个是比较麻烦的，因为查询条件千变万化，还需要判定他们之间的互斥关系。幸运的是在B+Tree上，其记录之间已经天然维护了顺序关系，ARIES/KVL提出了**Key Range Locking**，也就是对Key加锁，来保护其旁边的区间Range。KRL认为同时对Key和Key之间的Range加锁的方式一定程度上限制了对Key和对Gap的访问并发，提出将二者进行拆分，分别加锁。InnoDB采用的就是这种方式，在InnoDB中这种保护区间的锁叫做**Next Key Lock**和**Gap Lock**，二者的区别在于是否要同时保护这个边界的存在的Record。

不可避免的，为了避免幻读的Key Range Locking会带来更多的锁冲突，从而影响整个数据库的性能，学术上其实提供过很多的优化手段，比如对Insert短暂加锁后就释放的Instant Locking；针对删除操作的Ghost Locking优化；避免跨节点判断锁的Fence Key；用更精确的锁mode区分操作类型，从而更大程度的挖掘他们之间的并发可能的KRL，以及分层级加锁的Hierarchical Locking。很多这些思想其实在InnoDB中都是有类似实现的，这些会在本文后面的章节中详细讨论。

InnoDB中的记录锁有读锁（LOCK_S）和写锁（LOCK_X）两种模式，读锁之间不互斥，而写锁和读写锁都互斥，修改操作通常会持有写锁，而只读操作会持有读锁。而根据加锁对象的不同又可以分成三种：只对记录加锁的**Record Lock**（LOCK_REC_NOT_GAP），对当前记录之前的到前一个记录的区间加锁的**Gap Lock**（LOCK_GAP），以及同时对记录和其之前的区间加锁的**Next Key Lock**（LOCK_ORDINARY），他们的加锁范围如下图所示：

TODO 图



## InnoDB加锁过程

MySQL在设计初期采用了可插拔引擎的设计思路，将DB划分成了负责SQL解析、优化及执行的MySQL层，以及负责数据存储的引擎层，MySQL层通过不同引擎层实现的统一的Handler接口来访问下面的引擎数据。虽然经过几十年的发展，支持ACID的InnoDB引擎已经事实上成为了MySQL的官方指定引擎。但这层通过Handler的访问方式还是存在的。对数据库的增删改查SQL语句，从对数据的访问模式上来看其实可以大体分为两类：一种根据某种查询条件，找到所有的符合条件的Record，之后对这些Record进行读写操作，这种模式对应的是Select、Update以及Delete语句；另一种是插入语句，其访问模式是找到当前记录应该的插入点，然后完成插入，当然这里针对主键和唯一二级索引，还需要保证插入后的的唯一性。本节将对这两种访问模式分别讨论其加锁过程：

#### 1. Select、Update、Delete 加锁过程

InnoDB采用了前面所说的**Ghost Locking的Delete实现**，也就是对记录Delete的时候，并不会做真正的删除，而是仅仅在这条Record上设置Delete Mark标记，也就是将Delete操作转换成一次Update操作，依赖后台的Undo Purge过程，在这个记录不再被访问的时候做真正的删除。这样的好处是极大的降低了Delete操作的加锁开销，试想假如直接做真正的记录删除，即使是在Read Committed隔离级别下，这个事务也需要对被删除记录的下一条记录加Next Key Lock或者Gap Lock，来保证在这个事务的生命周期中不会有其他事务插入等值的新记录导致Non-Repeatable。而采用了Ghost Locking的方式后，在RC下该事务仅需要对这个Delete Mark标记的记录加Record Lock即可。因此，这里Delete操作可以看做是一种特殊的只修改记录Delete Mark标记的Update操作，他们的加锁过程也是一致的。

Selete、Update以及Delete语句，经过MySQL前面的SQL解析、优化、生成执行计划后，确定要使用的索引或者直接进行主键索引的全表扫描，之后就是通过一种迭代器的访问方式来遍历这个索引上的记录：首先，通过**ha_innobase::index_read**定位到满足where条件的第一条记录，缓存结果、修改或者删除；然后，通过**ha_innobase::general_fetch**依次去遍历下一条满足条件的记录，同样做修改或者删除，直到遇到不满足条件的记录或结尾。这种SQL层和InnoDB层的交互模式如下如所示：

TODO 交互图

index_read和general_fetch这两个函数的核心逻辑都实现在**row_search_mvcc**中，row_search_mvcc中会根据上层指定的查找条件，在选定的索引上搜索满足条件的记录，这个函数是InnoDB非常核心但也非常冗长的函数。之所以复杂，是因为其中融合了太多的逻辑和优化，本文这里会先忽略掉为了优化而存在的Record Buffer以及Adaptive Hash Index的相关逻辑，对于快照读实现的MVCC也将在后面的文章再详细介绍，这里仅关注这个函数中为Lock Read或者Update、Delete服务的加锁逻辑。对于第一条的查询，也就是通过index_read的访问，需要通过**btr_pcur_open_with_no_init**先去对应索引B+Tree上去搜索，获得指向满足条件记录的cursor，而对于后续general_fetch进来的查询，会利用前一次查询缓存的cursor，通过cursor所指向记录的next指针或者叶子节点之间的链表指针，可以实现对当前索引B+Tree上之后记录的一次遍历，检查是否满足条件，并通过**sel_set_rec_lock**加合适的锁，对于修改操作或者非覆盖索引的查询，还需要回表聚簇索引，通过**lock_clust_rec_read_check_and_lock**对聚簇索引上的对应记录加**Record Lock**（LOCK_REC_NOT_GAP）。row_search_mvcc的加锁规则，可以总结为一句话：

**对所有扫描到的记录(2)加合适的锁(1)，并尽量缩小加锁范围(3)**

这里我们分别解释这句话中的三个关键的点：

**（1）合适的锁：**

所谓合适的锁，首先是Lock Mode的选择，这个比较简单，对于写操作加写锁（X_LOCK），对于只读操作加读锁（S_LOCK）。其次是Lock Type的选择，在Read Committed及以下的隔离级别时，只对记录加**Record Lock**（LOCK_REC_NOT_GAP）。在Read Repeatable隔离级别下，对当前记录及其之前的区间加**Next Key Lock**（LOCK_ORDINARY）。

**（2）所有扫描到的记录**

一次SQL访问，扫描到的记录跟这张表上的索引以及执行计划中的索引选择有关，比如命中索引的查询，会从二级索引的B+Tree入手，依次对扫描到的记录加锁；再比如，没有合适的二级索引，或者执行计划没有选择到最优的索引的情况下，可能需要通过聚簇索引走全表扫描，这个时候就会对全表的记录都进行加锁，在Read Committed隔离级别下对不满足条件的记录会立即放锁，影响相对小一些。但在Read Repeatable隔离级别下，会导致对全表数据加Next Key Lock并持有，影响就比较大了。

需要注意的是，这里需要加锁的记录不止包括用户可见的记录，还包括Delete Mark的记录，这种记录并不会被用户看到，但是确实存在在B+Tree上，并且可以作为加锁的对象。产生Delete Mark记录的原因主要有两个，一个是上面提到的对Delete操作的Ghost Record的设计，被删除的记录在事务提交并被后台Purge操作清除之前，就会一直以Delete Mark的状态存在；第二个原因是，InnoDB的二级索引实现，所有对二级索引的修改除了修改Delete Mark标记本身，都会转换成一次删除和一次新纪录的插入，这次删除同样会遗留一个Delete Mark的记录。当然对于Delete Mark记录的加锁是可以优化的，这点在下面第3点中介绍。

**（3）尽量缩小加锁范围**

按照上述的方式加锁并在事务生命周期持有这把锁，是足够保证对应隔离级别下对Non-Repeatable或者Phantom异象的排除的。在一些确定性的场景下，存在一些缩小加锁范围来降低所冲突，提升并发的空间，InnoDB的这种优化包括两种，一种是减少加锁对象，比如将**Next Key Lock**（LOCK_ORDINARY）变成**Record Lock**（LOCK_REC_NOT_GAP）或者**Gap Lock**(LOCK_GAP)，另一种是缩短持有锁的时间，比如一些可以提前放锁的场景。具体的优化如下：
1. Read Committed及以下隔离级别时，对不满足条件的记录会在加到锁后提前放锁，包括上面提到的Delete Mark的记录，以及InnoDB返回MySQL后，MySQL判断不符合Where条件的记录。这是由于Read Committed隔离级别并不保证不出现幻读（Phantom Read），而这些记录又属于非用户可见的，可以看做是由于MySQL的底层实现带来的多余加锁，因此虽然看似违反了2PL但并不会造成错误的后果。但需要注意的是这些锁还是在加锁之后才又释放的，因此虽然窗口很小但还是会有锁等待甚至是死锁的可能。这也是一些极端情况下，在Read Committed隔离级别下访问不同Key的事务也有概率出现死锁的原因。
1. Read Repeatable及以上隔离级别时，对于等值查询，当遍历到第一个不满足查询条件的记录时，对这个记录加**Gap Lock**(LOCK_GAP)，而不是正常的**Next Key Lock**（LOCK_ORDINARY）来降低锁冲突。
1. Read Repeatable及以上隔离级别时，对于等值查询，对于唯一索引上的非Delete Mark的记录，加**Record Lock**（LOCK_REC_NOT_GAP）而不是**Next Key Lock**（LOCK_ORDINARY）。这是因为在唯一索引上满足等值查询的记录最多只能有一条，所以只要对这个记录加记录锁就不存在后续同样满足条件的记录被插入的问题。但对Delete Mark记录是不可以的，比如二级索引上就可以存在重复的Delete Mark记录。

除此之外，InnoDB的还实现了前面提到的**Fence Key**的优化，上面介绍了在Read Repeatable隔离级别下，会对扫描到的记录加**Next Key Lock**（LOCK_ORDINARY）来避免幻读（Phantom Read），这个锁是一个左开右闭区间的锁。而我们的加锁对象是Record在Page上的物理位置Heap No，当需要插入一条记录的时候，需要去判断下一条记录上有没有**Next Key Lock**（LOCK_ORDINARY），如果正好是当前Page的最后一条记录，这个时候就需要去访问这个Page的后继节点，如果这个Page不在Buffer Pool还需要从磁盘加载。但我们其实并不需要访问后面Page的数据，这个操作就会引入了不必要的开销。而InnoDB的实现上通过在Page上的哨兵记录Supremum上维护锁避免了这种情况的发生，也就是在上面所说的扫描Record的过程中，如果扫描到了Supremum，在继续向后迭代之前需要在这个Supremum上也维护一个**Next Key Lock**（LOCK_ORDINARY），这样以来后续的插入操作就可以在当前Page判断有没有锁冲突。当然在发生Page合并分裂等操作时，这个Supremum上的Lock也需要被合适地处理，我们后面回来介绍这部分内容。

我们这里一个例子来说明：

TODO 图

对于Update和Delete操作，在第一步通过index_read和general_fetch这两个函数中的row_search_mvcc获取到一条满足条件的记录的同时，已经持有了必要的二级索引或聚簇索引上合适的锁，之后再通过**row_upd**去真正做几路的Update或Delete的时候，可能还需要获取额外的锁，一个简单的例子是，经过聚簇索引的查找之后，需要Update一个二级索引的列，那么这个时候在row_upd中最终会调用**lock_sec_rec_modify_check_and_lock**对要修改的二级索引上的记录也加上锁。



#### 2. Insert加锁过程

与上面所讲到Selete、Update、Delete不同，Insert操作的访问模式不需要根据Where条件的Search，而是直接定位目标记录在B+Tree上的位置，然后完成插入，在插入之前需要通过Lock的判断来避免出现Non-Repeatable或者Phantom。除此之外，索引的唯一性保证的要求会使得Insert过程变得稍微复杂一些，这种唯一性的要求，包括聚簇索引（Primary Index）和唯一二级索引（Unique Index），简单的Insert语句在遇到唯一性冲突（Duplicate Key）的时候会直接报错返回，而如果采用了Insert on duplicate key update及Replace语句，这个Insert操作就会转换为一次Update，或者是一次Delete加Insert的操作，如下图交互图所示：

TODO insert交互图



MySQL会通过**write_row**接口来调用InnoDB进行插入操作，这里最终会调用到**row_ins**函数，这个函数中会依次对主索引和所有二级索引完成插入。其中对主索引调用**row_ins_clust_index_entry_low**函数，对二级索引调用**row_ins_sec_index_entry_low**函数。这两个函数中的操作都可以分为唯一性检查和插入两个部分。

**唯一性检查：**

对于聚簇索引和唯一二级索引，当通过btr_pcur_open定位到这个索引B+Tree的插入位点后，如果发现要插入的值已经存在，就触发了唯一性检查的失败，会统一直接返回DB_DUPLICATE_KEY的错误，但后续MySQL上层是返回（Insert）还是转换为Update（Insert ... on duplicate key update）或Delete加Insert（Replace）的操作是不同的，自然这里对遇到的重复Key的加锁也应该不是同的，InnoDB层是怎么做区分的呢，答案是MySQL在进入write_row之前将这个操作的不同类型记录在trx->duplicates中，值TRX_DUP_IGNORE表示是Insert ... on duplicate key update，TRX_DUP_REPLACE表示是Replace。

主索引上的唯一性检查失败的处理函数是**row_ins_duplicate_error_in_cluster**





insert

唯一性检测保证

外键检测保证



## Lock维护（Lock Manger）

lock hash的维护方式

加锁

放锁

锁唤醒

隐式锁

## 死锁及死锁检测

35之后的优化



## 总结



## 参考



