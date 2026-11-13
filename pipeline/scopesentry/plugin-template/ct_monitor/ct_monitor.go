// Package plugin plugin-------------------------------------
// @file      : ct_monitor.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2026/1/25 13:05
// -------------------------------------------
package plugin

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/Autumn-27/ScopeSentry/internal/utils/helper"

	"github.com/Autumn-27/ScopeSentry/internal/models"

	"github.com/Autumn-27/ScopeSentry/internal/utils/ct"
	ct_models "github.com/Autumn-27/ScopeSentry/internal/utils/ct/models"

	"github.com/Autumn-27/ScopeSentry/internal/options"
	"github.com/Autumn-27/ScopeSentry/internal/utils"
	"github.com/Autumn-27/ScopeSentry/internal/utils/ct/types"
	"go.mongodb.org/mongo-driver/bson"
)

func GetName() string {
	return "CT Monitor"
}

// Cycle 运行周期
func Cycle() string {
	return "1"
}

func Install() error {
	return nil
}

// 排除非关注域名
var blacklist = []string{
	"google.com",
}

// 排除包含字符串的域名
var subdomainBlacklist = []string{
	".prod.",
}
var CTSDK *ct.CTWatcherSDK
var OP options.PluginOption

// 已处理的子域名列表，用于去重
var (
	processedSubdomains = make(map[string]struct{})
	subdomainMu         sync.RWMutex
)

