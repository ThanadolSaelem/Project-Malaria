// interfaces-------------------------------------
// @file      : plugin.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/6 16:08
// -------------------------------------------

package interfaces

import (
	"github.com/Autumn-27/ScopeSentry/internal/models"
	"github.com/Autumn-27/ScopeSentry/internal/options"
)

type Plugin interface {
	GetName() string
	Cycle() string
	Install() error
	Execute(op options.PluginOption) error
	TaskEnd(task models.Task, plgHash string) error
	Clone() Plugin
	Log(msg string, tp ...string)
	GetPluginId() string
}
