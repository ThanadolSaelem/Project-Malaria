// ct-----------------------------------------
// @file      : matcher.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/01/24 21:00
// -------------------------------------------
// CT日志监听SDK - 高性能域名匹配器
// ============================================

package ct

import (
	"fmt"
	"hash/fnv"
	"strings"
	"sync"
	"time"

	"github.com/Autumn-27/ScopeSentry/internal/utils/ct/models"
	"github.com/Autumn-27/ScopeSentry/internal/utils/ct/types"
	"golang.org/x/net/publicsuffix"
)

// DomainMatcher 高性能域名匹配器
type DomainMatcher struct {
	config      *types.DomainMatcherConfig
	trieRoot    *models.DomainTrieNode
	bloomFilter *BloomFilter
	lruCache    *LRUCache
	domains     map[string]*models.Domain
	mu          sync.RWMutex

	// 统计信息
	stats struct {
		totalMatches int64
		cacheHits    int64
		cacheMisses  int64
		bloomHits    int64
		bloomMisses  int64
		trieHits     int64
		trieMisses   int64
	}
}

// NewDomainMatcher 创建新的域名匹配器
func NewDomainMatcher(config *types.DomainMatcherConfig) *DomainMatcher {
	dm := &DomainMatcher{
		config:   config,
		trieRoot: models.NewDomainTrieNode(),
		domains:  make(map[string]*models.Domain),
	}

	// 初始化布隆过滤器
	if config.EnableBloomFilter {
		dm.bloomFilter = NewBloomFilter(config.BloomFilterSize, config.BloomFilterHash)
	}

	// 初始化LRU缓存
	if config.EnableLRUCache {
		dm.lruCache = NewLRUCache(config.LRUCacheSize)
	}

	return dm
}

// AddDomain 添加域名到匹配器
func (dm *DomainMatcher) AddDomain(domain string) error {
	dm.mu.Lock()
	defer dm.mu.Unlock()

	domain = dm.normalizeDomain(domain)
	if domain == "" {
		return fmt.Errorf("无效域名: %s", domain)
	}

	// 检查是否已存在
	if _, exists := dm.domains[domain]; exists {
		return nil
	}

	// 创建域名对象
	domainObj := models.NewDomain(domain)

	// 添加到域名映射
	dm.domains[domain] = domainObj

	// 添加到Trie树
	dm.addToTrie(domain, domainObj)

	// 添加到布隆过滤器
	if dm.bloomFilter != nil {
		dm.bloomFilter.Add(domain)
	}

	return nil
}

// RemoveDomain 从匹配器中移除域名
func (dm *DomainMatcher) RemoveDomain(domain string) error {
	dm.mu.Lock()
	defer dm.mu.Unlock()

	domain = dm.normalizeDomain(domain)
	if domain == "" {
		return nil
	}

	// 从域名映射中移除
	delete(dm.domains, domain)

	// 从Trie树中移除
	dm.removeFromTrie(domain)

	// 重新初始化布隆过滤器（简化实现）
	if dm.bloomFilter != nil {
		dm.rebuildBloomFilter()
	}

	// 清理LRU缓存
	if dm.lruCache != nil {
		dm.lruCache.Clear()
	}

	return nil
}

// HasDomain 检查是否包含指定域名
func (dm *DomainMatcher) HasDomain(domain string) bool {
	dm.mu.RLock()
	defer dm.mu.RUnlock()

	domain = dm.normalizeDomain(domain)
	_, exists := dm.domains[domain]
	return exists
}

// GetAllDomains 获取所有域名
func (dm *DomainMatcher) GetAllDomains() []string {
	dm.mu.RLock()
	defer dm.mu.RUnlock()

	domains := make([]string, 0, len(dm.domains))
	for domain := range dm.domains {
		domains = append(domains, domain)
	}
	return domains
}