func Execute(op options.PluginOption) error {
	// 获取插件上下文
	ctx := utils.GetContext(op.PluginHash)

	// 监控日志配置
	opts := &types.SDKOptions{
		// CT日志服务器配置
		LogServers: []*types.LogServerConfig{
			{
				URL:           "https://ct.googleapis.com/logs/us1/argon2026h1/",
				BatchSize:     500,
				ParallelFetch: 10,
				BufferSize:    1000,
				Timeout:       30 * time.Second,
				MaxRetries:    3,
			},
			//{
			//	URL:           "https://ct.googleapis.com/logs/us1/argon2026h2/",
			//	BatchSize:     500,
			//	ParallelFetch: 10,
			//	BufferSize:    1000,
			//	Timeout:       30 * time.Second,
			//	MaxRetries:    3,
			//},
			//{
			//	URL:           "https://ct.googleapis.com/logs/us1/argon2027h1/",
			//	BatchSize:     500,
			//	ParallelFetch: 10,
			//	BufferSize:    1000,
			//	Timeout:       30 * time.Second,
			//	MaxRetries:    3,
			//},
			{
				URL:           "https://ct.googleapis.com/logs/eu1/xenon2026h1/",
				BatchSize:     500,
				ParallelFetch: 10,
				BufferSize:    1000,
				Timeout:       30 * time.Second,
				MaxRetries:    3,
			},
			//{
			//	URL:           "https://ct.googleapis.com/logs/eu1/xenon2026h2/",
			//	BatchSize:     500,
			//	ParallelFetch: 10,
			//	BufferSize:    1000,
			//	Timeout:       30 * time.Second,
			//	MaxRetries:    3,
			//},
			//{
			//	URL:           "https://ct.googleapis.com/logs/eu1/xenon2027h1/",
			//	BatchSize:     500,
			//	ParallelFetch: 10,
			//	BufferSize:    1000,
			//	Timeout:       30 * time.Second,
			//	MaxRetries:    3,
			//},
			//{
			//	URL:           "https://ct.cloudflare.com/logs/nimbus2026/",
			//	BatchSize:     500,
			//	ParallelFetch: 10,
			//	BufferSize:    1000,
			//	Timeout:       30 * time.Second,
			//	MaxRetries:    3,
			//},
			//{
			//	URL:           "https://ct.cloudflare.com/logs/nimbus2027/",
			//	BatchSize:     500,
			//	ParallelFetch: 10,
			//	BufferSize:    1000,
			//	Timeout:       30 * time.Second,
			//	MaxRetries:    3,
			//},
		},
		// 域名匹配器配置
		DomainMatcher: &types.DomainMatcherConfig{
			EnableBloomFilter: true,
			BloomFilterSize:   1000000,
			BloomFilterHash:   5,
			EnableLRUCache:    true,
			LRUCacheSize:      10000,
			CaseSensitive:     false,
			MaxDomainLength:   253,
		},
		// 性能配置
		Performance: &types.PerformanceConfig{
			MaxWorkers:        10,
			ChannelBufferSize: 100,
			ProcessingTimeout: 5 * time.Second,
			BatchProcessSize:  50,
		},
		// Redis配置
		Redis: &types.RedisConfig{
			KeyPrefix: "ct_watcher:",
		},
	}

	// 获取关注的域名，排除黑名单，只返回domain字段
	filter := bson.M{
		"domain": bson.M{
			"$nin": blacklist,
		},
	}
	var rootDomains []bson.M
	err := op.CommonRepo.FindField(ctx, "RootDomain", filter, 0, []string{"domain"}, &rootDomains)
	if err != nil {
		return err
	}

	// 将返回的所有domains转成字符串数组
	domains := make([]string, 0, len(rootDomains))
	for _, doc := range rootDomains {
		if domain, ok := doc["domain"].(string); ok {
			domains = append(domains, domain)
		}
	}
	// 设置关注的域名
	opts.Domains = domains

	// 创建SDK实例
	sdk, err := ct.NewCTWatcherSDK(opts)
	if err != nil {
		log.Fatalf("创建SDK失败: %v", err)
	}
	defer sdk.Close()

	CTSDK = sdk
	OP = op

	// 判断扫描模板是否创建
	taskTemplateId := ""
	ctTmp, err := op.TemplateService.List(context.Background(), 1, 20, "CT_Monitor")
	if err != nil {
		op.Log(fmt.Sprintf("Search Template error: %s", err.Error()), "e")
	}
	if ctTmp != nil {
		if len(ctTmp.List) == 0 {
			// 模板未创建 进行创建模板
			template := models.ScanTemplate{
				Name:         "CT_Monitor",
				AssetMapping: []string{"3a0d994a12305cb15a5cb7104d819623"}, // httpx
				Parameters: models.Parameters{
					AssetMapping: map[string]string{
						"3a0d994a12305cb15a5cb7104d819623": "-cdncheck false -screenshot true -tlsprobe false -st 10 -fr true -bh false -t 30",
					},
				},
				ParameterLists: models.Parameters{
					AssetMapping: map[string]string{
						"3a0d994a12305cb15a5cb7104d819623": "[{\"name\":\"cdncheck\",\"type\":\"bool\",\"defaultValue\":\"false\"},{\"name\":\"screenshot\",\"type\":\"bool\",\"defaultValue\":\"true\"},{\"name\":\"tlsprobe\",\"type\":\"bool\",\"defaultValue\":\"false\"},{\"name\":\"st\",\"type\":\"string\",\"defaultValue\":\"10\"},{\"name\":\"fr\",\"type\":\"bool\",\"defaultValue\":\"true\"},{\"name\":\"bh\",\"type\":\"bool\",\"defaultValue\":\"false\"},{\"name\":\"t\",\"type\":\"string\",\"defaultValue\":\"30\"}]",
					},
				},
			}
			templateID, err := op.TemplateService.Save(context.Background(), "", &template)
			if err != nil {
				op.Log(fmt.Sprintf("<UNK> Create Template error <UNK>: %s", err.Error()), "e")
				return err
			}
			taskTemplateId = templateID
		} else {
			taskTemplateId = ctTmp.List[0].ID
		}
	}

	// 注册子域名发现回调
	sdk.OnSubdomainFound(func(event ct_models.SubdomainEvent) {
		// 检查子域名是否已经处理过（使用读锁，支持并发读取）
		subdomainMu.RLock()
		_, exists := processedSubdomains[event.Subdomain]
		subdomainMu.RUnlock()

		if exists {
			// 已存在，跳过处理
			return
		}
		// 排除域名
		for _, domain := range subdomainBlacklist {
			if strings.Contains(event.Subdomain, domain) {
				return
			}
		}
		// 标记为已处理（使用写锁）
		subdomainMu.Lock()
		processedSubdomains[event.Subdomain] = struct{}{}
		subdomainMu.Unlock()

		// 发现子域名后 放进redis中（使用Set类型自动去重）
		subdomainKey := "ct_watcher:subdomains"
		err := op.CommonRepo.SAdd(ctx, subdomainKey, event.Subdomain)
		if err != nil {
			op.Log(fmt.Sprintf("[错误] 存储子域名到Redis失败: %s, 错误: %v", event.Subdomain, err), "e")
		}
		op.Log(fmt.Sprintf("[发现子域名] %s -> %s | 证书索引: %d | 时间: %s\n",
			fmt.Sprintf("<color value=\"#ff6b6b\" bold>%s</color>", event.RootDomain),
			fmt.Sprintf("<color value=\"#ff6b6b\" bold>%s</color>", event.Subdomain),
			event.Certificate.Index,
			event.DiscoveredAt.Format("2006-01-02 15:04:05")))
		// 发送通知
		notificationMsg := fmt.Sprintf("发现新的子域名: \n%v", event.Subdomain)
		op.Notification(notificationMsg)
	})

	// 注册错误回调
	sdk.OnError(func(err error, context map[string]interface{}) {
		errorType := "unknown"
		if ctxType, ok := context["error_type"]; ok {
			if et, ok := ctxType.(string); ok {
				errorType = et
			}
		}
		op.Log(fmt.Sprintf("[错误] 类型: %s | 消息: %v\n", errorType, err), "e")
	})

	// 启动SDK
	op.Log("启动CT日志监听器...")
	if err := sdk.Start(ctx); err != nil {
		log.Fatalf("启动SDK失败: %v", err)
		op.Log(fmt.Sprintf("启动SDK失败: %v", err), "e")
		return err
	}
	op.Log("CT监听器已启动，正在监听子域名发现...")
	// 启动状态监控协程
	go func() {
		ticker := time.NewTicker(10 * time.Minute)
		defer ticker.Stop()

		// 用于计算增量QPS的变量
		var lastProcessedCount int64 = 0
		var lastReportTime = time.Now()

		// 状态报告函数
		reportStatus := func() {
			currentTime := time.Now()
			status := sdk.GetStatus()
			stats := sdk.GetStats()

			// 计算总体平均QPS
			uptimeSeconds := status.Uptime.Seconds()
			avgQps := float64(0)
			if uptimeSeconds > 0 {
				avgQps = float64(status.ProcessedCertificates) / uptimeSeconds
			}

			// 计算增量QPS（最近30秒内的实际处理速度）
			timeDiff := currentTime.Sub(lastReportTime).Seconds()
			countDiff := status.ProcessedCertificates - lastProcessedCount
			incrementalQps := float64(0)
			if timeDiff > 0 {
				incrementalQps = float64(countDiff) / timeDiff
			}

			// 更新上一次的状态
			lastProcessedCount = status.ProcessedCertificates
			lastReportTime = currentTime

			// 构建状态报告日志
			var logContent string
			logContent += "\n=== 监听器状态报告 ===\n"
			logContent += fmt.Sprintf("运行时间: %v\n", status.Uptime)
			logContent += fmt.Sprintf("总处理证书数: %d\n", status.ProcessedCertificates)
			logContent += fmt.Sprintf("总发现子域名数: %d\n", status.DiscoveredSubdomains)
			logContent += fmt.Sprintf("平均QPS: %.2f certs/sec\n", avgQps)
			logContent += fmt.Sprintf("增量QPS: %.2f certs/sec (最近30秒)\n", incrementalQps)
			logContent += fmt.Sprintf("活跃监听器数: %d\n", status.ActiveWatchers)
			logContent += fmt.Sprintf("域名总数: %d\n", stats.TotalDomains)

			// 显示每个监听器的处理统计
			if len(status.WatcherStatuses) > 0 {
				totalWatcherProcessed := int64(0)
				for url, watcherStatus := range status.WatcherStatuses {
					logContent += fmt.Sprintf("\n监听器: %s\n", url)
					logContent += fmt.Sprintf("  状态: %s\n", watcherStatus.Status)
					logContent += fmt.Sprintf("  处理证书数: %d\n", watcherStatus.ProcessedCount)
					logContent += fmt.Sprintf("  最后索引: %d\n", watcherStatus.LastIndex)
					logContent += fmt.Sprintf("  错误次数: %d\n", watcherStatus.ErrorCount)
					totalWatcherProcessed += watcherStatus.ProcessedCount
				}
				logContent += fmt.Sprintf("\n监听器总处理证书数: %d\n", totalWatcherProcessed)
			}
			logContent += "========================\n\n"
			op.Log(logContent)
		}

		// 立即执行一次状态报告
		reportStatus()

		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				reportStatus()
			}
		}
	}()

	// 从redis中获取子域名进行创建任务
	go func() {
		ticker := time.NewTicker(1 * time.Hour)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				processSubdomains(ctx, op, taskTemplateId)
			}
		}
	}()
	// 等待上下文取消，监控结束
	<-ctx.Done()
	op.Log("CT监听器已停止")
	return nil
}

