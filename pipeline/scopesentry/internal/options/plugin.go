// options-------------------------------------
// @file      : plugin.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/3 21:12
// -------------------------------------------

package options

import (
	"github.com/Autumn-27/ScopeSentry/internal/config"
	"github.com/Autumn-27/ScopeSentry/internal/database/mongodb"
	sasRedis "github.com/Autumn-27/ScopeSentry/internal/database/redis"
	commonRepo "github.com/Autumn-27/ScopeSentry/internal/repositories/common"
	assetCommon "github.com/Autumn-27/ScopeSentry/internal/services/assets/common"
	"github.com/Autumn-27/ScopeSentry/internal/services/node"
	"github.com/Autumn-27/ScopeSentry/internal/services/poc"
	taskCommon "github.com/Autumn-27/ScopeSentry/internal/services/task/common"
	"github.com/Autumn-27/ScopeSentry/internal/services/task/template"
	"github.com/redis/go-redis/v9"
	"go.mongodb.org/mongo-driver/mongo"
)

type PluginOption struct {
	DB                 *mongo.Database
	RedisClinet        *redis.Client
	TaskCommonService  taskCommon.Service
	TemplateService    template.Service
	PocService         poc.Service
	AssetCommonService assetCommon.Service
	CommonRepo         commonRepo.Repository
	Node               node.Service
	SetStringVariable  func(key string, value string)
	GetStringVariable  func(key string) (value string)
	Log                func(msg string, tp ...string)
	Notification       func(msg string)
	PluginHash         string
}

var PluginOptionInit PluginOption

func init() {
	PluginOptionInit = PluginOption{
		DB:                 mongodb.DB,
		RedisClinet:        sasRedis.Client,
		TaskCommonService:  taskCommon.NewService(),
		Node:               node.NewService(),
		PocService:         poc.NewService(),
		AssetCommonService: assetCommon.NewService(),
		CommonRepo:         commonRepo.NewRepository(),
		TemplateService:    template.NewService(),
		Notification:       config.Notification,
	}
}

func NewOption(hash string) PluginOption {
	return PluginOption{
		DB:                 PluginOptionInit.DB,
		RedisClinet:        PluginOptionInit.RedisClinet,
		TaskCommonService:  PluginOptionInit.TaskCommonService,
		Node:               PluginOptionInit.Node,
		PocService:         PluginOptionInit.PocService,
		AssetCommonService: PluginOptionInit.AssetCommonService,
		CommonRepo:         PluginOptionInit.CommonRepo,
		TemplateService:    PluginOptionInit.TemplateService,
		Notification:       PluginOptionInit.Notification,
		PluginHash:         hash,
	}
}
