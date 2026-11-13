// ct/types------------------------------------
// @file      : options.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/01/24 21:00
// -------------------------------------------
// CT日志监听SDK - 配置选项和参数定义
// ============================================

package types

import (
	"fmt"
	"time"

	"github.com/Autumn-27/ScopeSentry/internal/utils/ct/models"
)

// SDKOptions SDK配置选项
type SDKOptions struct {
	// CT日志服务器配置列表
	LogServers []*LogServerConfig `json:"log_servers"`

	// 初始关注的域名列表
	Domains []string `json:"domains"`

	// 域名匹配器配置
	DomainMatcher *DomainMatcherConfig `json:"domain_matcher"`

	// 性能配置
	Performance *PerformanceConfig `json:"performance"`

	// Redis配置（用于检查点存储）
	Redis *RedisConfig `json:"redis"`
}

// LogServerConfig CT日志服务器配置
type LogServerConfig struct {
	// 基本配置
	URL string `json:"url"` // CT日志URL (必需)

	// Scanner配置
	BatchSize     int `json:"batch_size"`     // 批量获取大小 (默认100)
	ParallelFetch int `json:"parallel_fetch"` // 并行获取数 (默认1)
	BufferSize    int `json:"buffer_size"`    // 缓冲区大小 (默认1000)

	// 网络配置
	Timeout    time.Duration `json:"timeout"`     // 请求超时 (默认30s)
	MaxRetries int           `json:"max_retries"` // 最大重试次数 (默认3)
}

// DomainMatcherConfig 域名匹配器配置
type DomainMatcherConfig struct {
	// 过滤器配置
	EnableBloomFilter bool `json:"enable_bloom_filter"` // 启用布隆过滤器 (默认true)
	BloomFilterSize   uint `json:"bloom_filter_size"`   // 布隆过滤器大小 (默认1000000)
	BloomFilterHash   uint `json:"bloom_filter_hash"`   // 哈希函数数量 (默认5)

	// 缓存配置
	EnableLRUCache bool `json:"enable_lru_cache"` // 启用LRU缓存 (默认true)
	LRUCacheSize   int  `json:"lru_cache_size"`   // LRU缓存大小 (默认10000)

	// 匹配配置
	CaseSensitive   bool `json:"case_sensitive"`    // 大小写敏感 (默认false)
	MaxDomainLength int  `json:"max_domain_length"` // 最大域名长度 (默认253)
}

// PerformanceConfig 性能配置
type PerformanceConfig struct {
	// 协程池配置
	MaxWorkers        int `json:"max_workers"`         // 最大工作协程数 (默认10)
	ChannelBufferSize int `json:"channel_buffer_size"` // 通道缓冲区大小 (默认100)

	// 处理配置
	ProcessingTimeout time.Duration `json:"processing_timeout"` // 单证书处理超时 (默认5s)
	BatchProcessSize  int           `json:"batch_process_size"` // 批量处理大小 (默认50)

	// 资源限制
	MaxMemoryUsage int64   `json:"max_memory_usage"` // 最大内存使用(MB) (默认512)
	MaxCPUUsage    float64 `json:"max_cpu_usage"`    // 最大CPU使用率 (默认0.8)
}

// RedisConfig Redis配置
type RedisConfig struct {

	// 键配置
	KeyPrefix string `json:"key_prefix"` // 键前缀 (默认"ct_watcher:")
}

