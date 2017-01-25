---
layout: post
title: 庖丁解LevelDB之版本控制
category: 技术
tags: [leveldb, nosql，存储引擎，源码，source code，版本，Version，元信息]
keywords: leveldb，nosql，存储引擎，源码，source code，版本，Version，元信息
---

版本控制或元信息管理，是LevelDB中比较重要的内容。本文首先介绍其在整个LevelDB中不可替代的作用；之后从代码结构引出其实现方式；最后由几个主要的功能点入手详细介绍元信息管理是如何提供不可或缺的支撑的。



## **作用**

从通过之前的博客，我们已经了解到了LevelDB整个的工作过程以及从Memtable，Log到SST文件的存储方式。那么问题来了，LevelDB如何能够知道每一层有哪些SST文件；如何快速的定位某条数据所在的SST文件；重启后又是如何恢复到之前的状态的，等等这些关键的问题都需要依赖元信息管理模块。对其维护的信息及所起的作用简要概括如下：

- 记录Compaction相关信息，使得Compaction过程能在需要的时候被触发；
- 维护SST文件索引信息及层次信息，为整个LevelDB的读、写、Compaction提供数据结构支持；
- 负责元信息数据的持久化，是的整个库可以从进程重启或机器宕机中恢复到正确的状态；
- 记录LogNumber，Sequence，下一个SST文件编号等状态信息；
- 以版本的方式维护元信息，使得Leveldb内部或外部用户可以以快照的方式使用文件和数据。

下面就将更详细的进行说明。

## **实现**

LeveDB用**Version**表示一个版本的元信息，Version中主要包括一个FileMetaData指针的二维数组，分层记录了所有的SST文件信息。**FileMetaData**数据结构用来维护一个文件的元信息，包括文件大小，文件编号，最大最小值，引用计数等。除此之外，Version中还记录了触发Compaction相关的状态信息，这些信息会在读写请求或Compaction过程中被更新。通过[庖丁解LevelDB之概览](http://catkang.github.io/2017/01/07/leveldb-summary.html)中对Compaction过程的描述可以知道在CompactMemTable和BackgroundCompaction过程中会导致新文件的产生和旧文件的删除。每当这个时候都会有一个新的对应的Version生成，并插入VersionSet链表头部。

**VersionSet**是一个Version构成的双向链表，这些Version按时间顺序先后产生，记录了当时的元信息，链表头指向当前最新的Version，同时维护了每个Version的引用计数，被引用中的Version不会被删除，其对应的SST文件也因此得以保留，通过这种方式，使得LevelDB可以在一个稳定的快照视图上访问文件。VersionSet中除了Version的双向链表外还会记录一些如LogNumber，Sequence，下一个SST文件编号的状态信息。

TODO VersionSet Version File示意图

通过上面的描述可以看出，相邻Version之间的不同仅仅是一些文件被删除另一些文件被删除。也就是说将文件变动应用在旧的Version上可以得到新的Version，这也就是Version产生的方式。LevelDB用**VersionEdit**来标识这种相邻Version的差值。

TODO Version 0 + VersionEdit = Version 1 示意图

为了避免进程崩溃或机器宕机导致的数据丢失，LevelDB需要将元信息数据持久化到磁盘，承担这个任务的就是**Manifest**文件。可以看出每当有新的Version产生都需要更新Manifest，很自然的发现这个新增数据正好对应于VersionEdit内容，也就是说Manifest文件记录的是一组VersionEdit值。

TODO Manifest文件内容

恢复元信息的过程也变成了一次应用VersionEdit的过程，如下图所示，可以看出这个过程中有大量的中间Version产生，但这个并不是我们所关心的。

TODO VersionEdit =》Version + VersionEdit => Version 过程

LevelDB引入VersionBuilder来避免这种中间变量，方法是先将所有的VersoinEdit内容整理到VersionBuilder中，然后一次应用产生最终的Version：

TODO引入VersionBuilder的方式

这一节中，我们依次看到了LevelDB版本控制中比较重要的几个角色：Version、FileMetaData、VersionSet、VersionEdit、Manifest和VersionBuilder。同时了解了他们各自的作用。接下来就一起从LevelDB主要的功能点中欣赏下他们的英姿。

## **功能点**

##### PickCompaction

##### CompactRange

##### Get

##### Recover




## **总结**





## **参考**

Source Code：https://github.com/google/leveldb

庖丁解LevelDB之概览: http://catkang.github.io/2017/01/07/leveldb-summary.html

庖丁解LevelDB之数据管理: http://catkang.github.io/2017/01/07/leveldb-summary.html

