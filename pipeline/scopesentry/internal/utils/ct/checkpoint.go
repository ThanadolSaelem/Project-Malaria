// ct-----------------------------------------
// @file      : checkpoint.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/01/24 21:00
// -------------------------------------------
// CT日志监听SDK - Redis检查点机制
// ============================================

package ct

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	sasRedis "github.com/Autumn-27/ScopeSentry/internal/database/redis"
	"github.com/Autumn-27/ScopeSentry/internal/utils/ct/models"
	"github.com/redis/go-redis/v9"
)

// RedisCheckpointManager Redis检查点管理器
type RedisCheckpointManager struct {
	client    *redis.Client // 使用项目全局Redis客户端
	keyPrefix string
	ctx       context.Context
}

// NewRedisCheckpointManager 创建新的Redis检查点管理器
func NewRedisCheckpointManager(keyPrefix string) (*RedisCheckpointManager, error) {
	// 使用项目全局的Redis客户端
	redisClient := sasRedis.Client
	if redisClient == nil {
		return nil, fmt.Errorf("Redis客户端未初始化")
	}

	// 测试连接
	ctx := context.Background()
	if err := redisClient.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("Redis连接失败: %w", err)
	}

	return &RedisCheckpointManager{
		client:    redisClient,
		keyPrefix: keyPrefix,
		ctx:       ctx,
	}, nil
}

// SaveCheckpoint 保存检查点
func (rcm *RedisCheckpointManager) SaveCheckpoint(cp *models.Checkpoint) error {
	if cp == nil || !cp.IsValid() {
		return fmt.Errorf("无效的检查点数据")
	}

	key := rcm.makeKey(cp.URL)
	data, err := json.Marshal(cp)
	if err != nil {
		return fmt.Errorf("序列化检查点失败: %w", err)
	}

	// 保存到Redis（无过期时间）
	err = rcm.client.Set(rcm.ctx, key, data, 0).Err()
	if err != nil {
		return fmt.Errorf("保存检查点到Redis失败: %w", err)
	}

	return nil
}

// LoadCheckpoint 加载检查点
func (rcm *RedisCheckpointManager) LoadCheckpoint(url string) (*models.Checkpoint, error) {
	key := rcm.makeKey(url)

	data, err := rcm.client.Get(rcm.ctx, key).Result()
	if err != nil {
		if err.Error() == "redis: nil" {
			// 没有找到检查点，返回默认值
			return &models.Checkpoint{
				URL:                url,
				LastProcessedIndex: 0,
				Timestamp:          time.Now(),
				Version:            1,
			}, nil
		}
		return nil, fmt.Errorf("从Redis加载检查点失败: %w", err)
	}

	var cp models.Checkpoint
	if err := json.Unmarshal([]byte(data), &cp); err != nil {
		return nil, fmt.Errorf("反序列化检查点失败: %w", err)
	}

	return &cp, nil
}

// DeleteCheckpoint 删除检查点
func (rcm *RedisCheckpointManager) DeleteCheckpoint(url string) error {
	key := rcm.makeKey(url)

	err := rcm.client.Del(rcm.ctx, key).Err()
	if err != nil {
		return fmt.Errorf("删除检查点失败: %w", err)
	}

	return nil
}

// ListCheckpoints 列出所有检查点
func (rcm *RedisCheckpointManager) ListCheckpoints() ([]*models.Checkpoint, error) {
	pattern := rcm.keyPrefix + "checkpoint:*"

	keys, err := rcm.client.Keys(rcm.ctx, pattern).Result()
	if err != nil {
		return nil, fmt.Errorf("获取检查点键列表失败: %w", err)
	}

	checkpoints := make([]*models.Checkpoint, 0, len(keys))

	for _, key := range keys {
		data, err := rcm.client.Get(rcm.ctx, key).Result()
		if err != nil {
			continue // 跳过有问题的键
		}

		var cp models.Checkpoint
		if err := json.Unmarshal([]byte(data), &cp); err != nil {
			continue // 跳过无法解析的检查点
		}

		checkpoints = append(checkpoints, &cp)
	}

	return checkpoints, nil
}

// CleanupExpired 清理过期的检查点
func (rcm *RedisCheckpointManager) CleanupExpired(olderThan time.Duration) error {
	checkpoints, err := rcm.ListCheckpoints()
	if err != nil {
		return fmt.Errorf("获取检查点列表失败: %w", err)
	}

	cutoffTime := time.Now().Add(-olderThan)
	deletedCount := 0

	for _, cp := range checkpoints {
		if cp.Timestamp.Before(cutoffTime) {
			if err := rcm.DeleteCheckpoint(cp.URL); err != nil {
				continue // 跳过删除失败的检查点
			}
			deletedCount++
		}
	}

	return nil
}

// BatchSaveCheckpoints 批量保存检查点
func (rcm *RedisCheckpointManager) BatchSaveCheckpoints(checkpoints []*models.Checkpoint) error {
	if len(checkpoints) == 0 {
		return nil
	}

	pipe := rcm.client.Pipeline()

	for _, cp := range checkpoints {
		if cp == nil || !cp.IsValid() {
			continue
		}

		key := rcm.makeKey(cp.URL)
		data, err := json.Marshal(cp)
		if err != nil {
			continue // 跳过序列化失败的检查点
		}

		pipe.Set(rcm.ctx, key, data, 0)
	}

	_, err := pipe.Exec(rcm.ctx)
	if err != nil {
		return fmt.Errorf("批量保存检查点失败: %w", err)
	}

	return nil
}

