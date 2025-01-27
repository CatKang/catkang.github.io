# 庖丁解InnoDB之B+Tree
@(MySQL Index)

InnoDB采用B+Tree来维护数据，其处于非常核心的位置，可以说InnoDB中最重要的并发控制及故障恢复都是围绕着B+Tree来实现的。B+Tree本身是非常基础且成熟的数据结构，但在一个成熟的工业产品里，面对的是复杂的用户场景，多样的需求，高性能高稳定的要求，以及长达几十年的代码积累，除此之外，InnoDB中的B+Tree在实现上并没有一个清晰的接口分层，这些都让这部分的代码显得复杂晦涩。本文希望从中剥茧抽丝，聚焦B+Tree本身的结构和访问来进行介绍，首先会介绍什么是B+Tree，之后介绍InnoDB中的B+Tree所处的位置和作用，然后介绍其数据组织方式，访问方式，以及并发控制。除此之外，代码中交织在一起的诸如ahi、rtree、blob、代价估计等内容会先忽略掉。


## B+Tree
对MySQL这种磁盘数据库来说，当要访问的数据不在内存中的时候，就需要从磁盘中进行加载。而内存和磁盘的访问速度是有几千甚至上万的差距的，那么作为磁盘数据库的索引，能不能有效的降低从磁盘中加载数据的次数就变得非常重要。1970年，Rudolf Bayer《Organization and Maintenance of Large Ordered Indices》一文中提出了BTree[1]，之后在这个基础上演化除了B+Tree。B/B+Tree采用了多叉树的结构，显著的降低了数据的访问深度，尤其是B+Tree，通过限制所有的数据都只会存在于叶子节点，非叶子节点中只记录Key的信息，最大程度的压缩了索引的高度。这种索引结构的扁平化就意味着更少的磁盘访问，进而也意味这个更好得性能。因此，包括MySQL在内的大量主流的磁盘数据库都采用了B+Tree作为其索引的数据结构。如下图所示，是一个简单的B+Treed的示例：

TODO 图
B+Tree整体是一个多叉树的结构，其中每个节点中包含一组有序的key，介于两个连续的有序key，key+1中间的是指向一个子树的指针，而这个子树中包含了所有取值在[key, key+1)的记录。所有对B+Tree内容的填删改查都需要先对操作的key定位，这个定位过程需要从根节点出发，在每一层的节点中通过key的比较，找到需要的下一层节点，直到叶子节点。也就是说所有的操作都是在叶子结点发起的。除此只外，为了方便遍历操作，叶子节点会通过右向指针串联在一起。

TODO图

当叶子节点中的记录插入超过某个阈值的时候，需要触发分裂，分裂会创建新的页面，将要分裂的页面的上部分数据迁移到这个新的节点上去，并将指向这个节点的指针及对应的边界key插入到父亲节点中去，而这次插入有可能导致父节点的分裂，进而继续向上传导。与之对应的是从树中删除数据时，可能触发相邻节点的合并，同时需要从父节点中删除对应的key及指针，因此合并操作也可能向更上层传导。所有的分裂和合并都是从叶子节点发起并向上传导的，只有根节点的分裂和合并会造成树高的变化。这也就保证了从root到任意叶子的路径是相同的，从而支持logN的查找，插入以及删除复杂度。

## InnoDB中的B+Tree

#### 基于B+Tree的数据维护与访问
InnoDB中的每张表的都会维护成一个包含所有数据的B+Tree，称为聚簇索引。可以认为通常聚簇索引这个B+Tree中的Key就是这张表的主键字段，而Value就是完整的行数据。除此之外，为了加速访问，通常会在表上创建一个或多个二级索引，每个二级索引也会对应一个B+Tree，二级索引的B+Tree中的Key是这个索引字段，而Value是对应的聚簇索引上的Key。通过二级索引查找的记录，如果需要主键之外的更多信息就需要用这个主键再回到聚簇索引的B+Tree上做查找，这个就是我们常说的回表过程。如下图所示是一张MySQL表对应的数据结构，包含一个聚簇索引B+Tree，和多个二级索引B+Tree。
TODO 图


