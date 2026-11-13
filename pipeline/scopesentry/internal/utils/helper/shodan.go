// helper-------------------------------------
// @file      : shodan.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/21 19:47
// -------------------------------------------

package helper

import (
	"fmt"
	"regexp"
	"strings"
)

// ConvertShodanToCustomQuery 将 shodan 查询语句转换成项目自定义的搜索语句
func ConvertShodanToCustomQuery(shodanQueryValue interface{}) string {
	var queries []string

	// 处理数组类型
	if arr, ok := shodanQueryValue.([]interface{}); ok {
		for _, item := range arr {
			if str, ok := item.(string); ok {
				converted := parseShodanQuery(str)
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
	if str, ok := shodanQueryValue.(string); ok {
		return parseShodanQuery(str)
	}

	return ""
}

// parseShodanQuery 解析 shodan 查询语句，支持括号和逻辑连接符
func parseShodanQuery(query string) string {
	query = strings.TrimSpace(query)
	if query == "" {
		return ""
	}

	// 先处理括号，递归解析
	return parseShodanQueryWithBrackets(query)
}

// parseShodanQueryWithBrackets 解析带括号的 shodan 查询
func parseShodanQueryWithBrackets(query string) string {
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
		parsedInner := parseShodanQueryWithBrackets(innerQuery)

		// 替换括号内容为解析后的结果
		query = query[:start] + "(" + parsedInner + ")" + query[end+1:]
	}

	// 所有括号都处理完了，解析逻辑表达式
	return parseShodanLogicExpression(query)
}

// parseShodanLogicExpression 解析逻辑表达式（处理 AND、OR、NOT）
func parseShodanLogicExpression(query string) string {
	query = strings.TrimSpace(query)
	if query == "" {
		return ""
	}

	// 按 || 分割（优先级最低，符号形式）
	if hasOperator(query, "||") {
		parts := splitByShodanOperatorSymbol(query, "||")
		var results []string
		for _, part := range parts {
			parsed := parseShodanLogicExpression(strings.TrimSpace(part))
			if parsed != "" {
				results = append(results, parsed)
			}
		}
		if len(results) > 0 {
			return strings.Join(results, " || ")
		}
		return ""
	}

	// 按 OR 分割（优先级最低，需要处理大小写，文本形式）
	if strings.Contains(strings.ToUpper(query), " OR ") {
		parts := splitByShodanOperator(query, " OR ")
		var results []string
		for _, part := range parts {
			parsed := parseShodanLogicExpression(strings.TrimSpace(part))
			if parsed != "" {
				results = append(results, parsed)
			}
		}
		if len(results) > 0 {
			return strings.Join(results, " || ")
		}
		return ""
	}

	// 按 && 分割（符号形式）
	if hasOperator(query, "&&") {
		parts := splitByShodanOperatorSymbol(query, "&&")
		var results []string
		for _, part := range parts {
			parsed := parseShodanLogicExpression(strings.TrimSpace(part))
			if parsed != "" {
				results = append(results, parsed)
			}
		}
		if len(results) > 0 {
			return strings.Join(results, " && ")
		}
		return ""
	}

	// 按 AND 分割（需要处理大小写和空格，文本形式）
	if strings.Contains(strings.ToUpper(query), " AND ") {
		parts := splitByShodanOperator(query, " AND ")
		var results []string
		for _, part := range parts {
			parsed := parseShodanLogicExpression(strings.TrimSpace(part))
			if parsed != "" {
				results = append(results, parsed)
			}
		}
		if len(results) > 0 {
			return strings.Join(results, " && ")
		}
		return ""
	}

	// 没有逻辑连接符，解析单个条件（可能包含多个空格分隔的过滤器，默认是 AND）
	return parseShodanFilters(query)
}

// splitByShodanOperator 按操作符分割，但要注意括号内的内容和大小写
func splitByShodanOperator(query, operator string) []string {
	var parts []string
	var current strings.Builder
	depth := 0
	operatorUpper := strings.ToUpper(operator)
	operatorLen := len(operator)

	for i := 0; i < len(query); i++ {
		if query[i] == '(' {
			depth++
			current.WriteByte(query[i])
		} else if query[i] == ')' {
			depth--
			current.WriteByte(query[i])
		} else if depth == 0 {
			// 检查是否匹配操作符（不区分大小写）
			if i+operatorLen <= len(query) {
				substr := strings.ToUpper(query[i : i+operatorLen])
				if substr == operatorUpper {
					parts = append(parts, current.String())
					current.Reset()
					i += operatorLen - 1 // 跳过操作符
					continue
				}
			}
			current.WriteByte(query[i])
		} else {
			current.WriteByte(query[i])
		}
	}

	if current.Len() > 0 {
		parts = append(parts, current.String())
	}

	return parts
}

// hasOperator 检查查询中是否包含操作符（不在引号内）
func hasOperator(query, operator string) bool {
	inQuotes := false
	quoteChar := byte(0)
	depth := 0

	for i := 0; i <= len(query)-len(operator); i++ {
		char := query[i]

		// 处理引号
		if (char == '"' || char == '\'') && (i == 0 || query[i-1] != '\\') {
			if !inQuotes {
				inQuotes = true
				quoteChar = char
			} else if char == quoteChar {
				inQuotes = false
				quoteChar = 0
			}
			continue
		}

		// 如果在引号内，跳过
		if inQuotes {
			continue
		}

		// 处理括号深度
		if char == '(' {
			depth++
			continue
		} else if char == ')' {
			depth--
			continue
		}

		// 检查操作符（不在引号内，不在括号内）
		if depth == 0 && query[i:i+len(operator)] == operator {
			return true
		}
	}

	return false
}

// splitByShodanOperatorSymbol 按符号操作符（如 || 或 &&）分割，但要注意括号和引号内的内容
func splitByShodanOperatorSymbol(query, operator string) []string {
	var parts []string
	var current strings.Builder
	depth := 0
	inQuotes := false
	quoteChar := byte(0)
	operatorLen := len(operator)

	for i := 0; i < len(query); i++ {
		char := query[i]

		// 处理引号
		if (char == '"' || char == '\'') && (i == 0 || query[i-1] != '\\') {
			if !inQuotes {
				inQuotes = true
				quoteChar = char
			} else if char == quoteChar {
				inQuotes = false
				quoteChar = 0
			}
			current.WriteByte(char)
			continue
		}

		// 如果在引号内，直接添加字符
		if inQuotes {
			current.WriteByte(char)
			continue
		}

		// 处理括号
		if char == '(' {
			depth++
			current.WriteByte(char)
		} else if char == ')' {
			depth--
			current.WriteByte(char)
		} else if depth == 0 {
			// 检查是否匹配操作符（不在引号内，不在括号内）
			if i+operatorLen <= len(query) && query[i:i+operatorLen] == operator {
				parts = append(parts, current.String())
				current.Reset()
				i += operatorLen - 1 // 跳过操作符
				continue
			}
			current.WriteByte(char)
		} else {
			current.WriteByte(char)
		}
	}

	if current.Len() > 0 {
		parts = append(parts, current.String())
	}

	return parts
}

// parseShodanFilters 解析 shodan 过滤器（可能包含多个空格分隔的过滤器）
func parseShodanFilters(query string) string {
	query = strings.TrimSpace(query)
	if query == "" {
		return ""
	}

	// 移除括号（如果整个查询被括号包围）
	query = strings.Trim(query, "()")
	query = strings.TrimSpace(query)

	// 分割过滤器（按空格，但要考虑引号内的内容）
	filters := splitShodanFilters(query)
	if len(filters) == 0 {
		return ""
	}

	var results []string
	for _, filter := range filters {
		filter = strings.TrimSpace(filter)
		if filter == "" {
			continue
		}
		parsed := parseShodanFilter(filter)
		if parsed != "" {
			results = append(results, parsed)
		}
	}

	if len(results) == 0 {
		return ""
	}

	// 多个过滤器用 && 连接
	if len(results) == 1 {
		return results[0]
	}
	return strings.Join(results, " && ")
}

// splitShodanFilters 分割 shodan 过滤器，考虑引号内的内容
// 注意：此函数只处理空格分隔的过滤器，OR 和 AND 已经在 parseShodanLogicExpression 中处理
func splitShodanFilters(query string) []string {
	var filters []string
	var current strings.Builder
	inQuotes := false
	quoteChar := byte(0)

	for i := 0; i < len(query); i++ {
		char := query[i]

		// 处理引号
		if (char == '"' || char == '\'') && (i == 0 || query[i-1] != '\\') {
			if !inQuotes {
				inQuotes = true
				quoteChar = char
				current.WriteByte(char)
			} else if char == quoteChar {
				inQuotes = false
				quoteChar = 0
				current.WriteByte(char)
			} else {
				current.WriteByte(char)
			}
			continue
		}

		// 如果在引号内，直接添加字符
		if inQuotes {
			current.WriteByte(char)
			continue
		}

		// 空格分隔（但不在引号内）
		if char == ' ' {
			if current.Len() > 0 {
				filters = append(filters, current.String())
				current.Reset()
			}
			continue
		}

		current.WriteByte(char)
	}

	if current.Len() > 0 {
		filters = append(filters, current.String())
	}

	return filters
}

// parseShodanFilter 解析单个 shodan 过滤器
func parseShodanFilter(filter string) string {
	filter = strings.TrimSpace(filter)
	if filter == "" {
		return ""
	}

	// 定义 shodan 字段映射（shodan字段 -> 自定义字段）
	fieldMap := map[string]string{
		"http.title":        "title",
		"http.html":         "body",
		"http.component":    "app",
		"http.server":       "header",
		"http.favicon.hash": "icon",
		"http.status":       "statuscode",
		"title":             "title",
		"html":              "body",
		"component":         "app",
		"server":            "header",
		"favicon.hash":      "icon",
		"status":            "statuscode",
	}

	// 检查是否是 NOT 查询（以 - 开头或 NOT 开头，不区分大小写）
	isNot := false
	if strings.HasPrefix(filter, "-") {
		isNot = true
		filter = strings.TrimPrefix(filter, "-")
		filter = strings.TrimSpace(filter)
	} else {
		// 检查是否以 NOT 开头（不区分大小写）
		filterUpper := strings.ToUpper(filter)
		if strings.HasPrefix(filterUpper, "NOT ") {
			isNot = true
			// 找到原始字符串中 NOT 的位置（不区分大小写）
			notIndex := strings.Index(filterUpper, "NOT ")
			if notIndex == 0 {
				filter = filter[4:] // 移除 "NOT " (4个字符)
				filter = strings.TrimSpace(filter)
			}
		}
	}

	// 匹配 shodan 过滤器格式: filter:value 或 "filter:value"
	// 支持带引号的值
	pattern := regexp.MustCompile(`^([\w.]+)\s*:\s*(.+)$`)
	matches := pattern.FindStringSubmatch(filter)
	if len(matches) == 3 {
		field := strings.ToLower(matches[1])
		value := strings.TrimSpace(matches[2])

		// 如果字段是 country，直接跳过（不支持 country 字段）
		if field == "country" {
			return ""
		}

		// 移除值两端的引号（如果存在）
		value = strings.Trim(value, `"'`)

		// 检查字段是否在映射中
		customField, exists := fieldMap[field]
		if !exists {
			// 如果字段不在映射中，默认使用 body
			customField = "body"
		}

		// 根据是否是 NOT 查询选择操作符
		operator := "="
		if isNot {
			operator = "!="
		}

		return fmt.Sprintf(`%s%s"%s"`, customField, operator, value)
	}

	// 如果没有匹配到过滤器格式，检查是否是纯文本查询
	// 纯文本查询默认作为 body 查询
	if !strings.Contains(filter, ":") {
		value := strings.Trim(filter, `"'`)
		operator := "="
		if isNot {
			operator = "!="
		}
		return fmt.Sprintf(`body%s"%s"`, operator, value)
	}

	return ""
}
