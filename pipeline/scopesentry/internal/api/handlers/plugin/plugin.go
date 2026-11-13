package plugin

import (
	"github.com/Autumn-27/ScopeSentry/internal/api/response"
	"github.com/Autumn-27/ScopeSentry/internal/models"
	"github.com/Autumn-27/ScopeSentry/internal/services/plugin"
	"github.com/Autumn-27/ScopeSentry/internal/utils/random"
	"github.com/gin-gonic/gin"
)

var pluginService plugin.Service

func init() {
	pluginService = plugin.NewService()
}

// List 获取插件列表
// @Summary 获取插件列表
// @Description 分页获取插件列表
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body plugin.PluginListRequest true "请求参数"
// @Success 200 {object} response.Response{data=plugin.PluginListResponse}
// @Router /api/plugin [post]
func List(c *gin.Context) {
	var req models.PluginListRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	result, err := pluginService.List(c, &req)
	if err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, result, "api.success")
}

// ListByModule 根据模块获取插件列表
// @Summary 根据模块获取插件列表
// @Description 获取指定模块的插件列表
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body map[string]string true "请求参数"
// @Success 200 {object} response.Response{data=[]plugin.Plugin}
// @Router /api/plugin/module [post]
func ListByModule(c *gin.Context) {
	var req struct {
		Module string `json:"module" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	result, err := pluginService.ListByModule(c, req.Module)
	if err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, map[string]interface{}{
		"list": result,
	}, "api.success")
}

// Detail 获取插件详情
// @Summary 获取插件详情
// @Description 获取指定插件的详细信息
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body plugin.PluginDetailRequest true "请求参数"
// @Success 200 {object} response.Response{data=plugin.Plugin}
// @Router /api/plugin/detail [post]
func Detail(c *gin.Context) {
	var req models.PluginDetailRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	result, err := pluginService.Detail(c, &req)
	if err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, result, "api.success")
}

// Save 保存插件
// @Summary 保存插件
// @Description 创建或更新插件
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body plugin.PluginSaveRequest true "请求参数"
// @Success 200 {object} response.Response
// @Router /api/plugin/save [post]
func Save(c *gin.Context) {
	var req models.PluginSaveRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	if err := pluginService.Save(c, &req); err != nil {
		response.InternalServerError(c, "api.plugin.key.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}

// Delete 删除插件
// @Summary 删除插件
// @Description 删除指定的插件
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body plugin.PluginDeleteRequest true "请求参数"
// @Success 200 {object} response.Response
// @Router /api/plugin/delete [post]
func Delete(c *gin.Context) {
	var req models.PluginDeleteRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	if err := pluginService.Delete(c, &req); err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}

// GetLogs 获取插件日志
// @Summary 获取插件日志
// @Description 获取指定插件的日志
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body plugin.PluginLogRequest true "请求参数"
// @Success 200 {object} response.Response{data=string}
// @Router /api/plugin/log [post]
func GetLogs(c *gin.Context) {
	var req models.PluginLogRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	result, err := pluginService.GetLogs(c, &req)
	if err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, gin.H{
		"data": result,
	}, "api.success")
}

// CleanLogs 清理插件日志
// @Summary 清理插件日志
// @Description 清理指定插件的日志
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body plugin.PluginLogRequest true "请求参数"
// @Success 200 {object} response.Response
// @Router /api/plugin/log/clean [post]
func CleanLogs(c *gin.Context) {
	var req models.PluginLogRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	if err := pluginService.CleanLogs(c, &req); err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}

// CleanAllLogs 清除所有插件日志
// @Summary 清除所有插件日志
// @Description 清除所有插件的日志
// @Tags 插件管理
// @Accept json
// @Produce json
// @Success 200 {object} response.Response
// @Router /api/plugin/log/clean/all [post]
func CleanAllLogs(c *gin.Context) {
	if err := pluginService.CleanAllLogs(c); err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}

// Import 导入插件
// @Summary 导入插件
// @Description 导入新的插件
// @Tags 插件管理
// @Accept multipart/form-data
// @Produce json
// @Param file formData file true "插件文件"
// @Param key query string true "插件密钥"
// @Success 200 {object} response.Response
// @Router /api/plugin/import [post]
func Import(c *gin.Context) {
	file, err := c.FormFile("file")
	if err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	key := c.Query("key")
	if key == "" {
		response.BadRequest(c, "api.bad_request", nil)
		return
	}
	// 保存上传的文件
	filePath := "uploads/" + random.GenerateString(5) + ".zip"
	if err := c.SaveUploadedFile(file, filePath); err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	if err := pluginService.Import(c, filePath, key); err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}

// Reinstall 重装插件
// @Summary 重装插件
// @Description 重装指定的插件
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body plugin.PluginReinstallRequest true "请求参数"
// @Success 200 {object} response.Response
// @Router /api/plugin/reinstall [post]
func Reinstall(c *gin.Context) {
	var req models.PluginReinstallRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	if err := pluginService.Reinstall(c, &req); err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}

// Recheck 重检插件
// @Summary 重检插件
// @Description 重新检查指定的插件
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body plugin.PluginRecheckRequest true "请求参数"
// @Success 200 {object} response.Response
// @Router /api/plugin/recheck [post]
func Recheck(c *gin.Context) {
	var req models.PluginRecheckRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	if err := pluginService.Recheck(c, &req); err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}

// Uninstall 卸载插件
// @Summary 卸载插件
// @Description 卸载指定的插件
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body plugin.PluginUninstallRequest true "请求参数"
// @Success 200 {object} response.Response
// @Router /api/plugin/uninstall [post]
func Uninstall(c *gin.Context) {
	var req models.PluginUninstallRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	if err := pluginService.Uninstall(c, &req); err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}

// CheckKey 检查插件密钥
// @Summary 检查插件密钥
// @Description 检查插件密钥是否有效
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body plugin.PluginKeyCheckRequest true "请求参数"
// @Success 200 {object} response.Response
// @Router /api/plugin/key/check [post]
func CheckKey(c *gin.Context) {
	var req models.PluginKeyCheckRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	if err := pluginService.CheckKey(c, &req); err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}

// SearchRemotePlugins 搜索远程插件
// @Summary 搜索远程插件
// @Description 获取远程插件列表，并标记已安装和需要更新的插件
// @Tags 插件管理
// @Accept json
// @Produce json
// @Success 200 {object} response.Response{data=map[string]interface{}}
// @Router /api/plugin/remote/search [post]
func SearchRemotePlugins(c *gin.Context) {
	result, err := pluginService.SearchRemotePlugins(c)
	if err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, result, "api.success")
}

// ImportByData 通过POST JSON数据导入插件
// @Summary 通过POST JSON数据导入插件
// @Description 通过POST传输JSON数据导入插件，包含info.json的序列化字符串、source字段和isSystem字段
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body models.PluginImportByDataRequest true "请求参数"
// @Success 200 {object} response.Response
// @Router /api/plugin/import/data [post]
func ImportByData(c *gin.Context) {
	var req models.PluginImportByDataRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	if err := pluginService.ImportByData(c, &req); err != nil {
		response.InternalServerError(c, "api.plugin.key.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}

// Status 更新插件状态
// @Summary 更新插件状态
// @Description 更新指定插件的启用/禁用状态
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body models.PluginStatusRequest true "请求参数"
// @Success 200 {object} response.Response
// @Router /api/plugin/status [post]
func Status(c *gin.Context) {
	var req models.PluginStatusRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	if err := pluginService.UpdateStatus(c, &req); err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}

// Run 运行插件一次
// @Summary 运行插件一次
// @Description 手动触发执行指定的服务端插件
// @Tags 插件管理
// @Accept json
// @Produce json
// @Param request body models.PluginRunRequest true "请求参数"
// @Success 200 {object} response.Response
// @Router /api/plugin/run [post]
func Run(c *gin.Context) {
	var req models.PluginRunRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "api.bad_request", err)
		return
	}

	if err := pluginService.Run(c, &req); err != nil {
		response.InternalServerError(c, "api.error", err)
		return
	}

	response.Success(c, nil, "api.success")
}