对MySQL数据库的增删改查请求，会在Server层通过优化器的代价估算，选择看起来最有的索引生成执行计划，最终转化为对对应的B+Tree的访问，从Root节点一路查找到需要的叶子结点，这个过程中访问的Page如果不在Buffer Pool都需要先从磁盘中加载到Buffer Pool中。


#### 基于B+Tree的并发控制
所谓并发控制就是数据库为了保证事务之间隔离性而设置的访问机制，《浅析数据库并发控制机制》一文中曾经对常见的并发控制机制做过简单的介绍和分类。InnoDB中的并发控制采用的的**Lock + MVCC**的方式，也就是采用MVCC来避免读写之间的冲突，但在写写或写和当前读之间采用了悲观的Lock的并发控制方式。
**MVCC部分**在《庖丁解innodb之UNDO》一文中介绍过：在聚簇索引上除了用户数据外，还会记录隐藏字段，包括最近修改的事务ID，以及指向历史版本的Roll Ptr指针，指向Undo日志中修改行的历史版本，快照读会根据配置的隔离级别持有ReadView，ReadView中记录获取ReadView是的活跃事务状态，通过对比聚簇索引上或UNDO Log上的事务ID和所持有ReadView中的当时时刻的活跃事务状态，就可以判断当前的版本是不是可见的，如果不可见就沿着Roll Ptr寻找正确的可见的版本。
而对于**Lock的实现**，在《B+树加锁历史》一文中曾经介绍过，基于B+Tree的并发控制发展一直遵循着降低锁粒度的方向，从将BTree整体作为加锁对象；到将Btree Page当成加锁单位，并围绕如何减少事务需要持有的锁的Page数量而发展，提出了Lock Coupling的来实现提前释放祖先节点的Lock，又通过Blink Tree避免对父节点的加锁；直到ARIES/KVL将逻辑内容和物理内容分离，由Lock和Latch分别保护，并提供了一套相对完善的对Record加锁的实现算法，基本形成了现代B+Tree数据库的通用解法，InnoDB就是其中之一。InnoDB中维护了专门的Lock Manager模块来处理事务之间的加锁、阻塞、死锁检测等，这部分内容会在后续文章中做详细介绍。这里主要关注的是其跟B+Tree的关系，Lock Manager中的加锁对象可以简单的理解为聚簇索引或二级索引B+Tree叶子结点上的某个Key的物理位置。因此，在加锁之前需要先在对应的B+Tree上定位需要的的记录。以记录的update为例，其加Lock及记录Undo的流程大约如下：

todo流程

另外值得一提的是，InnoDB采用了xxx一文中提到的ghost record实现，也就是所有的删除操作，只会对记录设置delete mark标记，而将真正的删除操作推迟到后台Undo Purge中进行。从而将delete操作转换为记录的原地update操作，从而避免对区间Lock的需要。

同样的，按照ARIES/KVL的设计，InnoDB中采用**Latch来保护B+Tree本身物理结构**在多线程访问下的正确，比如正在修改的Page不应该被其他线程看到，又比如一个分裂操作中的中间状态不应该被其他线程看到。InnoDB中承担这个责任的主要有两个锁，分别是保护整个btree的index lock，以及保护每个page的page lock。在本文后面的并发控制章节会对这个部分详细讨论。




