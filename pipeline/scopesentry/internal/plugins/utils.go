// plugins-------------------------------------
// @file      : utils.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/20 20:15
// -------------------------------------------

package plugins

import (
	"context"
	"fmt"
	"time"

	"github.com/Autumn-27/ScopeSentry/internal/database/mongodb"
	"github.com/Autumn-27/ScopeSentry/internal/logger"
	plgOption "github.com/Autumn-27/ScopeSentry/internal/options"
	"github.com/Autumn-27/ScopeSentry/internal/utils"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/mongo/options"
	mongoOptions "go.mongodb.org/mongo-driver/mongo/options"
	"go.uber.org/zap"
)

func SetStringVariable(key, value string) {
	ctx := context.Background()
	collection := mongodb.DB.Collection("variable")

	filter := bson.M{"key": key}
	update := bson.M{"$set": bson.M{"key": key, "value": value}}

	opts := options.Update().SetUpsert(true)
	_, err := collection.UpdateOne(ctx, filter, update, opts)
	if err != nil {
		logger.Error(fmt.Sprintf("Error updating variable %s: %v", key, err))
	}
}

func GetStringVariable(key string) string {
	ctx := context.Background()
	collection := mongodb.DB.Collection("variable")

	var result bson.M
	err := collection.FindOne(ctx, bson.M{"key": key}).Decode(&result)
	if err != nil {
		logger.Error(fmt.Sprintf("Error getting variable %s: %v", key, err))
		return ""
	}

	if value, ok := result["value"].(string); ok {
		return value
	}
	return ""
}

func RunPluginOnce(hash string) {
	// 判断插件状态 如果是开启 再运行
	var result PluginInfo
	ctx := context.Background()
	collection := mongodb.DB.Collection("plugins")
	opts := mongoOptions.FindOne().
		SetProjection(bson.M{
			"status": 1,
		})
	err := collection.FindOne(ctx, bson.M{"hash": hash}, opts).Decode(&result)
	if err != nil {
		logger.Error(err.Error())
		return
	}
	if !result.Status {
		return
	}
	plg, flag := GlobalPluginManager.GetPlugin(hash)
	if flag {
		go func() {
			// 根据hash查看是否存在上下文 存在上下文说明 插件已经在运行了 需要暂停之后 再重新开始 上下文的创建一般是在插件内部进行创建的
			flag := utils.HasContext(hash)
			if flag {
				utils.CancelContext(hash)
				time.Sleep(time.Second * 5)
			}
			if plg.Cycle() == "1" {
				err := plg.Execute(plgOption.NewOption(hash))
				if err != nil {
					logger.Error("failed to execute plugin", zap.Error(err))
					return
				}
			}
		}()
	} else {
		logger.Error(fmt.Sprintf("%v plugin not found", hash))
	}
}
