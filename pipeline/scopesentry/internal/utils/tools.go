// utils-------------------------------------
// @file      : tools.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/22 20:24
// -------------------------------------------

package utils

import "gopkg.in/yaml.v3"

func Unmarshal(in []byte, out interface{}) (err error) {
	return yaml.Unmarshal(in, out)
}

func Marshal(in interface{}) (out []byte, err error) {
	return yaml.Marshal(in)
}
