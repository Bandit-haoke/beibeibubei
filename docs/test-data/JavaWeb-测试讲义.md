# JavaWeb 开发核心知识讲义

## 第一章 Spring Boot

### 1.1 自动装配原理

Spring Boot 自动装配的核心是 `@SpringBootApplication` 注解，它由三个注解组合而成：`@SpringBootConfiguration`、`@ComponentScan` 和 `@EnableAutoConfiguration`。

`@EnableAutoConfiguration` 通过 `@Import(AutoConfigurationImportSelector.class)` 导入自动配置类。`AutoConfigurationImportSelector` 会读取 `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` 文件中登记的所有自动配置类全限定名（Spring Boot 2.7 之前是 `spring.factories`）。

这些自动配置类通过条件注解按需生效，常用的条件注解包括：

- `@ConditionalOnClass`：类路径下存在指定类时才生效
- `@ConditionalOnMissingBean`：容器中不存在指定 Bean 时才生效
- `@ConditionalOnProperty`：配置文件中存在指定属性且值匹配时才生效
- `@ConditionalOnWebApplication`：当前是 Web 应用时才生效

自动装配的执行顺序是：先加载用户自己的 `@Bean` 定义，再处理自动配置类。因此用户自定义的 Bean 总是优先于自动配置的 Bean，这也是为什么重写自动配置只需要自己声明一个同类型 Bean。

### 1.2 Starter 机制

Starter 是一个空的 Maven 依赖，它的作用是聚合一组相关的依赖，让使用者只需要引入一个坐标。例如 `spring-boot-starter-web` 内部聚合了 `spring-webmvc`、`spring-web`、`tomcat-embed-core`、`jackson-databind` 等。

自定义 Starter 的规范做法是拆成两个模块：

1. `xxx-spring-boot-starter`：只放依赖声明，不放代码
2. `xxx-spring-boot-autoconfigure`：放自动配置类和 `AutoConfiguration.imports` 文件

### 1.3 配置文件与 Profile

Spring Boot 支持 `application.yml`、`application-dev.yml`、`application-prod.yml` 这类按 Profile 拆分的配置。通过 `spring.profiles.active` 指定激活哪个。

配置加载优先级从高到低大致是：命令行参数 > 环境变量 > `application-{profile}.yml` > `application.yml`。同名属性后加载的覆盖先加载的。

## 第二章 Spring Cloud

### 2.1 服务注册与发现

Nacos 是阿里开源的注册中心与配置中心。服务提供者启动时把自己的 IP、端口、服务名注册到 Nacos；消费者从 Nacos 拉取服务列表并缓存在本地，默认每 10 秒更新一次。

Nacos 的健康检查分为两种：临时实例使用心跳机制（客户端每 5 秒上报一次），非临时实例由 Nacos 主动探测。

### 2.2 网关 Gateway

Spring Cloud Gateway 基于 WebFlux 和 Reactor Netty，是非阻塞的。核心概念有三个：

- Route：路由，由 id、目标 uri、断言集合、过滤器集合组成
- Predicate：断言，匹配则路由生效，常用 Path、Method、Header、Query
- Filter：过滤器，分为 GatewayFilter（作用于单个路由）和 GlobalFilter（作用于所有路由）

Gateway 的三大核心组件里，断言决定「请求是否符合条件」，过滤器决定「请求和响应怎么被加工」。

### 2.3 熔断与限流

Sentinel 是阿里开源的流量控制组件，核心概念是资源和规则。资源可以是任意代码片段或接口，规则包括流控规则、熔断降级规则、系统保护规则、热点参数规则。

Sentinel 的熔断降级策略有三种：慢调用比例、异常比例、异常数。当单位统计时长内的指标超过阈值，就会触发熔断，熔断时长内请求快速失败，之后进入半开状态试探恢复。

## 第三章 Redis

### 3.1 五大数据类型

Redis 支持 String、Hash、List、Set、ZSet 五种基本数据类型，以及 Bitmap、HyperLogLog、GEO、Stream 等扩展类型。

- String：最基础的类型，可以存字符串、整数、浮点数，底层是 SDS（简单动态字符串）
- Hash：键值对集合，适合存对象，底层在元素少时用 ziplist，多时用 hashtable
- List：双向链表，底层是 quicklist，可以用作消息队列
- Set：无序不重复集合，底层是 intset 或 hashtable
- ZSet：有序集合，每个元素带 score，底层是 ziplist 或 skiplist

### 3.2 持久化机制 RDB 与 AOF