// MatchSubdomains 匹配子域名（核心方法）
func (dm *DomainMatcher) MatchSubdomains(domains []string) []*models.DomainMatch {
	dm.mu.RLock()
	defer dm.mu.RUnlock()

	var matches []*models.DomainMatch

	for _, domain := range domains {
		domain = dm.normalizeDomain(domain)
		if domain == "" {
			continue
		}

		// 提取根域名（输入的域名可能是子域名，我们匹配根域名）
		rootDomain := extractRootDomain(domain)
		if rootDomain == "" {
			continue
		}

		// 第一层过滤：布隆过滤器快速检查
		if dm.bloomFilter != nil {
			if !dm.bloomFilter.Contains(rootDomain) {
				dm.stats.bloomMisses++
				continue
			}
			dm.stats.bloomHits++
		}

		// 第二层过滤：LRU缓存检查
		if dm.lruCache != nil {
			if _, found := dm.lruCache.Get(domain); found {
				dm.stats.cacheHits++
				continue
			}
			dm.stats.cacheMisses++
		}

		// 第三层过滤：Trie树精确匹配
		if match := dm.matchInTrie(rootDomain); match != nil {
			// 更新匹配结果中的子域名信息
			match.Subdomain = domain
			dm.stats.trieHits++
			dm.stats.totalMatches++

			matches = append(matches, match)

			// 添加到缓存
			if dm.lruCache != nil {
				dm.lruCache.Put(domain, match)
			}
		} else {
			dm.stats.trieMisses++
		}
	}

	return matches
}

// IsSubdomainOf 判断是否为指定域名的子域名
func (dm *DomainMatcher) IsSubdomainOf(subdomain, rootDomain string) bool {
	subdomain = dm.normalizeDomain(subdomain)
	rootDomain = dm.normalizeDomain(rootDomain)

	if subdomain == "" || rootDomain == "" {
		return false
	}

	// 完全匹配
	if subdomain == rootDomain {
		return false
	}

	// 检查是否以根域名结尾
	if !strings.HasSuffix(subdomain, "."+rootDomain) {
		return false
	}

	// 验证子域名格式
	subParts := strings.Split(subdomain, ".")
	rootParts := strings.Split(rootDomain, ".")

	// 子域名至少要比根域名多一个标签
	return len(subParts) > len(rootParts)
}

// GetStats 获取统计信息
func (dm *DomainMatcher) GetStats() *models.DomainMatcherStats {
	dm.mu.RLock()
	defer dm.mu.RUnlock()

	stats := &models.DomainMatcherStats{
		DomainStats: models.DomainStats{
			TotalDomains:    int64(len(dm.domains)),
			WildcardDomains: 0,
		},
	}

	// 计算通配符域名数
	for _, domain := range dm.domains {
		if domain.IsWildcard {
			stats.WildcardDomains++
		}
	}

	// 布隆过滤器统计
	if dm.bloomFilter != nil {
		stats.BloomFilterStats = models.BloomFilterStats{
			Size:      dm.bloomFilter.size,
			HashCount: dm.bloomFilter.hashCount,
			ItemCount: dm.bloomFilter.itemCount,
		}
	}

	// Trie树统计
	stats.TrieStats = dm.getTrieStats()

	// 缓存统计
	if dm.lruCache != nil {
		stats.CacheStats = models.CacheStats{
			Size:      dm.lruCache.capacity,
			ItemCount: len(dm.lruCache.items),
			HitCount:  dm.stats.cacheHits,
			MissCount: dm.stats.cacheMisses,
		}
		if dm.stats.cacheHits+dm.stats.cacheMisses > 0 {
			stats.CacheStats.HitRate = float64(dm.stats.cacheHits) / float64(dm.stats.cacheHits+dm.stats.cacheMisses)
		}
	}

	return stats
}

