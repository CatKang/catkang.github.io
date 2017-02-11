通过之前对LevelDB的整体流程，数据存储以及元信息管理的介绍，我们已经基本完整的了解了LevelDB。接下来两篇要介绍的内容并不是LevelDB的基本组成，却是让LevelDB更优雅高效额重点和体现，Iterator就是这样一种存在。



## **作用**

正如[庖丁解LevelDB之数据存储](http://catkang.github.io/2017/01/17/leveldb-data.html)中介绍的，LevelDB各个组件用不同的格式进行数据存取。在LevelDB内部外部，各个不同阶段又不可避免的需要从不同的视角遍历这些数据。如果每一个层次的数据遍历都需要详细的关心全部数据存储格式，无疑将使得整个过程变得无比的冗余复杂。Iterator的出现正式为了解决这个问题，Iterator在各个层次上，向上层实现提供了十分重要的能力：

**无须了解下层存储细节的情况下，通过统一接口对下层数据进行遍历的能力。**





## **接口**

Iterator用确定的遍历接口将上层需求和下层实现解耦和。熟悉STL的同学一定不会陌生Iterator的实现方式，这里LevelDB的Iterator接口包括：

- Seek到某一位置的方法：Seek，SeekToFirst，SeekToLast；
- 访问前驱后继：Next，Prev；
- 判断当前位置是否有效：Valid；
- 获取当前位置数据信息：key，value，status；
- 可以注册多个Cleanup方法，当Iterator析构前做一些清理操作。



## **分类**

LevelDB大量使用了各种Iterator，根据Iterator的实现和层次，我们将其分为三种类型：

- 基本Iterator：最原子的Iterator，针对相应的数据结构实现Iterator接口；
- 组合Iterator：通过各种方式将多个基本Iterator组合起来，向上层提供一致的Iterator接口。
- 功能Iterator：利用基本Iterator或组合Iterator，附加一些必要的信息，实现某个过程中的遍历操作。



## **基本Iterator**

LevelDB中包括三种基本Iterator，他们分别针对Memtable，Block以及Version中的文件索引格式，实现了最原子的Iterator：

##### **1，MemTableIterator**

在Memtable Skiplist的格式上的Iterator实现。

![跳表](http://i.imgur.com/bmOK4Ui.png)

##### **2，Block::Iter **

针对SST文件Block存储格式的Iterator实现，Block格式如下：

![SST物理格式](http://i.imgur.com/mXoNhdx.png)

##### **3，Version::LevelFileNumIterator **

[庖丁解LevelDB之版本控制](http://catkang.github.io/2017/02/03/leveldb-version.html)中介绍了Version中记录了当前所有文件按层次划分的二维数组。其中Level1层之上的文件由于相互之间没有交集且有序，可以利用文件信息中的最大最小Key来进行二分查找。LevelFileNumIterator就是利用这个特点实现的对文件元信息进行遍历的Iterator。其中每个项记录了当前文件最大key到文件元信息的映射关系。这里的文件元信息包含文件号及文件长度。


## **组合Iterator**
组合Iterator由上述多个基本Iterator组合而成，LevelDB中包含两种组合Iterator

##### **1，TwoLevelIterator**
TwoLevelIterator实现逻辑上有层次关系的数据的遍历操作。组合了index iterator和data iterator两层迭代器，其中index iterator记录从数据key值到data iterator的映射，而data iterator则负责真正数据key到value的映射。生成TwoLevelIterator时，需要提供index Iterator及BlockFunction函数，其中BlockFunction实现了index iterator value值的反序列化以及对应的data iterator的生成。

##### **2，MergingIterator**
通过MergingIterator可以实现多个有序数据集合的归并操作。其中包含多个child iterator组成的集合。对MergingIterator的遍历会有序的遍历其child iterator中的每个元素。

## **功能Iterator**
通过对上述基本Iterator和组合Iterator的组合使用，可以实现不同场景下不同层次的数据遍历操作，这些Iterator这里成为功能Iterator，按其所负责的数据层次由下自上进行介绍：

##### **1，Table::Iterator**
对SST文件的遍历，通过[庖丁解LevelDB之数据存储](http://catkang.github.io/2017/01/17/leveldb-data.html)可知，这里有明显的层级关系，可以利用上面介绍的TwoLevelIterator，其index iterator为Index Block的Block::Iter，data iterator为Data Block的Block::Iter

TODO  结构图

##### **2，Compaction过程Iterator**
Compaction过程中需要对多个文件进行归并操作，并将结果输出到新的下层文件。LevelDB用MergingIterator来实现这个过程，其clild iterator包括[庖丁解LevelDB之版本控制](http://catkang.github.io/2017/02/03/leveldb-version.html)中提到的level层要Compaction的一个或多个文件以及leve+1层有key range重叠的文件相对应的Iterator：
- 如果有Level0文件，则包含所有level0文件的Table::Iterator
- 其他Level文件，包含文件索引的TwoLevelIterator，由Version::LevelFileNumIterato作为index iterator，Table::Iterator作为data iterator
TODO  结构图

##### **3，DBIter**
遍历整个DB数据的Iterator
TODO  结构图


## **总结**





## **参考**

Source Code：https://github.com/google/leveldb

庖丁解LevelDB之概览: http://catkang.github.io/2017/01/07/leveldb-summary.html

庖丁解LevelDB之数据管理: http://catkang.github.io/2017/01/07/leveldb-summary.html

庖丁解LevelDB之版本控制：http://catkang.github.io/2017/02/03/leveldb-version.html