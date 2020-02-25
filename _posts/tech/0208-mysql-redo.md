# 庖丁解InnoDB之REDO LOG

[数据库故障恢复机制的前世今生](http://catkang.github.io/2019/01/16/crash-recovery.html)中介绍了磁盘数据库为了在保证数据库的原子性(A, Atomic) 和持久性(D, Durability)的同时还能以灵活的刷盘策略来充分利用磁盘顺序写的性能，会记录REDO和UNDO日志，即**ARIES**方法。本文将重点介绍REDO LOG的作用，记录的内容，维护方式等内容，希望读者能够更全面准确的理解REDO LOG在InnoDB中的位置。



# 1. 为什么需要记录REDO

为了取得更好的读写性能，InnoDB会将数据缓存在内存中（InnoDB Buffer Pool），对磁盘数据的修改也会落后于内存，这时如果进程或机器崩溃，会导致内存数据丢失，为了保证数据库本身的一致性和持久性，InnoDB维护了REDO LOG。修改Page之前需要先将修改的内容记录到REDO中，并保证REDO LOG早于对应的Page落盘，也就是常说的WAL，Write Ahead Log。当故障发生导致内存数据丢失后，InnoDB会在重启时，通过重放REDO，将Page恢复到崩溃前的状态。



# 2. 需要什么样的REDO

那么我们需要什么样的REDO呢？首先，REDO的维护增加了一份写盘数据，同时为了保证数据正确，事务只有在他的REDO全部落盘才能返回用户成功，REDO的写盘时间会直接影响系统吞吐，显而易见，**REDO的数据量要尽量少**。其次，系统崩溃总是发生在始料未及的时候，当重启重发REDO的时候，系统并不知道哪些REDO对应的Page已经落盘，因此REDO重放必须可重入，即**REDO操作要保证幂等**。最后，为了便于通过并发应用的方式加快重启恢复速度，REDO应该是**基于Page**的，即一个REDO只涉及一个Page的修改。

熟悉的读者会发现，数据量小是**Logical Logging**的优点，而幂等以及基于Page正是**Physical Logging**的优点，因此InnoDB采取了一种称为**Physiological Logging**的方式，来兼得二者的优势。所谓Physiological Logging，就是以Page为单位在物理层面按逻辑的方式记录。举个例子，MLOG_REC_UPDATE_IN_PLACE类型的REDO中记录了对Page中一个Record的修改，记录方法如下：

（Page ID，Record Offset，(Filed 1, Value 1) ... (Filed i, Value i) ... )

其中，PageID指定要操作的Page页，Record Offset记录了Record在Page内的偏移位置，后面的Field数组，记录了需要修改的Field以及修改后的Value。同时，由于Physiological Logging的方式采用了物理Page中的逻辑记法，导致两个问题：

**1，需要基于正确的Page状态上回放REDO**

由于在一个Page内，REDO是以逻辑的方式记录了前后两次的修改，因此重放REDO必须基于正确的Page状态。然而InnoDB默认的Page大小是16KB，是大于文件系统能保证原子的4KB大小的，因此可能出现Page内容成功一半的情况。InnoDB中采用了**Double Write Buffer**的方式来通过写两次的方式保证恢复的时候找到一个正确的Page状态。这部分会在之后介绍Buffer Pool的时候详细介绍。

**2，需要保证REDO重放的幂等**

Double Write Buffer能够保证找到一个正确的Page状态，我们还需要知道这个状态对应REDO上的哪个记录，来避免对Page的重复修改。为此，InnoDB给每个REDO记录一个全局唯一递增的标号**LSN(Log Sequence Number)**。同时，Page在修改时，会将对应的REDO记录的LSN记录在Page上（FIL_PAGE_LSN字段），这样恢复重放REDO时，就可以来判断跳过已经应用的REDO，从而实现重放的幂等。





#3. REDO中记录了就哪些内容

