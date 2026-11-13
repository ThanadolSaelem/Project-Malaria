// ct-----------------------------------------
// @file      : watcher.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/01/24 21:00
// -------------------------------------------
// CT日志监听SDK - Scanner监听器封装
// ============================================

package ct

import (
	"context"
	"crypto/tls"
	"fmt"
	"net/http"
	"sync/atomic"
	"time"

	"github.com/Autumn-27/ScopeSentry/internal/global"
	"github.com/Autumn-27/ScopeSentry/internal/utils/ct/models"
	"github.com/Autumn-27/ScopeSentry/internal/utils/ct/types"

	ct "github.com/google/certificate-transparency-go"
	"github.com/google/certificate-transparency-go/client"
	"github.com/google/certificate-transparency-go/jsonclient"
	"github.com/google/certificate-transparency-go/scanner"
	"go.uber.org/zap"
)

// CTWatcher CT日志监听器
type CTWatcher struct {
	// 配置
	config      *types.LogServerConfig
	performance *types.PerformanceConfig

	// 核心组件
	streamProcessor *StreamProcessor
	checkpointSaver *AutoCheckpointSaver

	// Scanner相关
	httpClient *http.Client
	ctClient   *client.LogClient
	scanner    *scanner.Scanner

	// 状态管理
	status     *models.WatcherStatus
	checkpoint *models.Checkpoint
	isRunning  int32
	lastIndex  int64

	// 日志
	logger *zap.Logger

	// 上下文控制
	ctx    context.Context
	cancel context.CancelFunc

	// 统计信息
	stats struct {
		totalProcessed int64
		totalErrors    int64
		startTime      time.Time
	}
}

// NewCTWatcher 创建新的CT监听器
func NewCTWatcher(
	config *types.LogServerConfig,
	performance *types.PerformanceConfig,
	streamProcessor *StreamProcessor,
	checkpointSaver *AutoCheckpointSaver,
) *CTWatcher {

	ctx, cancel := context.WithCancel(context.Background())

	watcher := &CTWatcher{
		config:          config,
		performance:     performance,
		streamProcessor: streamProcessor,
		checkpointSaver: checkpointSaver,
		status: models.NewWatcherStatus(&models.LogServerConfig{
			URL:         config.URL,
			Description: config.URL, // 使用URL作为默认描述
			Operator:    "Unknown",  // 默认操作符
		}),
		logger: global.Log, // 使用全局logger
		ctx:    ctx,
		cancel: cancel,
	}

	// 初始化HTTP客户端
	watcher.initHTTPClient()

	return watcher
}

// Start 启动监听器
func (w *CTWatcher) Start() error {
	if !atomic.CompareAndSwapInt32(&w.isRunning, 0, 1) {
		return fmt.Errorf("监听器已在运行")
	}

	w.stats.startTime = time.Now()
	w.status.UpdateStatus("connecting")

	// 初始化CT客户端
	if err := w.initCTClient(); err != nil {
		atomic.StoreInt32(&w.isRunning, 0)
		w.status.UpdateStatus("error")
		return fmt.Errorf("初始化CT客户端失败: %w", err)
	}

	// 加载检查点
	if err := w.loadCheckpoint(); err != nil {
		atomic.StoreInt32(&w.isRunning, 0)
		w.status.UpdateStatus("error")
		return fmt.Errorf("加载检查点失败: %w", err)
	}

	// 创建Scanner
	if err := w.createScanner(); err != nil {
		atomic.StoreInt32(&w.isRunning, 0)
		w.status.UpdateStatus("error")
		return fmt.Errorf("创建Scanner失败: %w", err)
	}

	w.status.UpdateStatus("connected")

	// 启动监听循环
	go w.watchLoop()

	return nil
}

// Stop 停止监听器
func (w *CTWatcher) Stop() error {
	if !atomic.CompareAndSwapInt32(&w.isRunning, 1, 0) {
		return nil
	}

	w.status.UpdateStatus("disconnected")

	// 取消上下文
	w.cancel()

	// 保存最终检查点
	w.saveCheckpoint()

	return nil
}

// GetStatus 获取监听器状态
func (w *CTWatcher) GetStatus() *models.WatcherStatus {
	// 更新实时统计信息
	w.status.ProcessedCount = atomic.LoadInt64(&w.stats.totalProcessed)
	w.status.LastProcessedIndex = atomic.LoadInt64(&w.lastIndex)
	w.status.LastActivity = time.Now()

	return w.status
}