// Clear 清空所有域名
func (dm *DomainMatcher) Clear() error {
	dm.mu.Lock()
	defer dm.mu.Unlock()

	dm.domains = make(map[string]*models.Domain)
	dm.trieRoot = models.NewDomainTrieNode()

	if dm.bloomFilter != nil {
		dm.bloomFilter.Clear()
	}

	if dm.lruCache != nil {
		dm.lruCache.Clear()
	}

	// 重置统计信息
	dm.stats = struct {
		totalMatches int64
		cacheHits    int64
		cacheMisses  int64
		bloomHits    int64
		bloomMisses  int64
		trieHits     int64
		trieMisses   int64
	}{}

	return nil
}

// 私有方法

// normalizeDomain 标准化域名
func (dm *DomainMatcher) normalizeDomain(domain string) string {
	return models.NormalizeDomain(domain, dm.config.CaseSensitive)
}

// addToTrie 添加到Trie树
func (dm *DomainMatcher) addToTrie(domain string, domainObj *models.Domain) {
	node := dm.trieRoot
	runes := []rune(domain)

	for _, r := range runes {
		if node.Children[r] == nil {
			node.Children[r] = models.NewDomainTrieNode()
		}
		node = node.Children[r]
	}

	node.IsEnd = true
	node.Domain = domain
	node.AddedAt = time.Now()
	node.DomainObj = domainObj
}

// removeFromTrie 从Trie树中移除
func (dm *DomainMatcher) removeFromTrie(domain string) {
	// 简化实现：重建整个Trie树
	dm.rebuildTrie()
}

// rebuildTrie 重建Trie树
func (dm *DomainMatcher) rebuildTrie() {
	dm.trieRoot = models.NewDomainTrieNode()
	for domain, domainObj := range dm.domains {
		dm.addToTrie(domain, domainObj)
	}
}

// rebuildBloomFilter 重建布隆过滤器
func (dm *DomainMatcher) rebuildBloomFilter() {
	if dm.bloomFilter == nil {
		return
	}

	dm.bloomFilter.Clear()
	for domain := range dm.domains {
		dm.bloomFilter.Add(domain)
	}
}

// matchInTrie 在Trie树中匹配根域名
func (dm *DomainMatcher) matchInTrie(rootDomain string) *models.DomainMatch {
	// 在Trie树中查找根域名
	if node := dm.searchTrie(rootDomain); node != nil && node.IsEnd {
		node.HitCount++
		return &models.DomainMatch{
			Subdomain:  "", // 将在调用处设置
			RootDomain: rootDomain,
			MatchedAt:  time.Now(),
			MatchType:  "root_domain",
			Confidence: 1.0,
			HitCount:   node.HitCount,
		}
	}

	return nil
}

// searchTrie 在Trie树中搜索
func (dm *DomainMatcher) searchTrie(domain string) *models.DomainTrieNode {
	node := dm.trieRoot
	runes := []rune(domain)

	for _, r := range runes {
		if node.Children[r] == nil {
			return nil
		}
		node = node.Children[r]
	}

	return node
}

// getTrieStats 获取Trie树统计信息
func (dm *DomainMatcher) getTrieStats() models.TrieStats {
	stats := models.TrieStats{}
	dm.traverseTrie(dm.trieRoot, 0, &stats)
	return stats
}

// traverseTrie 遍历Trie树统计信息
func (dm *DomainMatcher) traverseTrie(node *models.DomainTrieNode, depth int, stats *models.TrieStats) {
	stats.NodeCount++

	if depth > stats.MaxDepth {
		stats.MaxDepth = depth
	}

	if node.IsEnd {
		stats.DomainCount++
		stats.TotalHitCount += node.HitCount
	}

	for _, child := range node.Children {
		dm.traverseTrie(child, depth+1, stats)
	}
}

// BloomFilter 简易布隆过滤器实现
type BloomFilter struct {
	bitset    []bool
	hashes    []uint
	size      uint
	hashCount uint
	itemCount uint64
}

