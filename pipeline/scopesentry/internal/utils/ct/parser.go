// ct-----------------------------------------
// @file      : parser.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/01/24 21:00
// -------------------------------------------
// CT日志监听SDK - 流式证书解析器
// ============================================

package ct

import (
	"crypto/sha256"
	"fmt"
	"strings"
	"time"

	"github.com/Autumn-27/ScopeSentry/internal/utils/ct/models"
	"github.com/google/certificate-transparency-go/x509"
)

// CertificateParser 证书解析器（流式处理）
type CertificateParser struct {
	// 解析选项
	maxDomains int // 最大域名数量限制
}

// NewCertificateParser 创建新的证书解析器
func NewCertificateParser() *CertificateParser {
	return &CertificateParser{
		maxDomains: 100, // 默认最大100个域名
	}
}

// ParseCertificateStream 流式解析证书（核心方法）
// 只提取必要信息，不存储证书内容
func (p *CertificateParser) ParseCertificateStream(rawData []byte, index int64, timestamp time.Time, logURL string) (*models.CertInfo, error) {
	if len(rawData) == 0 {
		return nil, fmt.Errorf("证书数据为空")
	}

	certInfo := &models.CertInfo{
		LogURL:    logURL,
		Index:     index,
		Timestamp: timestamp,
	}

	// 快速提取域名（这是最重要的信息）
	domains, err := p.ExtractDomainsFast(rawData)
	if err != nil {
		// 域名提取失败，但不影响继续处理
		domains = []string{}
	}

	// 限制域名数量
	if len(domains) > p.maxDomains {
		domains = domains[:p.maxDomains]
	}

	certInfo.AllDomains = domains

	// 尝试提取CN（Common Name）
	if len(domains) > 0 {
		certInfo.CommonName = domains[0]
	}

	return certInfo, nil
}

// ExtractDomainsFast 快速提取证书中的域名
// 使用Google CT库的x509解析器，提供更好的CT日志证书支持
func (p *CertificateParser) ExtractDomainsFast(certData []byte) ([]string, error) {
	domains := make([]string, 0, 10)

	// 解析X.509证书（使用Google CT库的x509解析器）
	cert, err := x509.ParseCertificate(certData)
	if err != nil {
		// 如果解析失败，回退到模式匹配
		return p.extractDomainsFromPatterns(certData), nil
	}

	// 从DNSNames获取域名（Subject Alternative Name扩展）
	// 确保DNSNames不为nil（nil值在JSON序列化时会成为null）
	if cert.DNSNames != nil {
		domains = append(domains, cert.DNSNames...)
	}

	// 处理Common Name（如果不是CA证书且CN不为空）
	if cert.Subject.CommonName != "" && !cert.IsCA {
		// 检查CN是否已经在域名列表中
		cnAlreadyAdded := false
		for _, domain := range domains {
			if domain == cert.Subject.CommonName {
				cnAlreadyAdded = true
				break
			}
		}

		// 如果CN不在列表中，添加它
		if !cnAlreadyAdded {
			domains = append(domains, cert.Subject.CommonName)
		}
	}

	// 验证和清理域名
	validDomains := make([]string, 0, len(domains))
	for _, domain := range domains {
		if p.isValidDomain(domain) {
			validDomains = append(validDomains, strings.ToLower(strings.TrimSpace(domain)))
		}
	}

	// 去重
	validDomains = p.deduplicateDomains(validDomains)

	return validDomains, nil
}

// extractDomainsFromPatterns 通过模式匹配提取域名（回退方案）
// 当标准X.509解析失败时使用
func (p *CertificateParser) extractDomainsFromPatterns(data []byte) []string {
	domains := make([]string, 0, 10)
	dataStr := string(data)

	// 常见的域名分隔符和模式
	separators := []string{"\x00", "\n", "\r", "\t", " ", ",", ";", "|"}

	for _, sep := range separators {
		parts := strings.Split(dataStr, sep)
		for _, part := range parts {
			if p.isValidDomain(part) {
				domains = append(domains, strings.ToLower(strings.TrimSpace(part)))
			}
		}
	}

	// 去重
	domains = p.deduplicateDomains(domains)

	return domains
}

// isValidDomain 验证域名格式
func (p *CertificateParser) isValidDomain(s string) bool {
	s = strings.TrimSpace(s)
	if len(s) < 4 || len(s) > 253 { // 域名长度限制
		return false
	}

	// 必须包含点
	if !strings.Contains(s, ".") {
		return false
	}

	// 检查字符合法性（域名允许的字符）
	for _, r := range s {
		if !(r >= 'a' && r <= 'z') && !(r >= 'A' && r <= 'Z') &&
			!(r >= '0' && r <= '9') && r != '.' && r != '-' {
			return false
		}
	}

	// 检查TLD（顶级域名）
	parts := strings.Split(s, ".")
	if len(parts) < 2 {
		return false
	}

	tld := parts[len(parts)-1]
	if len(tld) < 2 || len(tld) > 6 {
		return false
	}

	return true
}

