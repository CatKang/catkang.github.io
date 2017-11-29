# Why raft never commits log entries from previous terms directly

熟悉Raft的读者都知道，算法中在Safty子问题中限制对之前term的log entry不能简单的通过收集大多数（Quorum）的方式进行提交。论文中也给出详细的例子说明违反这条限制可能会破坏算法的Machine Safety Property，即任何一个log位置只能有一个值被提交到状态机。如下图所示：

// Todo 图

简单的说，c过程中如果S1简单的通过判断大多数节点在index为2的位置的AppendEntry成功来commit值2，那么后续S5成为Leader后可能用自己的值3将其覆盖导致错误。因此Raft限制只能通过判断大多数的方式提交当前term的log entry，进而对之前的entry间接提交，如过程e所示。

> Raft never commits log entries from previous terms by count- ing replicas. Only log entries from the leader’s current term are committed by counting replicas; once an entry from the current term has been committed in this way, then all prior entries are committed indirectly because of the Log Matching Property.

那么导致这种问题的根本原因是什么？以及为什么增加这个限制后就可以解决问题呢？

Raft根本上讲也是(multi-)Paxos，可以认为是对Paxos加了限制而得到的更简单易懂的一致性算法，因此我们从Paxos出发来试着回答上面两个问题。



## **Paxos**

了解Paxos的读者知道为了算法的Liveness，单个Paxos实例允许接受不止一个propose，但要求只能接受一个value：

> P2. If a proposal with value v is chosen, then every higher-numbered pro- posal that is chosen has value v.

也就是说一个新的propose会先读取可能存在的之前propose的value，并用自己的更大的propose num进行重新提交。



## **Paxos to Multi-paxos** 

Paxos算法分为两个阶段，第一个阶段中，节点通过Propose及Promise过程得到大多数节点对自己propose num的认可；之后在第二个阶段中通过Accept请求广播自己的提案值，并且在收到大多数的Ack后进行Commit。那么当我们面对一连串提案而不是一个单独的提案的Multi-Paxos时，很自然的一个优化就是选择一个Coordinator，由这个Coordinator来发起所有提案的阶段二，即尝试提交值，从而将Paxos阶段一中的Propose及Promise过程省略。相当于每一次Propose及Promise的结果都是这个Coordinator获胜。

由于所有的value都是由这个Coordinator发起的，是不是就不存在上面说到的不同propose提交同一个值了呢？不是的，只是这种情况被减少到了重新选主后的Recovery过程，可以看出这样的Multi-paxos的选主过程其实就相当于Paxos中的阶段一。新的Coordinator可能会发现之前的Coordinator发起的值，但其无法判断这个值是不是已经被Commit，因为旧的Coordinator可能是在本地Commit并返回Client之后，通知其他节点Commit之前的空隙宕掉的。因此新的Coordinator安全的做法就是用自己的propose num重新发起并尝试提交这个value。对这个位置来讲相当于经历了一个完整的Paxos阶段一、阶段二过程。



## **Multi-paxos to Raft**

可以看出，Raft就是很典型的采取了这种有Coordinator模式的Multi-paxos。Coordinator在Raft中称为Leader，propose num就是term。自然地，Raft中新Leader也会发现旧Leader留下的log entry。因此正确的做法是新Leader用自己的term重新对这个entry进行提交，但由于Raft对限制，新Leader没有办法修改这个entry中记录的term，而任由这个entry存在而不修改却将其提交也是不行的，因为entry中过时的term可能会导致未来被其实比当前新Leader小的term的值覆盖，也就是文章开头提到的错误。因此Raft采取了非常巧妙的方式



## **回顾**