#### 基于B+Tree的故障恢复
类似于并发控制，在故障恢复上InnoDB也区分了逻辑和物理两层，关于这一点更多的内容可以参考《B+树故障恢复历史》，简单的说在逻辑层的故障恢复需要保证的是在发生故障重启后，已经提交的事务依然存在，未提交的事务的任何修改都不存在。在InnoDB中，这一点是靠Redo和Undo Log来实现的。这里主要关注的的物理层的故障恢复，也就是如何保证在数据库重启后，B+Tree可以恢复到正确的位置，而不是一个树结构变更的中间状态。InnoDB中有一个很关键的数据结构：min-transaction（mtr）。InnoDB中针对B+Tree结构变更的操作，例如节点的分裂或者合并，这个过程可能会涉及到多个兄弟节点以及其祖先节点的修改，这些修改会记录到同一mtr的Redo中，只有当所有这些修改都完成后，收集到所有Redo的mtr才会进入commit阶段，这时会在这组Redo的末尾添加MLOG_END的特殊类型的日志，并等待这些Redo Log成功的写入磁盘。只有mtr完成commit之后，对应的事务才能提交，对应的脏页才能落盘。当发生故障重启的时候，在真正做Redo重放之前，Redo Parse会先尝试去找MLOG_END日志，如果看到这个标记，那么这段连续的mtr中的所有redo才能被重放，否则这个mtr中的所有redo都不能重放。从而保证commit掉的mtr中涉及的所有Page的修改都可以恢复，而没有commit的所有Page修改全部被丢弃。

TODO 图






## B+Tree的数据组织
B+Tree是很基础的数据结构，但通常在学术上讨论的时候，其中维护的数据项，都会限定为简单的定长Key Value，这使得实现上对数据的访问，以及判断否需要分裂或合并等操作都非常容易，但对面向现实需求的存储引擎的InnoDB来说，这样显然是不够的，再加上上面所讲到的并发控制、故障恢复的需要，InnoDB中的B+Tree数据组织上会显得复杂不少。

#### B+Tree中的数据项：Record
前面讲到，InnoDB中用B+Tree来维护数据，对数据库来说，这些数据就是数据库的一行行表数据。当用户创建一张表的时候，会在SQL语句中指定这张表中的每一行包含那些列，每一列的类型和长度，是否可以为null，这些信息都会记录在MySQL的数据字典（Data Dictionary）中，本文不对这里展开讲述，这里只需要知道，数据字典的些列及列长信息，会在对InnoDB的B+Tree进行写入或者读取的时候，通过dict_index_t的数据结构传递下来，并以这个格式进行用户每一行数据Record的序列化及反序列化，以聚簇索引中记录的完整Record为例，一行用户数据序列化后会维护成如下格式：
![Alt text](./1737858452517.png)

可以看到，其中有记录key的列，以及记录Value的列，之所以这里Key也会有多列，是因为可能有组合索引的情况。除此之外，Trx ID及Rollptr作用在上面介绍过，用来对读提供MVCC访问；Record Header中也记录了一些访问过程中需要的记录元信息，依次是变长列的长度数组length array，null记录的bitmap，是否被标记delet mark，当前记录的物理位置标识heap no，状态，以及记录下一条Record偏移的Next指针。

上面介绍的是记录完整的行数据的聚簇索引B+Tree中的Record格式，而对二级索引B+Tree中的Record格式略有区别，如下图所示，主要区别在于，其中的Key是建表是定义的二级索引列，其中的Value是对应的聚簇索引列：
![Alt text](./1737859390562.png)


#### B+Tree中的节点：Page
InnoDB中B+Tree中的每一个页面，对应InnoDB中的一个Page，默认大小是16KB。一个这样的Page中通常会维护很多的Record，这些Record通过上面介绍过的Record上的Next指针在Page内串成一个单向链表，除了真实的用户Record外，为了逻辑的简单，类似于我们通常处理链表问题时候采用的“哨兵”，InnoDB的B+Tree Page中也预留了两个固定位置固定值的System Records，在链表头的Infimum记录以及在链表尾的Supremum记录。
由于Key Value并不是定长的，无法通过Key方便的在页内做定位，InnoDB在Page内还维护了一个Record目录（Directory），这个Directory维护连续存放的多个定长的slot，每个slot占用两字节，记录其指向的Record的页内偏移，如下图所示：
![Alt text](./1737860436991.png)