// deduplicateDomains 去重域名列表
func (p *CertificateParser) deduplicateDomains(domains []string) []string {
	seen := make(map[string]bool)
	result := make([]string, 0, len(domains))

	for _, domain := range domains {
		domain = strings.ToLower(strings.TrimSpace(domain))
		if domain != "" && !seen[domain] {
			seen[domain] = true
			result = append(result, domain)
		}
	}

	return result
}

// CalculateCertHash 计算证书哈希（用于去重）
func (p *CertificateParser) CalculateCertHash(certData []byte) string {
	hash := sha256.Sum256(certData)
	return fmt.Sprintf("%x", hash)
}

// ValidateCertificateData 验证证书数据格式
func (p *CertificateParser) ValidateCertificateData(data []byte) error {
	if len(data) < 100 {
		return fmt.Errorf("证书数据太小")
	}

	if len(data) > 100*1024 { // 100KB限制
		return fmt.Errorf("证书数据太大")
	}

	// 检查是否可能是DER编码的证书
	if data[0] != 0x30 {
		return fmt.Errorf("不是有效的DER编码证书")
	}

	return nil
}

// GetParserStats 获取解析器统计信息
func (p *CertificateParser) GetParserStats() *ParserStats {
	return &ParserStats{
		MaxDomains: p.maxDomains,
	}
}

// ParserStats 解析器统计信息
type ParserStats struct {
	MaxDomains      int   `json:"max_domains"`
	TotalParsed     int64 `json:"total_parsed"`
	ParseErrors     int64 `json:"parse_errors"`
	DomainExtracted int64 `json:"domain_extracted"`
}

// StreamProcessor 流处理器
type StreamProcessor struct {
	parser   *CertificateParser
	matcher  *DomainMatcher
	eventBus *models.EventBus

	// 处理统计
	stats struct {
		totalProcessed int64
		totalMatched   int64
		totalErrors    int64
	}
}

// NewStreamProcessor 创建新的流处理器
func NewStreamProcessor(matcher *DomainMatcher, eventBus *models.EventBus) *StreamProcessor {
	return &StreamProcessor{
		parser:   NewCertificateParser(),
		matcher:  matcher,
		eventBus: eventBus,
	}
}

// ProcessCertificate 处理单个证书（流式）
func (sp *StreamProcessor) ProcessCertificate(rawData []byte, index int64, timestamp time.Time, logURL string) error {
	// 解析证书信息
	certInfo, err := sp.parser.ParseCertificateStream(rawData, index, timestamp, logURL)
	if err != nil {
		sp.stats.totalErrors++
		return fmt.Errorf("解析证书失败: %w", err)
	}

	sp.stats.totalProcessed++

	// 发布证书处理事件
	certEvent := &models.CertificateProcessedEvent{
		BaseEvent: models.BaseEvent{
			Type:      models.EventTypeCertificateProcessed,
			ID:        models.GenerateEventID(),
			Timestamp: time.Now(),
		},
		Certificate:    certInfo,
		ProcessingTime: 0, // 可以后续添加处理时间统计
		Success:        true,
		Error:          "",
	}

	// 异步发布证书处理事件
	go func(evt *models.CertificateProcessedEvent) {
		sp.eventBus.Publish(evt)
	}(certEvent)

	// 如果没有域名，跳过
	if len(certInfo.AllDomains) == 0 {
		return nil
	}

	// 匹配域名
	matches := sp.matcher.MatchSubdomains(certInfo.AllDomains)
	if len(matches) == 0 {
		return nil // 没有匹配，直接丢弃
	}

	sp.stats.totalMatched++

	// 生成事件并发布
	for _, match := range matches {
		match.Certificate = certInfo

		event := &models.SubdomainDiscoveredEvent{
			BaseEvent: models.BaseEvent{
				Type:      models.EventTypeSubdomainDiscovered,
				ID:        models.GenerateEventID(),
				Timestamp: time.Now(),
			},
			SubdomainEvent: models.SubdomainEvent{
				Subdomain:    match.Subdomain,
				RootDomain:   match.RootDomain,
				Certificate:  certInfo,
				DiscoveredAt: match.MatchedAt,
				EventID:      models.GenerateEventID(),
				IsNew:        true,
			},
		}

		// 异步发布事件
		go func(evt *models.SubdomainDiscoveredEvent) {
			sp.eventBus.Publish(evt)
		}(event)
	}

	return nil
}

// GetStats 获取流处理器统计信息
func (sp *StreamProcessor) GetStats() *StreamProcessorStats {
	return &StreamProcessorStats{
		TotalProcessed: sp.stats.totalProcessed,
		TotalMatched:   sp.stats.totalMatched,
		TotalErrors:    sp.stats.totalErrors,
	}
}

// StreamProcessorStats 流处理器统计信息
type StreamProcessorStats struct {
	TotalProcessed int64 `json:"total_processed"`
	TotalMatched   int64 `json:"total_matched"`
	TotalErrors    int64 `json:"total_errors"`
}
