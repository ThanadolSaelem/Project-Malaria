// Package models -----------------------------
// @file      : plugin.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/4/27 17:20
// -------------------------------------------
package models

import "go.mongodb.org/mongo-driver/bson/primitive"

type Plugin struct {
	ID            primitive.ObjectID `bson:"_id,omitempty" json:"id"`
	Module        string             `json:"module"`
	Name          string             `json:"name"`
	Hash          string             `json:"hash"`
	Parameter     string             `json:"parameter"`
	Help          string             `json:"help"`
	Status        bool               `json:"status"`
	Type          string             `bson:"type" json:"type"`
	LastTime      string             `bson:"lastTime" json:"lastTime"`
	NextTime      string             `bson:"nextTime" json:"nextTime"`
	Introduction  string             `json:"introduction"`
	ParameterList string             `json:"parameterList"`
	IsSystem      bool               `json:"isSystem"`
	Version       string             `json:"version"`
	Source        string             `json:"source"`
}

// PluginListRequest 插件列表请求
type PluginListRequest struct {
	PageIndex int    `json:"pageIndex" binding:"required,min=1"`
	PageSize  int    `json:"pageSize" binding:"required,min=1"`
	Type      string `json:"type"`
	Search    string `json:"search"`
}

// PluginListResponse 插件列表响应
type PluginListResponse struct {
	List  []Plugin `json:"list"`
	Total int64    `json:"total"`
}

// PluginDetailRequest 插件详情请求
type PluginDetailRequest struct {
	ID string `json:"id" binding:"required"`
}

// PluginSaveRequest 插件保存请求
type PluginSaveRequest struct {
	ID            string `json:"id"`
	Name          string `json:"name" binding:"required"`
	Module        string `json:"module"`
	Hash          string `json:"hash"`
	Parameter     string `json:"parameter"`
	Help          string `json:"help"`
	Introduction  string `json:"introduction"`
	ParameterList string `json:"parameterList"`
	Source        string `json:"source"`
	Version       string `json:"version"`
	IsSystem      bool   `json:"isSystem"`
	Type          string `json:"type"`
	Key           string `json:"key" binding:"required"`
}

// PluginDeleteRequest 插件删除请求
type PluginDeleteRequest struct {
	Data []struct {
		Hash   string `json:"hash" binding:"required"`
		Module string `json:"module" binding:"required"`
	} `json:"data" binding:"required"`
}

// PluginLogRequest 插件日志请求
type PluginLogRequest struct {
	Module string `json:"module"`
	Hash   string `json:"hash" binding:"required"`
	Type   string `json:"type"`
}

// PluginReinstallRequest 插件重装请求
type PluginReinstallRequest struct {
	Node   string `json:"node"`
	Hash   string `json:"hash"`
	Module string `json:"module"`
}

// PluginRecheckRequest 插件重检请求
type PluginRecheckRequest struct {
	Node   string `json:"node" binding:"required"`
	Hash   string `json:"hash" binding:"required"`
	Module string `json:"module" binding:"required"`
}

// PluginUninstallRequest 插件卸载请求
type PluginUninstallRequest struct {
	Node   string `json:"node" binding:"required"`
	Hash   string `json:"hash" binding:"required"`
	Module string `json:"module" binding:"required"`
}

// PluginKeyCheckRequest 插件密钥检查请求
type PluginKeyCheckRequest struct {
	Key string `json:"key" binding:"required"`
}

// PluginImportByDataRequest 通过POST JSON数据导入插件请求
type PluginImportByDataRequest struct {
	JSON     string `json:"json" `    // info.json的完整序列化json字符串
	Source   string `json:"source" `  // plugin.go的完整源代码内容
	IsSystem bool   `json:"isSystem"` // 是否为内置插件
	Key      string `json:"key"`      // 插件密钥
}

// PluginStatusRequest 插件状态更新请求
type PluginStatusRequest struct {
	ID     string `json:"id"`     // 插件ID
	Status bool   `json:"status"` // 插件状态
}

// PluginRunRequest 插件运行请求
type PluginRunRequest struct {
	Hash string `json:"hash" binding:"required"` // 插件Hash
}

type PluginInfo struct {
	Help          string `json:"help"`
	Parameter     string `json:"parameter"`
	Module        string `json:"module"`
	Name          string `json:"name"`
	Version       string `json:"version"`
	Introduction  string `json:"introduction"`
	Hash          string `json:"hash"`
	ParameterList string `json:"parameterList"`
	Type          string `json:"type"`
	// 以下是程序运行时动态添加的字段，可选
	Source   string `json:"source,omitempty"`
	IsSystem bool   `json:"isSystem,omitempty"`
}

type NodePluginInfo struct {
	Name    string `json:"name"`
	Install string `json:"install"`
	Check   string `json:"check"`
	Hash    string `json:"hash"`
	Module  string `json:"module"`
}