知道了InnoDB中记录REDO的方式，那么REDO里具体会记录哪些内容呢？为了应对InnoDB各种各样不同的需求，到MySQL 8.0为止，已经有多打65种类型的REDO LOG。他们中记录这不同的信息，恢复需要通过REDO的类型来做对应的解析。根据REDO记录不同的作用对象，可以将这65中REDO划分为三个大类：作用于Page，作用于Space以及提供额外信息的Logic类型。另外需要指出，一个完整原子操作可能会包含多个上述REDO记录。

**1，作用于Page的REDO**

这类REDO占所有REDO类型的大多数，根据作用的Page的不同类型又可以细分为，Index Page REDO，Undo Page REDO，Rtree PageREDO等。比如MLOG_REC_INSERT，MLOG_REC_UPDATE_IN_PLACE，MLOG_REC_DELETE三种类型分别对应于Page中记录的插入，修改以及删除。这里还是以MLOG_REC_UPDATE_IN_PLACE为例来看看其中具体的内容：

![redo_insert](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/redo_insert.png)

其中，Type就是MLOG_REC_UPDATE_IN_PLACE类型，Space ID和Page Number唯一标识一个Page页，这三项是所有REDO记录都需要有的头信息，后面的是MLOG_REC_UPDATE_IN_PLACE类型独有的，其中Record Offset用给出要修改的记录在Page中的位置偏移，Update Field Count说明记录里有几个Field要修改，紧接着对每个Field给出了Field编号(Field Number)，数据长度（Field Data Length）以及数据（Filed Data）。

**2，作用于Space的REDO**

这类REDO针对一个Space文件的修改，如MLOG_FILE_CREATE，MLOG_FILE_DELETE，MLOG_FILE_RENAME分别对应对一个Space的创建，删除以及重命名。由于文件操作的REDO是在文件操作结束后才记录的，因此在恢复的过程中看到这类日志时其实文件操作已经成功，因此在恢复过程中大多只是做对文件状态的检查，以MLOG_FILE_CREATE来看看其中记录的内容：

![redo_space](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/redo_space.png)

同样的前三个字段还是Type，Space ID和Page Number，由于是针对Page的操作，这里的Page Number永远是0。在此之后记录了创建的文件flag以及文件名，用作重启恢复时的检查。

**3，提供额外信息的Logic REDO**

除了上述类型外，还有少数的几个REDO类型不涉及具体的数据修改，只是为了记录一些需要的信息，比如最常见的MLOG_MULTI_REC_END就是为了标识一个REDO组，也就是一个完整的原子操作的结束。





# 4. REDO是如何组织的

所谓REDO的组织方式，就是如何把需要的REDO内容记录到磁盘文件中，以方便高效的REDO写入，读取，恢复以及清理。我们这里把REDO从上到下分为三层：逻辑REDO层、物理REDO层和文件层。

**逻辑REDO层**

这一层表示的是真正的REDO内容，REDO由多个不同Type的多个REDO记录组成，有全局唯一的递增的偏移sn，innodb会在全局log_sys中维护当前sn的最大值，并在每次写入数据时将sn增加redo内容长度。

![logic_redo](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/logic_redo.png)



**物理REDO层**

磁盘是块设备，InnoDB中也用Block的概念来读写数据，一个Block的长度OS_FILE_LOG_BLOCK_SIZE等于磁盘扇区的大小512B，每次IO读写的最小单位都是一个Block。除了REDO数据以外，Block中还需要一些额外的信息，下图所示一个Log Block的的组成，包括12字节的**Block Header**：前4字节中Flush Flag占用最高位bit，标识一次IO的第一个Block，剩下的31个个bit是Block编号；之后是2字节的数据长度，取值在[12，508]；紧接着2字节的First Record Offset用来指向Block中第一个REDO组的开始，这个值的存在使得我们对任何一个Block都可以找到一个合法的的REDO开始位置；最后的4字节Checkpoint Number记录写Block时的next checkpoint number，用来发现文件的循环使用，这个会在文件层详细讲解。Block末尾是4字节的**Block Tailer中只记录的当前Block的Checksum，通过这个值，读取Log时可以明确Block数据有没有被完整写盘。

