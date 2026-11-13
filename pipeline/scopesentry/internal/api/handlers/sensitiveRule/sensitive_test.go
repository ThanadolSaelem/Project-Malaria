package sensitiveRule

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestUpdateRequestAcceptsFalseState(t *testing.T) {
	gin.SetMode(gin.TestMode)

	var req updateRequest
	err := bindSensitiveRuleJSON(
		`{"id":"6642b0","name":"test-rule","regular":"test","color":"gray","state":false}`,
		&req,
	)
	if err != nil {
		t.Fatalf("expected update request with false state to bind: %v", err)
	}

	if req.State == nil {
		t.Fatal("expected state to be present")
	}
	if *req.State {
		t.Fatal("expected state to be false")
	}
}

func TestAddRequestAcceptsFalseState(t *testing.T) {
	gin.SetMode(gin.TestMode)

	var req addRequest
	err := bindSensitiveRuleJSON(
		`{"name":"test-rule","regular":"test","color":"gray","state":false}`,
		&req,
	)
	if err != nil {
		t.Fatalf("expected add request with false state to bind: %v", err)
	}

	if req.State == nil {
		t.Fatal("expected state to be present")
	}
	if *req.State {
		t.Fatal("expected state to be false")
	}
}

func TestUpdateRequestRequiresState(t *testing.T) {
	gin.SetMode(gin.TestMode)

	var req updateRequest
	err := bindSensitiveRuleJSON(
		`{"id":"6642b0","name":"test-rule","regular":"test","color":"gray"}`,
		&req,
	)
	if err == nil {
		t.Fatal("expected missing state to fail binding")
	}
}

func bindSensitiveRuleJSON(body string, req any) error {
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(http.MethodPost, "/", strings.NewReader(body))
	c.Request.Header.Set("Content-Type", "application/json")

	return c.ShouldBindJSON(req)
}