func NewBloomFilter(size, hashCount uint) *BloomFilter {
	return &BloomFilter{
		bitset:    make([]bool, size),
		hashes:    make([]uint, hashCount),
		size:      size,
		hashCount: hashCount,
	}
}

func (bf *BloomFilter) Add(item string) {
	for i := uint(0); i < bf.hashCount; i++ {
		hash := bf.hash(item, i)
		bf.bitset[hash%bf.size] = true
	}
	bf.itemCount++
}

func (bf *BloomFilter) Contains(item string) bool {
	for i := uint(0); i < bf.hashCount; i++ {
		hash := bf.hash(item, i)
		if !bf.bitset[hash%bf.size] {
			return false
		}
	}
	return true
}

func (bf *BloomFilter) Clear() {
	bf.bitset = make([]bool, bf.size)
	bf.itemCount = 0
}

// hash 使用双重hash技术生成多个独立的hash值
func (bf *BloomFilter) hash(item string, seed uint) uint {
	// 使用FNV-1a作为基础hash
	h1 := fnv.New32a()
	h1.Write([]byte(item))
	hash1 := uint64(h1.Sum32())

	// 使用第二个不同的hash函数
	h2 := fnv.New32()
	h2.Write([]byte(item))
	hash2 := uint64(h2.Sum32())

	// 使用双重hash技术: hash_i = hash1 + i * hash2
	// 这样可以生成多个独立的hash值
	hash := hash1 + uint64(seed)*hash2
	return uint(hash % uint64(bf.size))
}

// extractRootDomain 提取域名的根域名（注册域名）
// 例如: www.example.com -> example.com, sub.example.co.uk -> example.co.uk
func extractRootDomain(domain string) string {
	domain = strings.ToLower(strings.TrimSpace(domain))
	if domain == "" {
		return ""
	}

	// 使用publicsuffix库获取有效的后缀
	suffix, icann := publicsuffix.PublicSuffix(domain)
	if suffix == "" || !icann {
		// 如果无法确定后缀，返回最后两级作为备选
		parts := strings.Split(domain, ".")
		if len(parts) >= 2 {
			return strings.Join(parts[len(parts)-2:], ".")
		}
		return domain
	}

	// 获取根域名（注册域名）
	root, err := publicsuffix.EffectiveTLDPlusOne(domain)
	if err != nil {
		// 如果出错，返回最后两级作为备选
		parts := strings.Split(domain, ".")
		if len(parts) >= 2 {
			return strings.Join(parts[len(parts)-2:], ".")
		}
		return domain
	}

	return root
}

// LRUCache 简易LRU缓存实现
type LRUCache struct {
	capacity int
	items    map[string]interface{}
	keys     []string
}

func NewLRUCache(capacity int) *LRUCache {
	return &LRUCache{
		capacity: capacity,
		items:    make(map[string]interface{}),
		keys:     make([]string, 0, capacity),
	}
}

func (c *LRUCache) Get(key string) (interface{}, bool) {
	if value, exists := c.items[key]; exists {
		// 移动到末尾（最近使用）
		c.moveToEnd(key)
		return value, true
	}
	return nil, false
}

func (c *LRUCache) Put(key string, value interface{}) {
	if _, exists := c.items[key]; exists {
		c.items[key] = value
		c.moveToEnd(key)
		return
	}

	// 检查容量
	if len(c.items) >= c.capacity {
		// 移除最少使用的
		oldest := c.keys[0]
		delete(c.items, oldest)
		c.keys = c.keys[1:]
	}

	c.items[key] = value
	c.keys = append(c.keys, key)
}

func (c *LRUCache) Clear() {
	c.items = make(map[string]interface{})
	c.keys = c.keys[:0]
}

func (c *LRUCache) moveToEnd(key string) {
	for i, k := range c.keys {
		if k == key {
			c.keys = append(c.keys[:i], c.keys[i+1:]...)
			c.keys = append(c.keys, key)
			break
		}
	}
}
