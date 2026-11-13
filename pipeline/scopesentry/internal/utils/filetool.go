// utils-------------------------------------
// @file      : filetool.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/5/25 15:54
// -------------------------------------------

package utils

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

func EnsureDir(path string) error {
	// 检查路径状态
	info, err := os.Stat(path)

	// 如果路径不存在
	if os.IsNotExist(err) {
		// 自动创建多层目录
		err := os.MkdirAll(path, 0755)
		if err != nil {
			return fmt.Errorf("创建目录失败: %w", err)
		}
		return nil
	}

	// 路径存在，但不是目录
	if err == nil && !info.IsDir() {
		return fmt.Errorf("路径已存在但不是目录: %s", path)
	}

	// 已存在且是目录
	return nil
}

func WriteFile(filePath string, content []byte) error {
	// os.Create 会清空已存在的文件内容，相当于覆盖写
	file, err := os.Create(filePath)
	if err != nil {
		return fmt.Errorf("创建文件失败: %w", err)
	}
	defer file.Close()

	// 写入内容
	_, err = file.Write(content)
	if err != nil {
		return fmt.Errorf("写入文件失败: %w", err)
	}

	return nil
}

func DownloadFile(url string, savePath string, timeout time.Duration) error {
	// 创建目录
	if err := os.MkdirAll(filepath.Dir(savePath), os.ModePerm); err != nil {
		return err
	}

	client := &http.Client{
		Timeout: timeout, // 整体超时（连接 + 下载）
	}

	resp, err := client.Get(url)
	if err != nil {
		return fmt.Errorf("请求失败: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP 状态码异常: %d", resp.StatusCode)
	}

	out, err := os.Create(savePath)
	if err != nil {
		return err
	}
	defer out.Close()

	_, err = io.Copy(out, resp.Body)
	return err
}

func DeleteFile(filePath string) {
	// 检查文件是否存在
	if filePath == "" {
		return
	}
	if _, err := os.Stat(filePath); os.IsNotExist(err) {
		return
	} else if err != nil {
		return
	}

	// 文件存在，进行删除
	err := os.Remove(filePath)
	if err != nil {
		return
	}
}
