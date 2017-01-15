---
layout: post
title: 庖丁解LevelDB之数据存储
category: 技术
tags: [leveldb, nosql，存储引擎，源码，source code, 数据格式，数据存储，数据]
keywords: leveldb，nosql，存储引擎，源码，source code，数据格式，数据存储，数据
---

作为一个存储引擎，数据存储自然是LevelDB重中之重的需求。本文就将详细的介绍LevelDB的数据存储方式。我们已经了解了LevelDB的使用流程，及数据在Memtable，Immutable，SST文件之间的流动。下面将分别介绍数据在不同角色中的存储方式，数据结构及设计思路。

## **Memtable**

Memtable对应Leveldb中的内存数据，LevelDB的写入操作会直接将数据写入到Memtable后返回。读取操作又会首先从Memtable中进行查询。那么我们先来看下LevelDB对Memtable的需求：

- 常驻内存；


- 可能会有频繁的插入和查询操作；
- 不会有删除操作；
- 需要支持阻写状态下的遍历操作（Immutable的Dump过程）

LevelDB采用跳表SkipList实现，在给提供了O(logn)的时间复杂度的同时，又非常的易于实现：

TODO SkipList图

SkipList中单条数据存放一条Key-Value数据，定义为：

```
SkipList Node := InternalKey + ValueString
InternalKey := KeyString + SequenceNum + Type
Type := kDelete or kValue
ValueString := ValueLength + Value
KeyString := KeyLength + Key
```



## **Log**

数据写入Memtable之前，会首先顺序写入Log文件，以避免数据丢失。LevelDB实例启动时会首先从Log文件中恢复Memtable内容。所以我们对Log的需求是：

- 磁盘存储
- 大量的Append操作
- 没有删除单条数据的操作
- 遍历的读操作

LevelDB首先将每条写入数据序列化为一个Record，单个Log文件中包含多个Record。同时，Log文件又划分为固定大小的Block单位，并保证Block的开始位置一定是一个新的Record。这种安排使得发生数据错误时，最多只需丢弃一个Block大小的内容。显而易见地，不同的Record可能共存于一个Block，同时，一个Record也可能横跨几个Block。

TODO Log格式

```
Block := Record * N
Record := Header + Content
Header := Checksum + Length + Type
Type := Full or First or Midder or Last
```

Log文件划分为固定长度的Block，每个Block中包含多个Record；Record的前56个字节为Record头，包括32位checksum用做校验，16位存储Record实际内容数据的长度，8位的Type可以是Full、First、Middle或Last中的一种，表示该Record是否完整的在当前的Block中，如果不是则通过Type指明其前后的Block中是否有当前Record的前驱后继。



##  **SST文件**

SST文件是Leveldb中数据的最终存储角色，划分为不同的Level，Level 0的SST文件由Memtable直接Dump产生。其他层次的SST文件则由其上一层文件在Compaction过程中归并产生。读请求时可能会从SST文件中查找某条数据。因此我们对SST文件的需求是：

- 支持顺序写操作
- 支持遍历操作
- 查找操作



