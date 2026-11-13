// helper-------------------------------------
// @file      : fofa.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/21 19:39
// -------------------------------------------

package helper

import (
	"fmt"
	"regexp"
	"strings"
)

// convertFofaToCustomQuery 将 fofa-query 转换成项目自定义的搜索语句
func ConvertFofaToCustomQuery(fofaQueryValue interface{}) string {
	var queries []string

	// 处理数组类型
	if arr, ok := fofaQueryValue.([]interface{}); ok {
		for _, item := range arr {
			if str, ok := item.(string); ok {
				converted := parseFofaQuery(str)
				if converted != "" {
					queries = append(queries, converted)
				}
			}
		}
		// 多个条件用 && 连接
		if len(queries) > 0 {
			return strings.Join(queries, " && ")
		}
		return ""
	}

	// 处理字符串类型
	if str, ok := fofaQueryValue.(string); ok {
		return parseFofaQuery(str)
	}

	return ""
}

// parseFofaQuery 解析 fofa 查询语句，支持括号和逻辑连接符
func parseFofaQuery(query string) string {
	query = strings.TrimSpace(query)
	if query == "" {
		return ""
	}

	// 先处理括号，递归解析
	return parseFofaQueryWithBrackets(query)
}

// parseFofaQueryWithBrackets 解析带括号的 fofa 查询
func parseFofaQueryWithBrackets(query string) string {
	query = strings.TrimSpace(query)
	if query == "" {
		return ""
	}

	// 查找并替换所有括号内的内容
	for {
		// 查找最外层的左括号
		start := strings.Index(query, "(")
		if start == -1 {
			// 没有括号了，解析逻辑表达式
			break
		}

		// 找到匹配的右括号
		depth := 0
		end := -1
		for i := start; i < len(query); i++ {
			if query[i] == '(' {
				depth++
			} else if query[i] == ')' {
				depth--
				if depth == 0 {
					end = i
					break
				}
			}
		}

		if end == -1 {
			// 括号不匹配，跳出循环，当作普通查询处理
			break
		}

		// 递归解析括号内的内容
		innerQuery := query[start+1 : end]
		parsedInner := parseFofaQueryWithBrackets(innerQuery)

		// 替换括号内容为解析后的结果
		query = query[:start] + "(" + parsedInner + ")" + query[end+1:]
	}

	// 所有括号都处理完了，解析逻辑表达式
	return parseFofaLogicExpression(query)
}

// parseFofaLogicExpression 解析逻辑表达式（处理 && 和 ||）
func parseFofaLogicExpression(query string) string {
	query = strings.TrimSpace(query)
	if query == "" {
		return ""
	}

	// 按 || 分割（优先级最低）
	if strings.Contains(query, " || ") {
		parts := splitByOperator(query, " || ")
		var results []string
		for _, part := range parts {
			parsed := parseFofaLogicExpression(strings.TrimSpace(part))
			if parsed != "" {
				results = append(results, parsed)
			}
		}
		if len(results) > 0 {
			return strings.Join(results, " || ")
		}
		return ""
	}

	// 按 && 分割
	if strings.Contains(query, " && ") {
		parts := splitByOperator(query, " && ")
		var results []string
		for _, part := range parts {
			parsed := parseFofaLogicExpression(strings.TrimSpace(part))
			if parsed != "" {
				results = append(results, parsed)
			}
		}
		if len(results) > 0 {
			return strings.Join(results, " && ")
		}
		return ""
	}

	// 没有逻辑连接符，解析单个条件
	return parseFofaCondition(query)
}

// splitByOperator 按操作符分割，但要注意括号内的内容
func splitByOperator(query, operator string) []string {
	var parts []string
	var current strings.Builder
	depth := 0

	for i := 0; i < len(query); i++ {
		if query[i] == '(' {
			depth++
			current.WriteByte(query[i])
		} else if query[i] == ')' {
			depth--
			current.WriteByte(query[i])
		} else if depth == 0 && i+len(operator) <= len(query) && query[i:i+len(operator)] == operator {
			parts = append(parts, current.String())
			current.Reset()
			i += len(operator) - 1 // 跳过操作符
		} else {
			current.WriteByte(query[i])
		}
	}

	if current.Len() > 0 {
		parts = append(parts, current.String())
	}

	return parts
}

