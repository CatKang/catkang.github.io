---
layout: post
title: 庖丁解LevelDB之数据存储
category: 技术
tags: [leveldb, nosql，存储引擎，源码，source code, 数据格式，数据存储，数据]
keywords: leveldb，nosql，存储引擎，源码，source code，数据格式，数据存储，数据
---

作为一个存储引擎，数据存储自然是LevelDB重中之重的需求。我们已经在[庖丁解LevelDB之概览](http://catkang.github.io/2017/01/07/leveldb-summary.html)中介绍了Leveldb的使用流程，以及数据在Memtable，Immutable，SST文件之间的流动。本文就将详细的介绍LevelDB的数据存储方式，将分别介绍数据在不同介质中的存储方式，数据结构及设计思路。

## **Memtable**

Memtable对应Leveldb中的内存数据，LevelDB的写入操作会直接将数据写入到Memtable后返回。读取操作又会首先尝试从Memtable中进行查询。我们对Memtable的需求如下：

- 常驻内存；


- 可能会有频繁的插入和查询操作；
- 不会有删除操作；
- 需要支持阻写状态下的遍历操作（Immutable的Dump过程）

LevelDB采用跳表SkipList实现，在给提供了O(logn)的时间复杂度的同时，又非常的易于实现：

![跳表](http://i.imgur.com/1TZ97zy.png)

SkipList中单条数据存放一条Key-Value数据，定义为：

```
SkipList Node := InternalKey + ValueString
InternalKey := KeyString + SequenceNum + Type
Type := kDelete or kValue
ValueString := ValueLength + Value
KeyString := KeyLength + Key
```



## **Log**

数据写入Memtable之前，会首先顺序写入Log文件，以避免数据丢失。LevelDB实例启动时会从Log文件中恢复Memtable内容。所以我们对Log的需求是：

- 磁盘存储
- 大量的Append操作
- 没有删除单条数据的操作
- 遍历的读操作

LevelDB首先将每条写入数据序列化为一个Record，单个Log文件中包含多个Record。同时，Log文件又划分为固定大小的Block单位，并保证Block的开始位置一定是一个新的Record。这种安排使得发生数据错误时，最多只需丢弃一个Block大小的内容。显而易见地，不同的Record可能共存于一个Block，同时，一个Record也可能横跨几个Block。

![Log format](http://i.imgur.com/ZqIvZAk.png)

```
Block := Record * N
Record := Header + Content
Header := Checksum + Length + Type
Type := Full or First or Midder or Last
```

Log文件划分为固定长度的Block，每个Block中包含多个Record；Record的前56个字节为Record头，包括32位checksum用做校验，16位存储Record实际内容数据的长度，8位的Type可以是Full、First、Middle或Last中的一种，表示该Record是否完整的在当前的Block中，如果不是则通过Type指明其前后的Block中是否有当前Record的前驱后继。



##  **SST文件**

SST文件是Leveldb中数据的最终存储角色，划分为不同的Level，Level 0的SST文件由Memtable直接Dump产生。其他层次的SST文件则由其上一层文件在Compaction过程中归并产生。读请求时可能会从SST文件中查找某条数据。我们对SST文件的需求是：

- 支持顺序写操作
- 支持遍历操作
- 查找操作


我们将从物理格式和逻辑格式两个方面来介绍SST文件中的数据存储方式。所谓物理格式指的是数据的存储和解析方式；利用确定的物理格式，我们可以存储不同意义的数据，这就是数据的逻辑格式。

##### 物理格式

LevelDB将SST文件定义为Table，每个Table又划分为多个连续的Block，每个Block中又存储多条数据Entry：

![SST物理格式](http://i.imgur.com/mXoNhdx.png)



可以看出，单个Block作为一个独立的写入和解析单位，会在其末尾存储一个字节的Type和4个字节的Crc，其中Type记录的是当前Block的数据压缩策略，而Crc则存储Block中数据的校验信息。Block中每条数据Entry是以Key-Value方式存储的，由于是有序存储，Leveldb可以很巧妙了利用相邻数据Key可能有相同的Prefix的特点来减少存储数据量。如上图所示，每个Entry只记录自己的Key与前一个Entry Key的不同部分。在Entry开头记录三个长度值，分别是当前Entry和其之前Entry的公共Key Prefix长度、当前Entry Key自有Key部分的长度和Value的长度。通过这些长度信息和其后相邻的特有Key及Value内容，结合前一条Entry的Key内容，我们可以方便的获得当前Entry的完整Key和Value信息。

这种方式非常好的减少了数据存储，但同时也引入一个风险，如果最开头的Entry数据损坏，其后的所有Entry都将无法恢复。为了降低这个风险，leveldb引入了重启点，每隔固定条数Entry会强制加入一个重启点，这个位置的Entry会完整的记录自己的Key，并将其shared值设置为0。同时，Block会将这些重启点的偏移量及个数记录在所有Entry后边的Tailer中。

##### 逻辑格式

Table中不同的Block物理上的存储方式一致，如上文所示，但在逻辑上可能存储不同的内容，包括存储数据的Block，存储索引信息的Block，存储Filter的Block：

![SST逻辑格式](http://i.imgur.com/1nTxs5r.png)

- **Footer：**为于Table尾部，记录指向Metaindex Block的偏移量和指向Index Block的偏移量。Footer是SST文件解析开始的地方，通过Footer中记录的这两个关键元信息Block的位置，可以方便的开启之后的解析工作。另外Footer种还记录了用于验证文件是否为合法SST文件的Magicnum。
- **Index Block：**记录Data Block位置信息的Block，其中的每一条Entry指向一个Data Block，其Key值为所指向的Data Block最有一条数据的Key，Value为指向该Data Block位置的Handle。需要说明的是Table中所有的Handle是通过偏移量Offset以及Size一同来表示的。
- **Metaindex Block：**
- **Data Block：**
- **Meta Block：**