图中最上面的连续的Direcory中的每个slot指向的一个标粗的Record的页内偏移，这样的两个Record之间的Record称为被这个Slot owned，在插入和删除的过程中，这些slot会动态的进行分裂或平衡，来保证除了最后一个slot外，所有的slot所owned的Record在4到8之间。由于这些这些Directory slot本身是定长的，做页内的Key查找的时候就可以很方便地通过这些连续的slot实现二分查找，找到其owned的这一组4到8个Record，再做顺序查找就大大提高了页内查询的效率。可以看出这些slot需要连续，并且随着Record的插入也需要不断的扩展，因此在实现上，不同于Record在页内自上而下的生长方式，Direcotry是从页尾向上的扩展的，二者中间的部分就是页上的空闲区域，如下图所示：
![Alt text](./1737868117048.png)
![Alt text](./1737860632079.png)

除了上面已经介绍过的System Record、User Record、Page Direcory以及他们之前的Free Space外，每个B+Tree的还会有一个Index Header的的定长部分，其中PAGE_N_DIR_SLOTS记录的是有多少个Direcory Slot，PAGE_HEAP_TOP记录的是这个空闲的空间的开头，分配新的Record空间的时候会从这里分配，每次分配PAGE_N_HEAP这个计数器都会加一，因此每个Record的位置都会拥有一个页内独一无二的heap no，这个值也会作为Lock Manager中对记录的加锁对象；除此之外，由于Record是可能删除的，Page还维护了一个简单的Free List，PAGE_FREE就是这个链表头，PAGE_GARBAGE是这个链表的个数，不过这个空闲链表得实现相当简单，当新的Record写入时，仅仅会尝试链表头的那个Record位置是不是够用，够就摘下来复用，不够就从PAGE_HEAP_TOP这个堆上分配；接下来的PAGE_LAST_INSERT维护的是上一次插入的的记录，这个值维护的是该Page上最近的一些插入情况，为的是在页分裂的时候可以做一些启发式的规则来避免空间浪费；PAGE_DIRECTION是之前插入的方向，PAGE_N_DIRECTION记录连续朝这个方向插入的个数；最后PAGE_N_RECS是当前Page的记录数，PAGE_MAX_TRX_ID是最大的事务id，这个值通常只在二级索引Page上有用；PAGE_LEVEL是当前Page在B+Tree上的层级，叶子节点是0。

在Page Header里除了当前Page的Checksum及Page LSN之外，还会有两个链表指针，在B+Tree中指向其兄弟节点的页编号，因此每一层的Page都会组成一个Page的双向链表。前面我们还讲过，B+Tree的非叶子节点中只会维护Key而没有Value，对非叶子节点来说，他的Value就是落在这个Key范围内的下层Page的页编号。因此，最终一个B+Tree上的所有Page会通过纵向的子节点指针和横向的兄弟节点指针串成一个如下图所示的B+Tree：
![Alt text](./1737862713870.png)

TODO 描述节点的最小值对应父节点中的key



## B+tree的访问
我们已经知道MySQL的所有的增删改查操作，经过Server层级InnoDB层都会转换为一次次对某个聚簇索引或二级索引的B+Tree的查询、修改、插入。由于采用了Ghost Record（Delete Mark）的实现方式，SQL的删除操作总是被转换成一次Record上的Delete Mark标记的更新操作，之后再Undo Purge的过程中才会真正进行对B+Tree的删除操作，下面我们就**站在B+Tree的角度**来看看这些操作是如何进行的。由于所有的Value都只存在在叶子节点上，因此所有的操作，第一步都需要先在B+Tree上完成对这个Key得定位。