// parseFofaCondition 解析单个 fofa 条件
func parseFofaCondition(condition string) string {
	condition = strings.TrimSpace(condition)
	if condition == "" {
		return ""
	}

	// 移除括号（如果整个条件被括号包围）
	condition = strings.Trim(condition, "()")
	condition = strings.TrimSpace(condition)

	// 定义 fofa 字段映射（fofa字段 -> 自定义字段）
	fieldMap := map[string]string{
		"app":           "app",
		"title":         "title",
		"body":          "body",
		"header":        "header",
		"icon_hash":     "icon",
		"protocol":      "service",
		"banner":        "banner",
		"banner_hash":   "banner",
		"base_protocol": "service",
		"status_code":   "statuscode",
		"js_name":       "body",
	}

	// 匹配 fofa 查询格式，支持 =, ==, !=, *=
	// 按优先级排序：==, *=, =, !=
	patterns := []struct {
		regex   *regexp.Regexp
		opIndex int // 0: ==, 1: *=, 2: =, 3: !=
	}{
		// 匹配 field=="value" 或 field=='value' (完全匹配，带引号)
		{regexp.MustCompile(`^(\w+)\s*==\s*["']([^"']*)["']$`), 0},
		// 匹配 field*="value" 或 field*='value' (模糊匹配，带引号)
		{regexp.MustCompile(`^(\w+)\s*\*=\s*["']([^"']*)["']$`), 1},
		// 匹配 field="value" 或 field='value' (匹配，带引号)
		{regexp.MustCompile(`^(\w+)\s*=\s*["']([^"']*)["']$`), 2},
		// 匹配 field!="value" 或 field!='value' (不匹配，带引号)
		{regexp.MustCompile(`^(\w+)\s*!=\s*["']([^"']*)["']$`), 3},
		// 匹配 field==value (完全匹配，无引号)
		{regexp.MustCompile(`^(\w+)\s*==\s*(.+)$`), 0},
		// 匹配 field*=value (模糊匹配，无引号)
		{regexp.MustCompile(`^(\w+)\s*\*=\s*(.+)$`), 1},
		// 匹配 field=value (匹配，无引号)
		{regexp.MustCompile(`^(\w+)\s*=\s*(.+)$`), 2},
		// 匹配 field!=value (不匹配，无引号)
		{regexp.MustCompile(`^(\w+)\s*!=\s*(.+)$`), 3},
	}

	operators := []string{"==", "=", "=", "!="} // *= 转为 =

	for _, pattern := range patterns {
		matches := pattern.regex.FindStringSubmatch(condition)
		if len(matches) == 3 {
			field := strings.ToLower(matches[1])
			value := strings.TrimSpace(matches[2])
			// 移除值两端的引号（如果存在）
			value = strings.Trim(value, `"'`)

			// 检查字段是否在映射中
			customField, exists := fieldMap[field]
			if !exists {
				// 如果字段不在映射中，默认使用 body
				customField = "body"
			}

			operator := operators[pattern.opIndex]
			return fmt.Sprintf(`%s%s"%s"`, customField, operator, value)
		}
	}

	// 如果没有匹配到任何模式，检查是否包含已知字段名
	hasKnownField := false
	lowerCondition := strings.ToLower(condition)
	for field := range fieldMap {
		if strings.HasPrefix(lowerCondition, field+"=") ||
			strings.HasPrefix(lowerCondition, field+"==") ||
			strings.HasPrefix(lowerCondition, field+"!=") ||
			strings.HasPrefix(lowerCondition, field+"*=") {
			hasKnownField = true
			break
		}
	}

	// 如果不包含已知字段，默认作为 body 查询
	if !hasKnownField && condition != "" {
		// 移除可能的引号
		value := strings.Trim(condition, `"'`)
		// 如果值以 = 开头，移除它
		value = strings.TrimPrefix(value, "=")
		value = strings.TrimPrefix(value, "==")
		value = strings.TrimPrefix(value, "!=")
		value = strings.TrimPrefix(value, "*=")
		value = strings.TrimSpace(value)
		if value != "" {
			return fmt.Sprintf(`body="%s"`, value)
		}
	}

	return ""
}
