// plugins-------------------------------------
// @file      : context_manager.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/20 20:15
// -------------------------------------------

package utils

import (
	"context"
	"sync"
)

// contextInfo 存储context和对应的cancel函数
type contextInfo struct {
	ctx    context.Context
	cancel context.CancelFunc
}

var (
	// pluginContexts 全局变量，存储所有插件的上下文
	pluginContexts = make(map[string]*contextInfo)
	// contextMutex 保护pluginContexts的互斥锁
	contextMutex sync.RWMutex
)

// GetContext 根据插件ID获取context，如果不存在则创建新的
func GetContext(id string) context.Context {
	contextMutex.Lock()
	defer contextMutex.Unlock()

	// 如果已存在，直接返回
	if info, exists := pluginContexts[id]; exists && info != nil {
		return info.ctx
	}

	// 不存在则创建新的context
	ctx, cancel := context.WithCancel(context.Background())
	pluginContexts[id] = &contextInfo{
		ctx:    ctx,
		cancel: cancel,
	}

	return ctx
}

// CancelContext 根据插件ID取消并删除context
func CancelContext(id string) {
	contextMutex.Lock()
	defer contextMutex.Unlock()

	// 如果存在，先取消，然后删除
	if info, exists := pluginContexts[id]; exists && info != nil {
		info.cancel()
		delete(pluginContexts, id)
	}
}

// HasContext 检查插件是否已有context
func HasContext(id string) bool {
	contextMutex.RLock()
	defer contextMutex.RUnlock()

	_, exists := pluginContexts[id]
	return exists
}