#### B+Tree的定位
这个定位过程的逻辑主要在**btr_cur_search_to_nth_level**中，这个是个非常长且晦涩的函数，这里我们先忽略RTree、AHI、Insert Buffer、Blob以及下一章节将要介绍的并发控制相关内容后，其逻辑其实是非常简单的：首先，这个函数的调用者会指定要查找的key field值以及search_mode(大于、大于等于、小于、小于等于)；然后从描述这个B+Tree的数据字典元信息dict_index_t中，获得这个B+Tree的Root Page Number，通过**buf_page_get_gen**去获取这个这个Page，其中如果不在Buffer Pool会从磁盘中加载近内存；之后，通过**page_cur_search_with_match**去做页内的搜索，包括根据Directory Slot的二分查找，以及定位到对应Slot后对其owned Records的顺序遍历，找到需要的Key范围，得到下一层的Page Number，重复上面的这个buf_page_get_gen + page_cur_search_with_match过程，直到找到满足search_mode的叶子节点上的Record位置。这个位置信息会维护在一个btr_cur_t结构中，供调用者使用，也可能固化在当前线程的btr_pcur_t结构中，其中记录获得这个cursor时候得版本号，通过这个版本号，后续的访问只要发现Page没有改动就可以直接使用这个位置信息，避免重复的B+Tree查询。后续的操作都会基于这个位置信息cursor做操作，读取是最简单的，直接获取Value信息即可。


#### B+Tree的修改、插入、删除
InnoDB中对B+Tree的修改、插入以及删除操作都会存在乐观和悲观两个版本，乐观版本会假设不会导致树结构的变化，因此持有较轻量的锁，如果失败，那么就获取更重的锁，然后通过悲观版本来完成变更。这么做的思路是大多数的B+Tree操作都不会导致树结构的变化，那么就可以尽量的乐观来减少加锁的开销。一次Update的过程如下：
- **btr_cur_optimistic_update**会比较要修改的Record的老值和新值占用的空间大小，如果新值更小，那么简单的通过**btr_update_in_place**在当前位置直接更新，并接受Record变小带来的碎片。

- 如果新值变的更大，那么就需要先在Page上删除老的Record，再插入新的Record，这时会先计算删除后是否有空间插入新的的Record，如果能，那么通过**page_cur_delete_rec**删除，之后再通过**btr_cur_insert_if_poossible**再次插入就好。

- 但如果Page上无法放下新值，那么就需要返回失败，并在加更重的锁之后通过**btr_cur_pessimistic_update**来完成，这里先page_cur_delete_rec完成删除，然后通过**btr_cur_pessimistic_insert**来做悲观插入，其中可能需要先完成B+Tree的节点分裂甚至是树层数的增高。

这个过程中触发的Page内的Record插入或者删除，都会维护上面所讲到的页内Record链表，Free List以及Directory Slot，如下图所示，是一次将Record修改成更大的值的过程，在Page内发生了一次老Record的删除，以及一次新Record的插入，同时老的Record被加入到了Free List（Garbage）中。
![Alt text](./1737899225990.png)


对于插入操作而言，同样先乐观的通过**btr_cur_optimistic_insert**尝试插入，如果Page内空间充足，那么通过**page_cur_tuple_insert**完成页内插入，否则返回失败，之后通过**btr_cur_pessimistic_insert**来做悲观插入。类似的，删除操作会先乐观地通过**btr_cur_optimistic_delete**来删除，其中需要先采用**btr_cur_can_delete_without_compress**判断删除后是否需要触发Page合并，也就是Page中的剩余Record值是否小于了阈值。如果不会，那么通过**page_cur_delete_rec**完成删除。否则，需要返回失败，并在之后通过**btr_cur_pessimistic_delete**做悲观的删除，也就是在删除后触发Page的合并，甚至是树层数的降低。