RDB 是快照持久化，把某一时刻的内存数据全量写入磁盘，文件紧凑、恢复快，但可能丢失最后一次快照之后的数据。触发方式有 save、bgsave 和配置的自动触发规则。

AOF 是追加日志持久化，记录每一条写命令。AOF 有三种刷盘策略：always（每条命令都刷盘，最安全最慢）、everysec（每秒刷盘，默认，最多丢 1 秒数据）、no（交给操作系统决定）。

Redis 4.0 引入了混合持久化，AOF 重写时先写一份 RDB 格式的全量数据，再追加增量命令，兼顾恢复速度和数据安全。

### 3.3 缓存穿透、击穿、雪崩

缓存穿透：查询一个数据库里也不存在的数据，导致每次请求都打到数据库。解决方案有两种，一是缓存空值并设置较短的过期时间，二是使用布隆过滤器提前拦截不存在的 key。

缓存击穿：某一个热点 key 在失效的瞬间，大量并发请求同时穿透到数据库。注意这里强调的是单个热点 key，不是大批 key。解决方案有两种，一是互斥锁，只让一个线程去查数据库并重建缓存，其他线程等待；二是逻辑过期，不给 key 设置真实过期时间，而是在 value 里存一个逻辑过期时间，发现过期后异步重建缓存。

缓存雪崩：大量 key 在同一时刻集中过期，或者 Redis 服务本身宕机，导致所有请求都打到数据库。解决方案有三种，一是给过期时间加随机值打散，二是搭建 Redis 高可用集群避免单点故障，三是使用多级缓存（本地缓存加 Redis），并在服务端做限流降级兜底。

三者的关键区别：穿透是查不存在的数据，击穿是单个热点 key 失效，雪崩是大批 key 同时失效或者服务不可用。

### 3.4 分布式锁

基于 Redis 实现分布式锁的基本命令是 `SET key value NX EX seconds`，必须把加锁和设置过期时间合并成一条原子命令，否则可能出现加锁成功但还没来得及设置过期时间就宕机的死锁。

释放锁必须校验持有者，不能直接 `DEL`，否则可能删掉别人的锁。正确做法是用 Lua 脚本保证「判断 value 相等」和「删除 key」的原子性。

生产环境更推荐 Redisson，它提供了看门狗机制自动续期，还实现了可重入锁、读写锁、信号量等。

## 第四章 MyBatis 与 MySQL

### 4.1 MyBatis 的核心组件

MyBatis 的四大核心对象是 SqlSessionFactory、SqlSession、Executor、MappedStatement。SqlSessionFactory 是单例的，由 SqlSessionFactoryBuilder 读取配置文件构建。SqlSession 是非线程安全的，每次请求都要新建。

`#{}` 是预编译占位符，会生成 `?` 并由 JDBC 设置参数，能防 SQL 注入；`${}` 是字符串拼接，直接替换进 SQL，有注入风险，只应该用在表名、排序字段这类无法预编译的场景，并且必须做白名单校验。

### 4.2 索引与执行计划

MySQL 的 InnoDB 使用 B+ 树作为索引结构。B+ 树的特点是只有叶子节点存数据，非叶子节点只存索引键，因此树更矮，磁盘 IO 次数更少；叶子节点之间用双向链表连接，天然支持范围查询。

聚簇索引的叶子节点存放完整行数据，一张表只能有一个聚簇索引（通常是主键）。二级索引的叶子节点存放主键值，因此通过二级索引查询非索引列需要「回表」。

最左前缀原则：联合索引 `(a, b, c)` 能支持 `a`、`a,b`、`a,b,c` 的查询条件，但跳过 `a` 直接查 `b` 用不上索引。

用 `EXPLAIN` 分析执行计划时重点关注：type（至少要 range，最好 ref 或 const，出现 ALL 是全表扫描）、key（实际使用的索引）、rows（预估扫描行数）、Extra（出现 Using filesort 或 Using temporary 说明需要优化）。

### 4.3 事务隔离级别

MySQL 的 InnoDB 支持四种隔离级别：

- READ UNCOMMITTED：可能脏读
- READ COMMITTED：解决脏读，可能不可重复读
- REPEATABLE READ：MySQL 默认级别，解决不可重复读，配合间隙锁基本解决幻读
- SERIALIZABLE：串行执行，最安全但并发最差

MVCC 是通过 undo log 版本链和 ReadView 实现的。RC 级别下每次 SELECT 都生成新的 ReadView，RR 级别下只在第一次 SELECT 时生成 ReadView 并复用。
