# LSM and SSD



近年来，以LevelDB和Rocksdb为代表的LSM（Log-Structured Merge-Tree）存储引擎凭借其优异的写性能及不俗的读性能成为众多分布式组件的存储基石，包括团队近两年开发的类Redis大容量存储Pika和分布式KV存储Zeppelin，在享受LSM的高效的同时也开始逐渐体会到它的不足，比如它在大Value场景下的差强人意以及对磁盘的反复擦写。正如之前的博客[庖丁解LevelDB之概览](http://catkang.github.io/2017/01/07/leveldb-summary.html)中已经介绍了的LevelDB的设计思路，其最大的优势便是将磁盘的随机写转化为顺序写，但随着在系统中越来越多的使用SSD，这种设计是否仍然能带来如此大的收益，在SSD统治的世界里是否有更合理的存储结构。

2016年，FAST会议发表了论文[WiscKey: Separating Keys from Valuesin SSD-conscious Storage](https://www.usenix.org/system/files/conference/fast16/fast16-papers-lu.pdf)，阐述了一种对SSD更友好的基于LSM的引擎设计方案。

## **问题**

我们知道，LSM Tree是一种对写优化的系统，将随机写转化为顺序写，从而获得非常优秀的写性能，但一定的LSM也损失了一些东西作为交换，这个损失就是读写放大，即实际的磁盘读写跟用户请求读写的比值，就是说：

**LSM Tree 用大量的重复写入来交换让随机写获得顺序写的性能**

那么这种交换是否值得呢，先来看损失，以LevelDB为例，在最坏的情况下：

- 写放大：10 * Level（Level N-1向Level N的Compact可能涉及多达10个Level N-1层文件）
- 读放大：(index block + bloom-filter blocks + data block) * (L0文件数 + Level数)

也就是说，这个读写放大的系数大概在几十到几百之间。那么收获的呢，通过下表中针对不同存储介质的写入测试数据，可以看出在传统的机械盘上顺序写的性能远远好于其随机写性能，这个性能差异接近一千倍。用数十倍的磁盘带宽损失换取近千倍的性能提升，在写入敏感的场景下这种交换的效果毋庸置疑。但不同的是，SSD盘相对具有较高的随机写能力，与顺序写的差距本身只有十倍左右，那么这种交换就显得有些得不偿失。同时，由于反复的写入会带来SSD的磨损从而降低寿命。

TODO 读写性能测试表



## **思路**

针对上面提到的问题，



## **参考**

[Datastructures for external memory](http://blog.omega-prime.co.uk/?p=197)