// watchLoop 监听循环（核心方法）
func (w *CTWatcher) watchLoop() {
	defer func() {
		atomic.StoreInt32(&w.isRunning, 0)
		w.status.UpdateStatus("stopped")
	}()

	for {
		select {
		case <-w.ctx.Done():
			return
		default:
		}

		// 执行一次扫描
		if err := w.performScan(); err != nil {
			w.status.RecordError()
			atomic.AddInt64(&w.stats.totalErrors, 1)

			// 等待重试
			select {
			case <-w.ctx.Done():
				return
			case <-time.After(w.calculateRetryDelay()):
				continue
			}
		}

		// 扫描成功后等待下一次扫描
		select {
		case <-w.ctx.Done():
			return
		case <-time.After(30 * time.Second): // 每30秒扫描一次
			continue
		}
	}
}

// performScan 执行一次扫描
func (w *CTWatcher) performScan() error {
	if w.scanner == nil {
		return fmt.Errorf("scanner未初始化")
	}

	w.status.UpdateStatus("scanning")

	// 创建带超时的上下文
	scanCtx, cancel := context.WithTimeout(w.ctx, 5*time.Minute)
	defer cancel()

	// 执行扫描
	err := w.scanner.Scan(scanCtx, w.foundCertCallback, w.foundPrecertCallback)
	if err != nil {
		w.status.UpdateStatus("error")
		return fmt.Errorf("扫描失败: %w", err)
	}

	w.status.UpdateStatus("connected")
	return nil
}

// foundCertCallback 证书发现回调函数
func (w *CTWatcher) foundCertCallback(rawEntry *ct.RawLogEntry) {
	w.processRawEntry(rawEntry, "X509LogEntry")
}

// foundPrecertCallback 预证书发现回调函数
func (w *CTWatcher) foundPrecertCallback(rawEntry *ct.RawLogEntry) {
	w.processRawEntry(rawEntry, "PrecertLogEntry")
}

// processRawEntry 处理原始日志条目
func (w *CTWatcher) processRawEntry(rawEntry *ct.RawLogEntry, entryType string) {
	// 解析时间戳
	timestamp := time.Unix(int64(rawEntry.Leaf.TimestampedEntry.Timestamp)/1000, 0)

	// 更新处理索引（无论后续处理结果如何，都标记为已处理）
	for {
		currentIndex := atomic.LoadInt64(&w.lastIndex)
		if rawEntry.Index <= currentIndex {
			// 索引不大于当前索引，跳过更新
			break
		}
		if atomic.CompareAndSwapInt64(&w.lastIndex, currentIndex, rawEntry.Index) {
			// 成功更新索引
			break
		}
		// CAS失败，重试
	}

	// 根据证书类型获取数据
	var certData []byte
	switch entryType {
	case "X509LogEntry":
		if rawEntry.Leaf.TimestampedEntry.X509Entry == nil {
			w.logger.Warn("X509Entry为空，跳过处理", zap.Int64("index", rawEntry.Index))
			atomic.AddInt64(&w.stats.totalProcessed, 1)
			w.status.RecordProcessing(1)
			w.updateCheckpoint(rawEntry.Index)
			return
		}
		certData = rawEntry.Leaf.TimestampedEntry.X509Entry.Data
	case "PrecertLogEntry":
		// 预证书暂时跳过处理，因为域名信息可能不完整
		w.logger.Debug("跳过预证书处理", zap.Int64("index", rawEntry.Index))
		atomic.AddInt64(&w.stats.totalProcessed, 1)
		w.status.RecordProcessing(1)
		w.updateCheckpoint(rawEntry.Index)
		return
	default:
		w.logger.Warn("未知的证书类型", zap.String("type", entryType), zap.Int64("index", rawEntry.Index))
		atomic.AddInt64(&w.stats.totalProcessed, 1)
		w.status.RecordProcessing(1)
		w.updateCheckpoint(rawEntry.Index)
		return
	}

	// 流式处理证书
	err := w.streamProcessor.ProcessCertificate(
		certData,
		rawEntry.Index,
		timestamp,
		w.config.URL,
	)

	atomic.AddInt64(&w.stats.totalProcessed, 1)
	w.status.RecordProcessing(1)

	if err != nil {
		atomic.AddInt64(&w.stats.totalErrors, 1)
		w.status.RecordError()
		// 即使处理失败，也更新检查点（标记为已尝试处理）
		w.updateCheckpoint(rawEntry.Index)
		return
	}

	// 处理成功，更新检查点
	w.updateCheckpoint(rawEntry.Index)
}

// updateCheckpoint 更新检查点
func (w *CTWatcher) updateCheckpoint(index int64) {
	if w.checkpoint != nil {
		w.checkpoint.Update(index, 0) // STH大小暂时设为0
		w.checkpointSaver.UpdateCheckpoint(w.checkpoint)
	}
}

// saveCheckpoint 保存检查点
func (w *CTWatcher) saveCheckpoint() {
	if w.checkpointSaver != nil && w.checkpoint != nil {
		w.checkpointSaver.UpdateCheckpoint(w.checkpoint)
	}
}