// processSubdomains 处理Redis中的子域名
func processSubdomains(ctx context.Context, op options.PluginOption, taskTemplateId string) {
	subdomainKey := "ct_watcher:subdomains"

	// 检查Set是否为空
	count, err := op.CommonRepo.SCard(ctx, subdomainKey)
	if err != nil {
		op.Log(fmt.Sprintf("[错误] 检查子域名Set失败: %v", err), "e")
		return
	}

	// 如果为空，直接返回
	if count == 0 {
		op.Log("Redis中的子域名Set为空，跳过处理")
		return
	}

	// 取出所有子域名
	subdomains, err := op.CommonRepo.SMembers(ctx, subdomainKey)
	if err != nil {
		op.Log(fmt.Sprintf("[错误] 获取子域名列表失败: %v", err), "e")
		return
	}

	op.Log(fmt.Sprintf("从Redis中取出 %d 个子域名，准备创建任务", len(subdomains)))
	target := ""
	for _, subdomain := range subdomains {
		if subdomain != "" {
			target += subdomain + "\n"
		}
	}
	// 创建任务
	if target != "" {
		task := models.Task{
			Name:           fmt.Sprintf("[ct monitor]-%v[plugin]", helper.GetNowTimeString()),
			AllNode:        true,
			Duplicates:     "None",
			ScheduledTasks: false,
			Template:       taskTemplateId,
			TargetSource:   "general",
			Target:         target,
		}
		_, err := op.TaskCommonService.Insert(context.Background(), &task)
		if err != nil {
			op.Log(fmt.Sprintf("[<UNK>] create task error <UNK>: %v", err), "e")
			return
		}

		// 成功创建任务后，从Redis中删除已处理的子域名
		members := make([]interface{}, len(subdomains))
		for i, subdomain := range subdomains {
			members[i] = subdomain
		}
		err = op.CommonRepo.SRem(ctx, subdomainKey, members...)
		if err != nil {
			op.Log(fmt.Sprintf("[错误] 删除Redis中的子域名失败: %v", err), "e")
		} else {
			op.Log(fmt.Sprintf("成功从Redis中删除 %d 个已处理的子域名", len(subdomains)))
		}
	}

}

func TaskEnd(task models.Task, plgHash string) error {
	if CTSDK == nil {
		OP.Log("<UNK>CTSDK is null<UNK>...")
		return fmt.Errorf("CTSDK is null")
	}
	// 插件创建的 一般都是已经有数据的不需要再创建了
	if strings.Contains(task.Name, "[plugin]") {
		return nil
	}
	filter := bson.M{
		"taskName": task.Name,
	}
	var rootDomains []bson.M
	err := OP.CommonRepo.FindField(context.Background(), "RootDomain", filter, 0, []string{"domain"}, &rootDomains)
	if err != nil {
		return err
	}

	// 将返回的所有domains转成字符串数组
	domains := make([]string, 0, len(rootDomains))
	for _, doc := range rootDomains {
		if domain, ok := doc["domain"].(string); ok {
			domains = append(domains, domain)
		}
	}
	err = CTSDK.AddDomains(domains)
	if err != nil {
		OP.Log(fmt.Sprintf("<UNK>CTSDK add domain error<UNK>: %v", err), "e")
		return err
	}
	OP.Log(fmt.Sprintf("CT监控增加关注域名 %v 个", len(domains)))
	return nil
}
