package e2b

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/albert-lv/OpenAgora/go/pkg/sandbox"
)

func TestProviderCapabilities(t *testing.T) {
	p := NewProvider(nil)
	caps := p.Capabilities()
	if !caps.NetworkAllowlist {
		t.Fatal("expected NetworkAllowlist capability")
	}
}

func TestCreateWithoutAPIKey(t *testing.T) {
	p := NewProvider(nil)
	_, err := p.Create(context.Background(), &sandbox.Config{Image: "base"})
	if err == nil || !strings.Contains(err.Error(), "E2B_API_KEY") {
		t.Fatalf("expected E2B_API_KEY error, got %v", err)
	}
}

func TestCreateAndExec(t *testing.T) {
	var sandboxID string
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.Method + " " + r.URL.Path {
		case "POST /sandboxes":
			body, _ := io.ReadAll(r.Body)
			if !strings.Contains(string(body), `"template":"base"`) {
				t.Fatalf("unexpected body: %s", string(body))
			}
			if r.Header.Get("X-API-Key") != "test-key" {
				t.Fatalf("missing api key")
			}
			sandboxID = "sb-123"
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(map[string]string{"id": sandboxID})
		case "POST /sandboxes/" + sandboxID + "/commands":
			var req execRequest
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Fatalf("decode exec request: %v", err)
			}
			_ = json.NewEncoder(w).Encode(execResponse{
				Stdout:   "hello",
				Stderr:   "",
				ExitCode: 0,
			})
		case "DELETE /sandboxes/" + sandboxID:
			w.WriteHeader(http.StatusNoContent)
		default:
			t.Fatalf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
	}))
	defer ts.Close()

	p := NewProvider(map[string]string{"api_key": "test-key", "api_url": ts.URL})
	sb, err := p.Create(context.Background(), &sandbox.Config{Image: "base"})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if sb.ID != "sb-123" {
		t.Fatalf("expected sb-123, got %s", sb.ID)
	}

	res, err := p.Exec(context.Background(), sb.ID, []string{"echo", "hello"})
	if err != nil {
		t.Fatalf("exec: %v", err)
	}
	if res.ExitCode != 0 || string(res.Stdout) != "hello" {
		t.Fatalf("unexpected exec result: %+v", res)
	}

	if err := p.Destroy(context.Background(), sb); err != nil {
		t.Fatalf("destroy: %v", err)
	}
}
