// utils-------------------------------------
// @file      : requests.go
// @author    : Autumn
// @contact   : rainy-autumn@outlook.com
// @time      : 2025/12/22 22:14
// -------------------------------------------

package utils

import (
	"crypto/tls"
	"github.com/valyala/fasthttp"
	"time"
)

type request struct {
}

var Requests *request

var HttpClient *fasthttp.Client

type HttpResponse struct {
	StatusCode int
	Headers    map[string]string
	Body       []byte
}

func init() {
	tlsConfig := &tls.Config{
		InsecureSkipVerify: true,
	}

	HttpClient = &fasthttp.Client{
		ReadTimeout:                   time.Second * 10,
		WriteTimeout:                  time.Second * 10,
		MaxIdleConnDuration:           time.Second * 10,
		NoDefaultUserAgentHeader:      true,
		DisableHeaderNamesNormalizing: true,
		DisablePathNormalizing:        true,
		TLSConfig:                     tlsConfig,
		ReadBufferSize:                4 * 1024 * 1024,
		MaxResponseBodySize:           10 * 1024 * 1024,
		Dial: (&fasthttp.TCPDialer{
			Concurrency:      4096,
			DNSCacheDuration: time.Hour,
		}).Dial,
	}
	Requests = &request{}
}

type GetHttpResponse struct {
	Url           string
	StatusCode    int
	Body          string
	ContentLength int
	Redirect      string
	Title         string
}

func (r *request) HttpGet(uri string) (GetHttpResponse, error) {
	req, resp := fasthttp.AcquireRequest(), fasthttp.AcquireResponse()
	// 最后需要归还req、resp到池中
	defer func() {
		fasthttp.ReleaseRequest(req)
		fasthttp.ReleaseResponse(resp)
	}()
	req.Header.SetMethod(fasthttp.MethodGet)
	req.SetRequestURI(uri)
	if err := HttpClient.Do(req, resp); err != nil {
		return GetHttpResponse{}, err
	}
	tmp := GetHttpResponse{}
	tmp.Url = uri

	tmp.Body = string(resp.Body())
	tmp.StatusCode = resp.StatusCode()
	if location := resp.Header.Peek("location"); len(location) > 0 {
		tmp.Redirect = string(location)
	} else {
		rd := resp.Header.Peek("Location")
		if len(rd) > 0 {
			tmp.Redirect = string(rd)
		} else {
			tmp.Redirect = ""
		}
	}
	tmp.ContentLength = resp.Header.ContentLength()
	if tmp.ContentLength < 0 {
		tmp.ContentLength = len(resp.Body())
	}
	return tmp, nil
}

func (r *request) HttpPost(uri string, requestBody []byte, ct string) (error, HttpResponse) {
	req, resp := fasthttp.AcquireRequest(), fasthttp.AcquireResponse()
	defer func() {
		fasthttp.ReleaseRequest(req)
		fasthttp.ReleaseResponse(resp)
	}()
	req.Header.SetMethod(fasthttp.MethodPost)
	req.SetRequestURI(uri)
	if ct == "json" {
		req.Header.Set("Content-Type", "application/json")
		requestBody = fixJSONNewlines(requestBody)
	}
	req.SetBody(requestBody)

	if err := HttpClient.Do(req, resp); err != nil {
		return err, HttpResponse{}
	}
	headers := make(map[string]string)
	resp.Header.VisitAll(func(key, value []byte) {
		headers[string(key)] = string(value)
	})
	res := HttpResponse{
		StatusCode: resp.StatusCode(),
		Headers:    headers,
		Body:       append([]byte(nil), resp.Body()...),
	}
	return nil, res
}

func fixJSONNewlines(b []byte) []byte {
	var out []byte
	inString := false
	escaped := false

	for i := 0; i < len(b); i++ {
		c := b[i]

		if escaped {
			out = append(out, c)
			escaped = false
			continue
		}

		if c == '\\' {
			escaped = true
			out = append(out, c)
			continue
		}

		if c == '"' {
			inString = !inString
			out = append(out, c)
			continue
		}

		if inString && (c == '\n' || c == '\r') {
			// 转义换行
			out = append(out, '\\', 'n')
			continue
		}

		out = append(out, c)
	}

	return out
}
