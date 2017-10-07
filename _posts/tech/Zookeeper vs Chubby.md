# Zookeeper vs Chubby



上一篇博客[Chubby的锁服务](http://catkang.github.io/2017/09/29/chubby.html)中已经对[Chubby](https://static.googleusercontent.com/media/research.google.com/en//archive/chubby-osdi06.pdf)的设计和实现做了比较详细的实现，但由于其闭源身份，工程中接触比较多的还是它的一个非常类似的开源实现[Zookeeper](https://www.usenix.org/legacy/event/usenix10/tech/full_papers/Hunt.pdf)。Zookeeper作为后起之秀，应该对Chubby有很多的借鉴，他们有众多的相似之处，比如都可以提供分布式锁的功能；都提供类似于UNIX文件系统的数据组织方式；都提供了事件通知机制Event或Watcher；都在普通节点的基础上提供了临时节点来满足服务存活发现的功能；都以集群的方式提供服务；都通过选举产生Master并在集群间以Quorum的方式副本数据。但他们并不完全相同，并且Zookeeper还拥有后发优势，本文将重点介绍他们之间的区别，并试着分析这些区别的原因以和结果。



## **区别根源**

我们认为，一个设计良好的系统应该是围绕并为其设计目标服务的，因此通过对Chubby及Zookeeper的目标比较或许能对其区别的本质略窥一二：

- **Chubby**：provide coarse-grained locking as well as reliable storage for a loosely-coupled distributed system.
- **Zookeeper**：provide a simple and high performance kernel for building more complex coordination primitives at the client.

可以看出，Chubby旗帜鲜明的表示自己是为分布式锁服务的，而Zookeeper则倾向于构造一个“Kernel”，而利用这个“Kernel”客户端可以自己实现众多更复杂的分布式协调机制。自然的，**Chubby倾向于提供更精准明确的操作来免除使用者的负担，Zookeeper则需要提供更通用，更原子的原材料，留更多的空白和自由给Client**。也正是因此，为了更适配到更广的场景范围，Zookeeper对**性能**的提出了更高的要求。



## **比较**

围绕上述思路，我们接下来从一致性、分布式锁的实现及使用、客户端Cache等方面来对比他们的不同。

#### **一致性**



#### **分布式锁**



#### **客户端Cache**



#### **其他**



## **总结**