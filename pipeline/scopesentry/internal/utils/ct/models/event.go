// ct/models-----------------------------------
// @file      : event.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/01/24 21:00
// -------------------------------------------
// CT日志监听SDK - 事件和回调定义
// ============================================

package models

import (
	"fmt"
	"time"
)

// EventType 事件类型
type EventType string

const (
	// 子域名发现事件
	EventTypeSubdomainDiscovered EventType = "subdomain_discovered"

	// 证书处理事件
	EventTypeCertificateProcessed EventType = "certificate_processed"

	// 错误事件
	EventTypeErrorOccurred EventType = "error_occurred"

	// 监听器状态事件
	EventTypeWatcherStatusChanged EventType = "watcher_status_changed"

	// SDK生命周期事件
	EventTypeSDKStarted EventType = "sdk_started"
	EventTypeSDKStopped EventType = "sdk_stopped"
)

// Event 基础事件接口
type Event interface {
	GetType() EventType
	GetTimestamp() time.Time
	GetID() string
}

// BaseEvent 基础事件结构
type BaseEvent struct {
	Type      EventType `json:"type"`      // 事件类型
	ID        string    `json:"id"`        // 事件唯一ID
	Timestamp time.Time `json:"timestamp"` // 事件时间戳
}

// GetType 实现Event接口
func (e *BaseEvent) GetType() EventType {
	return e.Type
}

// GetTimestamp 实现Event接口
func (e *BaseEvent) GetTimestamp() time.Time {
	return e.Timestamp
}

// GetID 实现Event接口
func (e *BaseEvent) GetID() string {
	return e.ID
}

// SubdomainDiscoveredEvent 子域名发现事件
type SubdomainDiscoveredEvent struct {
	BaseEvent
	SubdomainEvent SubdomainEvent `json:"subdomain_event"`
}

// SubdomainEvent 子域名事件详情
type SubdomainEvent struct {
	Subdomain    string    `json:"subdomain"`     // 发现的子域名
	RootDomain   string    `json:"root_domain"`   // 根域名
	Certificate  *CertInfo `json:"certificate"`   // 证书信息（简化版）
	DiscoveredAt time.Time `json:"discovered_at"` // 发现时间
	EventID      string    `json:"event_id"`      // 事件ID
	IsNew        bool      `json:"is_new"`        // 是否为新发现
}

// CertInfo 证书信息（简化版，只包含必要字段）
type CertInfo struct {
	LogURL     string    `json:"log_url"`     // CT日志URL
	LogID      string    `json:"log_id"`      // 日志ID
	Index      int64     `json:"index"`       // 证书索引
	Timestamp  time.Time `json:"timestamp"`   // 证书时间戳
	CommonName string    `json:"common_name"` // 证书CN
	AllDomains []string  `json:"all_domains"` // 证书中所有域名
}

// CertificateProcessedEvent 证书处理事件
type CertificateProcessedEvent struct {
	BaseEvent
	Certificate    *CertInfo     `json:"certificate"`     // 证书信息
	ProcessingTime time.Duration `json:"processing_time"` // 处理耗时
	Success        bool          `json:"success"`         // 是否成功
	Error          string        `json:"error,omitempty"` // 错误信息
}

// ErrorOccurredEvent 错误发生事件
type ErrorOccurredEvent struct {
	BaseEvent
	ErrorType    string                 `json:"error_type"`    // 错误类型
	ErrorMessage string                 `json:"error_message"` // 错误消息
	Context      map[string]interface{} `json:"context"`       // 错误上下文
	Severity     string                 `json:"severity"`      // 严重程度 (low/medium/high/critical)
	Recoverable  bool                   `json:"recoverable"`   // 是否可恢复
}

// WatcherStatusChangedEvent 监听器状态变化事件
type WatcherStatusChangedEvent struct {
	BaseEvent
	LogURL    string `json:"log_url"`    // CT日志URL
	OldStatus string `json:"old_status"` // 旧状态
	NewStatus string `json:"new_status"` // 新状态
	Reason    string `json:"reason"`     // 变化原因
}

// SDKLifecycleEvent SDK生命周期事件
type SDKLifecycleEvent struct {
	BaseEvent
	Action   string         `json:"action"`             // 动作 (start/stop/restart)
	Reason   string         `json:"reason"`             // 原因
	Duration *time.Duration `json:"duration,omitempty"` // 持续时间（停止时）
	Stats    *SDKStats      `json:"stats,omitempty"`    // 当前统计信息
}

// SDKStats SDK统计信息
type SDKStats struct {
	TotalProcessedCertificates int64         `json:"total_processed_certificates"` // 总处理证书数
	TotalDiscoveredSubdomains  int64         `json:"total_discovered_subdomains"`  // 总发现子域名数
	TotalErrors                int64         `json:"total_errors"`                 // 总错误数
	Uptime                     time.Duration `json:"uptime"`                       // 运行时间
}

// 回调函数类型定义

// SubdomainCallback 子域名发现回调函数
type SubdomainCallback func(event SubdomainEvent)

// CertificateCallback 证书处理回调函数
type CertificateCallback func(cert *CertInfo, success bool, err error)

// ErrorCallback 错误回调函数
type ErrorCallback func(err error, context map[string]interface{})

// StatusCallback 状态变化回调函数
type StatusCallback func(logURL string, oldStatus, newStatus string)

// 事件处理器接口

// EventHandler 事件处理器接口
type EventHandler interface {
	HandleEvent(event Event) error
}

// EventBus 事件总线
type EventBus struct {
	handlers map[EventType][]EventHandler
}

// NewEventBus 创建新的事件总线
func NewEventBus() *EventBus {
	return &EventBus{
		handlers: make(map[EventType][]EventHandler),
	}
}

// Subscribe 订阅事件
func (eb *EventBus) Subscribe(eventType EventType, handler EventHandler) {
	eb.handlers[eventType] = append(eb.handlers[eventType], handler)
}

// Publish 发布事件
func (eb *EventBus) Publish(event Event) error {
	handlers, exists := eb.handlers[event.GetType()]
	if !exists {
		return nil
	}

	for _, handler := range handlers {
		if err := handler.HandleEvent(event); err != nil {
			// 记录错误但不中断其他处理器
			continue
		}
	}
	return nil
}

// GenerateEventID 生成事件ID
func GenerateEventID() string {
	return fmt.Sprintf("evt_%d", time.Now().UnixNano())
}