#### B+Tree的节点分裂
当前Page的空间无法放下要插入的Record的时候，就需要触发当前Page的分裂，由于B+Tree的所有Value都只存在于叶子结点，因此通常情况下节点的分裂都是从叶子节点的分裂发起的，叶子节点分裂后，新的节点插入到父节点中，导致级联的上层Page分裂。这里有一种例外，是子节点删除第一项，那么需要在其父节点中删除老的key，并插入新的key，这个插入动作也有可能导致父节点的分裂。
节点分裂的实现代码主要在**btr_page_split_and_insert**中，第一步是要确定split_rec，也就是从那个位置开始把之后的Record移动到新分裂出来的Page上去，一般情况下，这个split_rec会选择当前Page中间的那个，也就是分裂后的两个兄弟节点每人负责一般的数据。但这样一来，在导入数据这样的场景中，插入的数据是有序递增的，那么前面的一个Page就永远只有一半的数据，整个B+Tree的空间利用率就变成了50%。为了尽量避免这种情况，InnoDB中采用了简单的启发式规则，这就要用到前面我们再Page格式中介绍的Index Page Header上的信息，PAGE_LAST_INSERT，基本思路是如果这个Page上的两次连续的Insert是刚好有序的两个Record，那么很有可能当前是一个顺序插入的场景，那么就从这个插入的位置来做分裂。
确定了split_rec后面的分裂操作就比较简单了，首先从文件上分配并初始化一个新的Page；然后通过**btr_attach_half_pages**将这个新Page加入的B+Tree中，包括向父节点中添加这个新节点的Key及指针，以及将这个Page加入同一层的兄弟节点的双向链表中，注意向父节点的插入操作可能触发级联向上的Page分裂；之后将前面找到的split_rec后面的Records拷贝到新的Page上去，并在老的Page中删除；最后在完成新Record的插入即可，这个插入有可能插入新节点也有可能插入老节点，取决于前面split_rec的选择。这个分裂过程如下图所示：
TODO 分裂图

在整个B+Tree都很满的情况下，这种从叶子节点发起，一路向上的级联节点分裂，有可能一路传到到Root Page，造成Root Page的分裂，而Root Page分裂会带来整个B+Tree层数的变高。这个过程的实现主要咋**btr_root_raise_and_insert**中，由于Root Page头中有一些特殊的信息，并且这个位置是记录在数据字典中的，我们不希望Root Page的分裂带来这些信息的修改，因此这里采取了保留原Root的Page的方式：首先分配一个新的Page，将Root上的所有记录都拷贝到这个New Page上，然后清空Root Page并将这个New Page挂到Root Page上作为其当前唯一的叶子节点，之后同样调用btr_page_split_and_insert来完成一次常规的Page分裂过程。


#### B+Tree的节点合并
从Page上删除Record的时候，如果造成Page上的空间占用低于一个阈值merge_threshold，那么就会触发节点合并，这个阈值默认是50%，当然也可以对整个Table或者单个索引通过设置COMMENT='MERGE_THRESHOLD=40'来修改为1到50中间的任何一个数。大多数的节点合并都是从叶子节点上删除数据触发叶子结点的合并，需要删除父节点中的元素，进而可能触发级联的上层节点合并。但有一种例外，是在做节点的插入操作时，如果当前节点无法放下并且是最后一个Record，那么就会首先尝试**btr_insert_into_right_sibling**插入到右边的兄弟节点，这个新的插入就会是右侧兄弟节点的第一个Key，而修改第一个Key就需要先从父节点中删除原先对应这个节点的Key，然后插入新的，这个删除操作同样有可能会触发父亲节点进而级联向上的节点合并。
节点合并的操作主要在**btr_compress**中完成，其中首先会通过**btr_can_merge_with_page**依次判断其左右兄弟节点是否足以放下要合并节点的所有记录，如果可以放下就进入正式的合并过程：将当前Page中的所有记录拷贝到要合并的兄弟节点中去，将这个节点从兄弟节点的双向链表中移除，并更新或删除父节点中的对应Key或指针，这个过程可能会触发级联向上的Page合并，如下图所示：
TODO 节点合并图