// loadCheckpoint 加载检查点
func (w *CTWatcher) loadCheckpoint() error {
	if w.checkpointSaver == nil {
		return fmt.Errorf("检查点保存器未初始化")
	}

	cp, err := w.checkpointSaver.manager.LoadCheckpoint(w.config.URL)
	if err != nil {
		return err
	}

	w.checkpoint = cp

	// 根据检查点状态决定起始索引
	if cp.LastProcessedIndex == 0 {
		// 从Redis加载的检查点显示LastProcessedIndex为0，说明是首次运行
		if w.ctClient != nil {
			sth, err := w.ctClient.GetSTH(context.Background())
			if err != nil {
				w.logger.Warn("获取STH失败，使用默认索引继续监听", zap.Error(err))
				// 获取STH失败时，使用默认索引0继续运行，不停止监听
				atomic.StoreInt64(&w.lastIndex, 0)
			} else {
				// 从当前树大小开始监听新的证书
				treeSize := int64(sth.TreeSize)
				atomic.StoreInt64(&w.lastIndex, treeSize)
				w.logger.Info("首次运行，从当前树大小开始监听",
					zap.Int64("tree_size", treeSize),
					zap.String("url", w.config.URL))
			}
		} else {
			// 没有CT客户端，使用默认索引
			atomic.StoreInt64(&w.lastIndex, 0)
			w.logger.Info("首次运行，使用默认索引开始监听",
				zap.String("url", w.config.URL))
		}
	} else {
		// 检查点存在，继续从上次的位置运行
		atomic.StoreInt64(&w.lastIndex, cp.LastProcessedIndex)
		w.logger.Info("继续上次运行，从检查点恢复",
			zap.Int64("last_index", cp.LastProcessedIndex),
			zap.String("url", w.config.URL))
	}

	return nil
}

// initHTTPClient 初始化HTTP客户端
func (w *CTWatcher) initHTTPClient() {
	w.httpClient = &http.Client{
		Timeout: w.config.Timeout,
		Transport: &http.Transport{
			Proxy: http.ProxyFromEnvironment, // 显式使用环境变量中的代理设置
			TLSClientConfig: &tls.Config{
				InsecureSkipVerify: false,
			},
			MaxIdleConns:        10,
			MaxIdleConnsPerHost: 2,
			IdleConnTimeout:     90 * time.Second,
		},
	}
}

// initCTClient 初始化CT客户端
func (w *CTWatcher) initCTClient() error {
	userAgent := "CT-Watcher/1.0"

	jsonClient, err := client.New(w.config.URL, w.httpClient, jsonclient.Options{
		UserAgent: userAgent,
	})
	if err != nil {
		return fmt.Errorf("创建JSON客户端失败: %w", err)
	}

	w.ctClient = jsonClient
	return nil
}

// createScanner 创建Scanner实例
func (w *CTWatcher) createScanner() error {
	if w.ctClient == nil {
		return fmt.Errorf("CT客户端未初始化")
	}

	scannerOptions := &scanner.ScannerOptions{
		FetcherOptions: scanner.FetcherOptions{
			BatchSize:     w.config.BatchSize,
			ParallelFetch: w.config.ParallelFetch,
			StartIndex:    w.lastIndex,
			Continuous:    true, // 持续监听模式
		},
		Matcher:     scanner.MatchAll{}, // 匹配所有证书
		PrecertOnly: false,              // 处理所有证书类型
		NumWorkers:  1,                  // 扫描工作协程数
		BufferSize:  w.config.BufferSize,
	}

	w.scanner = scanner.NewScanner(w.ctClient, *scannerOptions)

	return nil
}

// calculateRetryDelay 计算重试延迟
func (w *CTWatcher) calculateRetryDelay() time.Duration {
	// 简单的指数退避策略
	retryCount := w.status.ErrorCount
	if retryCount > 10 {
		retryCount = 10
	}

	delay := time.Duration(retryCount) * 5 * time.Second
	if delay > 5*time.Minute {
		delay = 5 * time.Minute
	}

	return delay
}

// GetStats 获取监听器统计信息
func (w *CTWatcher) GetStats() *WatcherStats {
	return &WatcherStats{
		TotalProcessed: atomic.LoadInt64(&w.stats.totalProcessed),
		TotalErrors:    atomic.LoadInt64(&w.stats.totalErrors),
		Uptime:         time.Since(w.stats.startTime),
		CurrentIndex:   atomic.LoadInt64(&w.lastIndex),
	}
}

// WatcherStats 监听器统计信息
type WatcherStats struct {
	TotalProcessed int64         `json:"total_processed"`
	TotalErrors    int64         `json:"total_errors"`
	Uptime         time.Duration `json:"uptime"`
	CurrentIndex   int64         `json:"current_index"`
}