// GetCheckpointStats 获取检查点统计信息
func (rcm *RedisCheckpointManager) GetCheckpointStats() (*CheckpointStats, error) {
	checkpoints, err := rcm.ListCheckpoints()
	if err != nil {
		return nil, fmt.Errorf("获取检查点统计失败: %w", err)
	}

	stats := &CheckpointStats{
		TotalCheckpoints: len(checkpoints),
	}

	if len(checkpoints) > 0 {
		oldest := checkpoints[0].Timestamp
		newest := checkpoints[0].Timestamp

		totalIndexes := int64(0)

		for _, cp := range checkpoints {
			if cp.Timestamp.Before(oldest) {
				oldest = cp.Timestamp
			}
			if cp.Timestamp.After(newest) {
				newest = cp.Timestamp
			}
			totalIndexes += cp.LastProcessedIndex
		}

		stats.OldestCheckpoint = oldest
		stats.NewestCheckpoint = newest
		stats.AverageIndex = totalIndexes / int64(len(checkpoints))
	}

	return stats, nil
}

// Close 关闭检查点管理器
// 注意：不关闭Redis连接，因为使用的是项目全局客户端
func (rcm *RedisCheckpointManager) Close() error {
	return nil
}

// makeKey 生成Redis键
func (rcm *RedisCheckpointManager) makeKey(url string) string {
	return rcm.keyPrefix + "checkpoint:" + url
}

// CheckpointStats 检查点统计信息
type CheckpointStats struct {
	TotalCheckpoints int       `json:"total_checkpoints"`
	OldestCheckpoint time.Time `json:"oldest_checkpoint"`
	NewestCheckpoint time.Time `json:"newest_checkpoint"`
	AverageIndex     int64     `json:"average_index"`
}

// AutoCheckpointSaver 自动检查点保存器
type AutoCheckpointSaver struct {
	manager     *RedisCheckpointManager
	interval    time.Duration
	checkpoints map[string]*models.Checkpoint
	mu          sync.RWMutex
	ctx         context.Context
	cancel      context.CancelFunc
	isRunning   bool
}

// NewAutoCheckpointSaver 创建自动检查点保存器
func NewAutoCheckpointSaver(manager *RedisCheckpointManager, interval time.Duration) *AutoCheckpointSaver {
	ctx, cancel := context.WithCancel(context.Background())

	return &AutoCheckpointSaver{
		manager:     manager,
		interval:    interval,
		checkpoints: make(map[string]*models.Checkpoint),
		ctx:         ctx,
		cancel:      cancel,
	}
}

// Start 启动自动保存
func (acs *AutoCheckpointSaver) Start() error {
	if acs.isRunning {
		return fmt.Errorf("自动保存器已在运行")
	}

	acs.isRunning = true
	acs.saveAllCheckpoints()
	go func() {
		ticker := time.NewTicker(acs.interval)
		defer ticker.Stop()

		for {
			select {
			case <-acs.ctx.Done():
				// 退出前保存所有检查点
				acs.saveAllCheckpoints()
				return
			case <-ticker.C:
				// 定时保存
				acs.saveAllCheckpoints()
			}
		}
	}()

	return nil
}

// Stop 停止自动保存
func (acs *AutoCheckpointSaver) Stop() error {
	if !acs.isRunning {
		return nil
	}

	acs.cancel()
	acs.isRunning = false

	return nil
}

// UpdateCheckpoint 更新检查点（内存中）
func (acs *AutoCheckpointSaver) UpdateCheckpoint(cp *models.Checkpoint) {
	acs.mu.Lock()
	defer acs.mu.Unlock()

	if cp != nil && cp.IsValid() {
		cp.Timestamp = time.Now()
		acs.checkpoints[cp.URL] = cp
	}
}

// RemoveCheckpoint 移除检查点
func (acs *AutoCheckpointSaver) RemoveCheckpoint(url string) {
	acs.mu.Lock()
	defer acs.mu.Unlock()

	delete(acs.checkpoints, url)
}

// saveAllCheckpoints 保存所有检查点到Redis
func (acs *AutoCheckpointSaver) saveAllCheckpoints() {
	acs.mu.RLock()
	checkpoints := make([]*models.Checkpoint, 0, len(acs.checkpoints))
	for _, cp := range acs.checkpoints {
		checkpoints = append(checkpoints, cp)
	}
	acs.mu.RUnlock()

	if len(checkpoints) > 0 {
		// 批量保存
		if err := acs.manager.BatchSaveCheckpoints(checkpoints); err != nil {
			// 这里可以添加错误处理，比如重试或告警
		}
	}
}

// GetPendingCheckpoints 获取待保存的检查点数量
func (acs *AutoCheckpointSaver) GetPendingCheckpoints() int {
	acs.mu.RLock()
	defer acs.mu.RUnlock()
	return len(acs.checkpoints)
}
