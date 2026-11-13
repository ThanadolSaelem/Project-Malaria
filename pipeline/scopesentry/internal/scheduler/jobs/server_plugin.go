// jobs-------------------------------------
// @file      : server_plugin.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/20 0:14
// -------------------------------------------

package jobs

import (
	"fmt"
	"github.com/Autumn-27/ScopeSentry/internal/database/mongodb"
	"github.com/Autumn-27/ScopeSentry/internal/logger"
	"github.com/Autumn-27/ScopeSentry/internal/models"
	"github.com/Autumn-27/ScopeSentry/internal/options"
	"github.com/Autumn-27/ScopeSentry/internal/plugins"
	"github.com/Autumn-27/ScopeSentry/internal/utils/helper"
	"go.mongodb.org/mongo-driver/bson"
)

func ServerPluginRunner(id string, nextTime string) error {
	filter := bson.M{"hash": id}

	var plg models.Plugin
	err := mongodb.FindOne("plugins", filter, &plg)
	if err != nil {
		logger.Error(err.Error())
		return err
	}
	if plg.Status {
		plgRunner, flag := plugins.GlobalPluginManager.GetPlugin(id)
		if !flag {
			plugin, err := plugins.LoadPlugin(plg.Source, plg.Hash)
			if err != nil {
				return err
			}
			plugins.GlobalPluginManager.RegisterPlugin(id, plugin)
			err = plugin.Install()
			if err != nil {
				logger.Error(err.Error())
				return err
			}
			plgRunner = plugin.Clone()
		}
		mongodb.UpdateOne("plugins", bson.M{"hash": id}, bson.M{"$set": bson.M{"lastTime": helper.GetNowTimeString(), "nextTime": nextTime}})
		plgRunner.Log("plugin is running")
		err := plgRunner.Execute(options.NewOption(id))
		if err != nil {
			logger.Error(err.Error())
			plgRunner.Log(fmt.Sprintf("plugin execution error: %v", err), "e")
			return err
		}
		plgRunner.Log("plugin is end")

	}
	return nil
}