![image-20200216201419532](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/image-20200216201419532.png)

Block中剩余的中间498个字节就是REDO真正内容的存放位置，也就是我们上面说的逻辑REDO。我们现在将REDO真正的内容逻辑REDO放到物理REDO空间中，由于Block内的空间固定，而REDO长度不定，因此可能一个Block中有多个REDO，也可能一个REDO被拆分到多个Block中，如下图所示，棕色和红色分别代表Block Header和Tailer：

![physical_redo](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/physical_redo.png)

由于增加了Block Header和Tailer的字节开销，在物理REDO空间中用LSN来标识偏移，可以看出LSN和SN之间有简单的换算关系：

``` c++
constexpr inline lsn_t log_translate_sn_to_lsn(lsn_t sn) {
  return (sn / LOG_BLOCK_DATA_SIZE * OS_FILE_LOG_BLOCK_SIZE +
          sn % LOG_BLOCK_DATA_SIZE + LOG_BLOCK_HDR_SIZE);
}
```

SN加上之前所有的Block的Header以及Tailer的长度就可以换算到对应的LSN，反之亦然。



**文件层**

最终REDO会被写入到REDO日志文件中，以ib_logfile0、ib_logfile1...命名，为了避免创建文件及初始化空间带来的开销，InooDB的REDO文件会循环使用，通过参数innodb_log_files_in_group可以指定REDO文件的个数。多个文件收尾相连顺序写入REDO内容。每个文件以Block为单位划分，每个文件的开头固定预留4个Block来记录一些额外的信息，其中第一个Block称为**Header Block**，之后的3个Block在0号文件上用来存储Checkpoint信息，而在其他文件上留空：

![image-20200216222949045](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/file_header.png)

其中第一个Header Block的数据区域记录了一些额外的文件信息，如下图所示，4字节的Formate字段记录Log的版本，不同版本的LOG，会有REDO类型的增减，这个信息是8.0开始才加入的；8字节的Start LSN标识当前文件开始LSN，通过这个信息可以将文件的offset与对应的lsn对应起来；最后是最长32位的Creator信息，正常情况记录MySQL的版本。

![redo_file_header](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/redo_file_header.png)

现在我们将REDO放到文件空间中，如下图所示：

![redo_file](/Users/wangkang/Documents/github/catkang.github.io/_posts/tech/redo_file.png)

虽然通过LSN可以唯一标识一个REDO位置，但最终对REDO的读写还需要转换到对文件的读写IO，这个时候就需要表示文件空间的offset，他们之间的换算方式如下：

``` cpp
const auto real_offset =
      log.current_file_real_offset + (lsn - log.current_file_lsn);
```

切换文件时会在内存中更新当前文件开头的文件offset，*current_file_real_offset*，以及对应的LSN，*current_file_lsn*，通过这两个值可以方便地用上面的方式将LSN转化为文件offset。注意这里的offset是相当于整个REDO文件空间而言的，由于InnoDB中读写文件的space层实现支持多个文件，因此，可以将首位相连的多个REDO文件看成一个大文件，那么这里的offset就是这个大文件中的偏移。







# 5. 如何高效地写REDO

作为维护数据库正确性的重要信息，REDO日志必须在事务提交前保证落盘，否则一旦断电将会有数据丢失的可能，因此从REDO生成到最终落盘的完整过程成为数据库写入的关键路径，其效率也直接决定了数据库的写入性能。这个过程包括REDO内容的产生，REDO写入InnoDB Buffer，从InnoDB Buffer写入Page Cache，REDO刷盘。下面就通过这四个阶段来看看InnoDB如何在高并发的情况下还能高效地完成写REDO。

**REDO产生**

mtr



**写入InnoDB Buffer**



**写入Page Cache**



**刷盘**











- 怎么写log，从mtr 到 log buffer 到write，到flush





- checkpoint



# 6. 总结

