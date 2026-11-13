// symbols-------------------------------------
// @file      : symbols.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/6 15:54
// -------------------------------------------

//go:generate yaegi extract github.com/Autumn-27/ScopeSentry/internal/options
//go:generate yaegi extract github.com/Autumn-27/ScopeSentry/internal/utils
//go:generate yaegi extract github.com/Autumn-27/ScopeSentry/internal/utils/ct
//go:generate yaegi extract github.com/Autumn-27/ScopeSentry/internal/utils/ct/models
//go:generate yaegi extract github.com/Autumn-27/ScopeSentry/internal/utils/ct/types
//go:generate yaegi extract github.com/Autumn-27/ScopeSentry/internal/utils/random
//go:generate yaegi extract github.com/Autumn-27/ScopeSentry/internal/utils/helper
//go:generate yaegi extract github.com/Autumn-27/ScopeSentry/internal/models
//go:generate yaegi extract go.mongodb.org/mongo-driver/bson
//go:generate yaegi extract go.mongodb.org/mongo-driver/bson/primitive
//go:generate yaegi extract go.mongodb.org/mongo-driver/mongo
//go:generate yaegi extract go.mongodb.org/mongo-driver/mongo/options
package symbols

import (
	"github.com/traefik/yaegi/stdlib"
	"reflect"
)

var Symbols = map[string]map[string]reflect.Value{}

func init() {
	// 注册常用标准库
	for pkg, symbols := range map[string]string{
		"os/exec": "os/exec",
	} {
		Symbols[pkg] = stdlib.Symbols[symbols]
	}
}