TODO btr_lift_page_up



## 并发控制
TODO 图，5.6 5.7 polardb的Latch实现位置：是锁tree，latch coupling，还是blink





## 文件组织
InnoDB中的数据最终是存储在磁盘上的文件中的，通常会设置innodb_file_per_table来让每个用户的表独占一个数据IBD文件，那么一张表中的聚簇索引B+Tree与所有可能的二级索引B+Tree都会共享这样一个文件，而每一个B+Tree或者进一步讲，每一个B+Tree的叶子或非叶子节点，他们内部在访问上是有相关性的，这种相关性的意思是说，其中的一部分Page在被访问的时候很大概率意味着起兄弟节点Page也很快会被访问到，但磁盘的特性是顺序访问的速度远远的好于随机读写的速度，因此一种良好的设计思路是让逻辑上相关的Page在物理上也尽量的连续，这样有相关性的Page访问的时候就会尽量的以顺序读写的方式来进行IO。为了实现这一点，需要两部分的工作：
1. 需要一种连续Page的元信息维护方式。
2. 需要一种按照逻辑相关性分配Page的方法。

对于第一个问题，以16KB的Page大小为例，InnoDB中将连续的64个Page组成一个1MB的Extent，每个Extent都需要一个XDES Entry来维护一些元信息，其中就包括这个Extend的是空闲、分配了部分还是全部分配的状态，以及其中每一个Page是不是被使用的Bitmap，这样一个Extent需要40个字节的元信息。
![Alt text](./1737874359507.png)

这个元信息需要能方便的找到，并且随着文件的向后扩张，Page不断的增多，有足够的位置来进行存储。InnoDB的实现是每隔256MB就在这个固定位置放一个特殊的XDES Page，其中维护其向后256个Extent的元信息。这个Page的格式如下：
![Alt text](./1737874251345.png)


对于第二个逻辑相关的问题，在InnoDB中维护了Segment的概念，这是一个逻辑概念，对应的是一组逻辑上相关的Page集合，每个Segment会尽量的获取一些连续的Page并持有，当这个Segment中得节点想要分配Page的时候，就优先从这些连续的Page中来获得。目前的InnoDB实现里，对每一个B+Tree维护了两个Segment，一个负责叶子节点，一个负责非叶子节点。这部分信息维护在B+Tree的root Page中，root Page除去上面讲的Page内容外，多出来的FSEG Header中就有其维护的两个Segment信息：
![Alt text](./1737873056931.png)
可以看出，这里对每个Segment其实都是用SpaceID + PageNO + Offset唯一锁定了一个叫做Inode Entry的文件偏移，通常一个IBD文件的第三个Page就是Inode Page，其中维护了最多84个Inode Entry，也就是最多84个Segment，绝大多数情况下都是足够的，当然如果不足就需要动态分配新的Inode Node。Inode Entry如下图所示：
![Alt text](./1737875458988.png)
可以看出，其中维护了一组其持有的Extent的链表，包括完全空闲、部分分配，或全部已分配，除此之外，还有32个碎片Page的位置，这个其实是一种分配策略上的权衡，一个连续Extent有64个Page，如果每个Segment最少都分配一个extent，显然会有极大的空间浪费，因此对于小的Segment会优先按照单个Page的方式进行分配，知道这个Segment得inode entry里的32个碎片page的位置已经用满。

而文件的第一个Page，FSP_HDR作为一个特殊的XDES Page，除了XDES Entry外，还会维护一些文件相关的FSP_HEADER信息，如下图所示：
![Alt text](./1737875957775.png)
其中除了Space ID，当前文件大小，以及完成初始化的文件大小等常规信息外，还包括了文件内全局空闲的Extent链表，以及按照碎片Page分配的Extent链表。综上所述，一个B+Tree在文件上的组织全景如下图所示：

TODO 大图




https://dev.mysql.com/doc/refman/8.4/en/innodb-file-space.html


