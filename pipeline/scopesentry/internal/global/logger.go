// global-------------------------------------
// @file      : logger.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/22 22:25
// -------------------------------------------

package global

import (
	"go.uber.org/zap"
)

var Log *zap.Logger

func init() {
	var err error
	Log, err = zap.NewProduction()
	if err != nil {
		panic(err)
	}
}
