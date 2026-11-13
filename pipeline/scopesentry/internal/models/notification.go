// models-------------------------------------
// @file      : notification.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/22 22:09
// -------------------------------------------

package models

type NotificationApi struct {
	Url         string `bson:"url"`
	Method      string `bson:"method"`
	ContentType string `bson:"contentType"`
	Data        string `bson:"data"`
	State       bool   `bson:"state"`
}
