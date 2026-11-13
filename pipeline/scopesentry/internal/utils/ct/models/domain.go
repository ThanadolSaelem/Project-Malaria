// ct/models-----------------------------------
// @file      : domain.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/01/24 21:00
// -------------------------------------------
// CT日志监听SDK - 域名相关模型
// ============================================

package models

import (
	"fmt"
	"strings"
	"time"
	"unicode"
)

// Domain 域名对象
type Domain struct {
	Name       string    `json:"name"`        // 域名名称
	IsWildcard bool      `json:"is_wildcard"` // 是否为通配符域名
	RootDomain string    `json:"root_domain"` // 根域名
	Subdomains []string  `json:"subdomains"`  // 子域名列表（仅用于序列化）
	AddedAt    time.Time `json:"added_at"`    // 添加时间
	LastSeen   time.Time `json:"last_seen"`   // 最后发现时间
	CertCount  int64     `json:"cert_count"`  // 关联证书数量
	HitCount   int64     `json:"hit_count"`   // 命中次数
}

// NewDomain 创建新的域名对象
func NewDomain(name string) *Domain {
	now := time.Now()
	return &Domain{
		Name:     name,
		AddedAt:  now,
		LastSeen: now,
	}
}

// IsSubdomainOf 判断是否为指定域名的子域名
func (d *Domain) IsSubdomainOf(rootDomain string) bool {
	if d.Name == rootDomain {
		return false // 相同域名不算子域名
	}

	// 检查是否以根域名结尾
	if !strings.HasSuffix(d.Name, "."+rootDomain) {
		return false
	}

	// 验证子域名格式
	subParts := strings.Split(d.Name, ".")
	rootParts := strings.Split(rootDomain, ".")

	// 子域名至少要比根域名多一个标签
	return len(subParts) > len(rootParts)
}

// UpdateLastSeen 更新最后发现时间
func (d *Domain) UpdateLastSeen() {
	d.LastSeen = time.Now()
	d.HitCount++
}

// IncrementCertCount 增加证书计数
func (d *Domain) IncrementCertCount() {
	d.CertCount++
}

// DomainMatch 域名匹配结果
type DomainMatch struct {
	Subdomain   string    `json:"subdomain"`   // 发现的子域名
	RootDomain  string    `json:"root_domain"` // 匹配的根域名
	Certificate *CertInfo `json:"certificate"` // 证书信息
	MatchedAt   time.Time `json:"matched_at"`  // 匹配时间
	MatchType   string    `json:"match_type"`  // 匹配类型 (exact/prefix/suffix)
	Confidence  float64   `json:"confidence"`  // 匹配置信度 0-1
	HitCount    int64     `json:"hit_count"`   // 命中次数
}

// NewDomainMatch 创建新的域名匹配结果
func NewDomainMatch(subdomain, rootDomain string, cert *CertInfo) *DomainMatch {
	return &DomainMatch{
		Subdomain:   subdomain,
		RootDomain:  rootDomain,
		Certificate: cert,
		MatchedAt:   time.Now(),
		MatchType:   "prefix",
		Confidence:  0.9,
		HitCount:    1,
	}
}

// DomainTrieNode Trie树节点（用于高效域名匹配）
type DomainTrieNode struct {
	Children  map[rune]*DomainTrieNode `json:"-"`         // 子节点（不序列化）
	IsEnd     bool                     `json:"is_end"`    // 是否为结束节点
	Domain    string                   `json:"domain"`    // 完整域名
	AddedAt   time.Time                `json:"added_at"`  // 添加时间
	HitCount  int64                    `json:"hit_count"` // 命中次数
	DomainObj *Domain                  `json:"-"`         // 域名对象（不序列化）
}

// NewDomainTrieNode 创建新的Trie节点
func NewDomainTrieNode() *DomainTrieNode {
	return &DomainTrieNode{
		Children: make(map[rune]*DomainTrieNode),
		IsEnd:    false,
	}
}

// DomainStats 域名统计信息
type DomainStats struct {
	TotalDomains      int64   `json:"total_domains"`      // 总域名数
	UniqueSubdomains  int64   `json:"unique_subdomains"`  // 唯一子域名数
	NewDiscoveries    int64   `json:"new_discoveries"`    // 新发现数
	RootDomainCount   int64   `json:"root_domain_count"`  // 根域名数量
	WildcardDomains   int64   `json:"wildcard_domains"`   // 通配符域名数
	TotalMatches      int64   `json:"total_matches"`      // 总匹配次数
	AverageConfidence float64 `json:"average_confidence"` // 平均匹配置信度
	CacheHitRate      float64 `json:"cache_hit_rate"`     // 缓存命中率
}

// DomainMatcherStats 域名匹配器统计信息
type DomainMatcherStats struct {
	DomainStats
	BloomFilterStats BloomFilterStats `json:"bloom_filter_stats"` // 布隆过滤器统计
	TrieStats        TrieStats        `json:"trie_stats"`         // Trie树统计
	CacheStats       CacheStats       `json:"cache_stats"`        // 缓存统计
}

// BloomFilterStats 布隆过滤器统计信息
type BloomFilterStats struct {
	Size              uint    `json:"size"`                // 过滤器大小
	HashCount         uint    `json:"hash_count"`          // 哈希函数数量
	ItemCount         uint64  `json:"item_count"`          // 项目数量
	FalsePositiveRate float64 `json:"false_positive_rate"` // 假阳性率
}

// TrieStats Trie树统计信息
type TrieStats struct {
	NodeCount     int64 `json:"node_count"`      // 节点数量
	MaxDepth      int   `json:"max_depth"`       // 最大深度
	DomainCount   int64 `json:"domain_count"`    // 域名数量
	TotalHitCount int64 `json:"total_hit_count"` // 总命中次数
}

// CacheStats 缓存统计信息
type CacheStats struct {
	Size      int     `json:"size"`       // 缓存大小
	ItemCount int     `json:"item_count"` // 项目数量
	HitCount  int64   `json:"hit_count"`  // 命中次数
	MissCount int64   `json:"miss_count"` // 缺失次数
	HitRate   float64 `json:"hit_rate"`   // 命中率
}

// DomainMatcherInterface 域名匹配器接口
type DomainMatcherInterface interface {
	// 域名管理
	AddDomain(domain string) error
	RemoveDomain(domain string) error
	HasDomain(domain string) bool
	GetAllDomains() []string

	// 匹配功能
	MatchSubdomains(domains []string) []*DomainMatch
	IsSubdomainOf(subdomain, rootDomain string) bool

	// 统计信息
	GetStats() *DomainMatcherStats
	Clear() error
}

// NormalizeDomain 标准化域名
func NormalizeDomain(domain string, caseSensitive bool) string {
	if domain == "" {
		return ""
	}

	domain = strings.TrimSpace(domain)

	if !caseSensitive {
		domain = strings.ToLower(domain)
	}

	// 移除末尾的点
	domain = strings.TrimSuffix(domain, ".")

	return domain
}

// ValidateDomain 验证域名格式
func ValidateDomain(domain string, maxLength int) error {
	if domain == "" {
		return fmt.Errorf("域名不能为空")
	}

	if len(domain) > maxLength {
		return fmt.Errorf("域名长度超过最大限制 %d", maxLength)
	}

	// 验证字符
	for _, r := range domain {
		if !unicode.IsLetter(r) && !unicode.IsDigit(r) && r != '-' && r != '.' && r != '*' {
			return fmt.Errorf("域名包含无效字符: %c", r)
		}
	}

	return nil
}