// DefaultSDKOptions 获取默认SDK配置
func DefaultSDKOptions() *SDKOptions {
	return &SDKOptions{
		LogServers: []*LogServerConfig{
			{
				URL:           "https://ct.googleapis.com/logs/argon2023/",
				BatchSize:     100,
				ParallelFetch: 1,
				BufferSize:    1000,
				Timeout:       30 * time.Second,
				MaxRetries:    3,
			},
		},
		Domains: []string{},
		DomainMatcher: &DomainMatcherConfig{
			EnableBloomFilter: true,
			BloomFilterSize:   1000000,
			BloomFilterHash:   5,
			EnableLRUCache:    true,
			LRUCacheSize:      10000,
			CaseSensitive:     false,
			MaxDomainLength:   253,
		},
		Performance: &PerformanceConfig{
			MaxWorkers:        10,
			ChannelBufferSize: 100,
			ProcessingTimeout: 5 * time.Second,
			BatchProcessSize:  50,
			MaxMemoryUsage:    512,
			MaxCPUUsage:       0.8,
		},
		Redis: &RedisConfig{
			KeyPrefix: "ct_watcher:",
		},
	}
}

// Validate 验证配置
func (opts *SDKOptions) Validate() error {
	if len(opts.LogServers) == 0 {
		return &ValidationError{Field: "LogServers", Message: "至少需要配置一个CT日志服务器"}
	}

	for i, server := range opts.LogServers {
		if server.URL == "" {
			return &ValidationError{
				Field:   "LogServers",
				Index:   i,
				Message: "CT日志URL不能为空",
			}
		}

		if server.BatchSize <= 0 {
			server.BatchSize = 100
		}
		if server.ParallelFetch <= 0 {
			server.ParallelFetch = 1
		}
		if server.BufferSize <= 0 {
			server.BufferSize = 1000
		}
		if server.Timeout <= 0 {
			server.Timeout = 30 * time.Second
		}
		if server.MaxRetries < 0 {
			server.MaxRetries = 3
		}
	}

	// 验证域名匹配器配置
	if opts.DomainMatcher == nil {
		opts.DomainMatcher = &DomainMatcherConfig{
			EnableBloomFilter: true,
			BloomFilterSize:   1000000,
			BloomFilterHash:   5,
			EnableLRUCache:    true,
			LRUCacheSize:      10000,
			CaseSensitive:     false,
			MaxDomainLength:   253,
		}
	}

	// 验证性能配置
	if opts.Performance == nil {
		opts.Performance = &PerformanceConfig{
			MaxWorkers:        10,
			ChannelBufferSize: 100,
			ProcessingTimeout: 5 * time.Second,
			BatchProcessSize:  50,
			MaxMemoryUsage:    512,
			MaxCPUUsage:       0.8,
		}
	}

	// 验证Redis配置
	if opts.Redis == nil {
		opts.Redis = &RedisConfig{
			KeyPrefix: "ct_watcher:",
		}
	}

	return nil
}

// ValidationError 配置验证错误
type ValidationError struct {
	Field   string
	Index   int
	Message string
}

// Status SDK状态
type Status struct {
	// 运行状态
	IsRunning bool          `json:"is_running"` // 是否正在运行
	StartTime time.Time     `json:"start_time"` // 启动时间
	Uptime    time.Duration `json:"uptime"`     // 运行时间

	// 处理统计
	ProcessedCertificates int64 `json:"processed_certificates"` // 已处理证书总数
	DiscoveredSubdomains  int64 `json:"discovered_subdomains"`  // 发现的子域名总数
	ActiveWatchers        int   `json:"active_watchers"`        // 活跃的监听器数

	// 错误统计
	TotalErrors  int64    `json:"total_errors"`  // 总错误数
	RecentErrors []string `json:"recent_errors"` // 最近错误

	// 资源使用
	MemoryUsage    int64   `json:"memory_usage"`    // 内存使用量
	CPUUsage       float64 `json:"cpu_usage"`       // CPU使用率
	GoroutineCount int     `json:"goroutine_count"` // 协程数量

	// 监听器状态
	WatcherStatuses map[string]*models.LogStatus `json:"watcher_statuses"` // 各监听器状态
}

func (e *ValidationError) Error() string {
	if e.Index >= 0 {
		return fmt.Sprintf("配置验证失败 [%s[%d]]: %s", e.Field, e.Index, e.Message)
	}
	return fmt.Sprintf("配置验证失败 [%s]: %s", e.Field, e.Message)
}
