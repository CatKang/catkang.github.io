# 数据库故障恢复历史



## 背景

在数据库系统发展的历史长河中，故障恢复问题始终伴随左右，也深刻影响着数据库结构的发展变化。通过故障恢复机制，可以实现数据库的两个至关重要的特性：Durability of Updates以及Failure Atomic。磁盘数据库由于其卓越的性价比一直以来都占据数据库应用的主流位置。然而，由于需要协调内存和磁盘两种截然不同的存储介质，在处理故障恢复问题时也增加了很多的复杂度。随着学术界及工程界的共同努力及硬件本身的变化，磁盘数据库的故障恢复机制也不断的迭代更新，尤其近些年来，随着NVM的浮现，围绕新硬件的研究也如雨后春笋出现。本文希望通过分析不同时间点的关键研究成果，来梳理数据库故障恢复问题的本质，其发展及优化方向，以及随着硬件变化而发生的变化。
文章将首先描述故障恢复问题本身；然后按照基本的时间顺序介绍传统数据库中故障恢复机制的演进及优化；之后思考新硬件带来的机遇与挑战；并引出围绕新硬件的两个不同方向的研究成果；最后进行总结。



## 问题

故障模型



AD



场景



问题描述



## 朴素做法



## Shadow Paging



## Logging



## ARIES



## MARS



## WBL



## 总结



## 参考

- [[1] Gray, Jim, et al. "The recovery manager of the System R database manager." ACM Computing Surveys (CSUR) 13.2 (1981): 223-242.](http://courses.cs.washington.edu/courses/cse550/09au/papers/CSE550.GrayTM.pdf)
- [[2] Mohan, C., et al. "ARIES: a transaction recovery method supporting fine-granularity locking and partial rollbacks using write-ahead logging." ACM Transactions on Database Systems (TODS) 17.1 (1992): 94-162.](https://cs.stanford.edu/people/chrismre/cs345/rl/aries.pdf)
- [[3] Coburn, Joel, et al. "From ARIES to MARS: Transaction support for next-generation, solid-state drives." Proceedings of the twenty-fourth ACM symposium on operating systems principles. ACM, 2013.](https://cseweb.ucsd.edu/~swanson/papers/SOSP2013-MARS.pdf)
- [[4] Arulraj, Joy, Matthew Perron, and Andrew Pavlo. "Write-behind logging." Proceedings of the VLDB Endowment 10.4 (2016): 337-348.](http://www.vldb.org/pvldb/vol10/p337-arulraj.pdf)
- [5] Garcia-Molina, Hector. Database systems: the complete book. Pearson Education India, 2008.
- [[6] Zheng, Wenting, et al. "Fast Databases with Fast Durability and Recovery Through Multicore Parallelism." OSDI. Vol. 14. 2014.](https://15721.courses.cs.cmu.edu/spring2018/papers/12-logging/zheng-osdi14.pdf)
- [7] http://catkang.github.io/2018/08/31/isolation-level.html
- [8] http://catkang.github.io/2018/09/19/concurrency-control.html









