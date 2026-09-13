package inference

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
)

// recordingBackend records request paths and payloads in order.
type recordingBackend struct {
	server   *httptest.Server
	paths    []string
	payloads []map[string]any
	// updateSuccess controls the success field of update_weights_from_disk.
	updateSuccess bool
}

func newRecordingBackend() *recordingBackend {
	rb := &recordingBackend{updateSuccess: true}
	rb.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var m map[string]any
		_ = json.Unmarshal(body, &m)
		rb.paths = append(rb.paths, r.URL.Path)
		rb.payloads = append(rb.payloads, m)
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/update_weights_from_disk" {
			if rb.updateSuccess {
				_ = json.NewEncoder(w).Encode(map[string]any{"success": true, "message": "ok"})
			} else {
				_ = json.NewEncoder(w).Encode(map[string]any{"success": false, "message": "boom"})
			}
			return
		}
		_, _ = w.Write([]byte(`{}`))
	}))
	return rb
}

func (rb *recordingBackend) Close() { rb.server.Close() }

func TestSGLangWeightSyncFlow(t *testing.T) {
	rb := newRecordingBackend()
	defer rb.Close()

	ws, err := NewWeightSyncer("sglang", rb.server.URL)
	if err != nil {
		t.Fatalf("NewWeightSyncer: %v", err)
	}
	ctx := context.Background()
	if err := ws.PauseGeneration(ctx, ""); err != nil {
		t.Fatalf("PauseGeneration: %v", err)
	}
	if err := ws.UpdateWeightsFromDisk(ctx, "/ckpt/step-10", "step-10", true); err != nil {
		t.Fatalf("UpdateWeightsFromDisk: %v", err)
	}
	if err := ws.ContinueGeneration(ctx); err != nil {
		t.Fatalf("ContinueGeneration: %v", err)
	}

	wantPaths := []string{"/pause_generation", "/update_weights_from_disk", "/continue_generation"}
	if !reflect.DeepEqual(rb.paths, wantPaths) {
		t.Fatalf("request order = %v, want %v", rb.paths, wantPaths)
	}
	if rb.payloads[0]["mode"] != "retract" {
		t.Fatalf("pause mode = %v, want retract", rb.payloads[0]["mode"])
	}
	up := rb.payloads[1]
	if up["model_path"] != "/ckpt/step-10" {
		t.Fatalf("model_path = %v", up["model_path"])
	}
	if up["weight_version"] != "step-10" {
		t.Fatalf("weight_version = %v", up["weight_version"])
	}
	if up["abort_all_requests"] != true {
		t.Fatalf("abort_all_requests = %v", up["abort_all_requests"])
	}
	if up["flush_cache"] != true {
		t.Fatalf("flush_cache = %v", up["flush_cache"])
	}
}

func TestSGLangUpdateWeightsFailure(t *testing.T) {
	rb := newRecordingBackend()
	defer rb.Close()
	rb.updateSuccess = false

	ws, err := NewWeightSyncer("sglang", rb.server.URL)
	if err != nil {
		t.Fatalf("NewWeightSyncer: %v", err)
	}
	err = ws.UpdateWeightsFromDisk(context.Background(), "/ckpt/bad", "step-x", false)
	if err == nil || !strings.Contains(err.Error(), "boom") {
		t.Fatalf("expected failure mentioning backend message, got %v", err)
	}
}

func TestVLLMWeightSync(t *testing.T) {
	rb := newRecordingBackend()
	defer rb.Close()

	ws, err := NewWeightSyncer("vllm", rb.server.URL)
	if err != nil {
		t.Fatalf("NewWeightSyncer: %v", err)
	}
	ctx := context.Background()
	if err := ws.PauseGeneration(ctx, ""); err != nil {
		t.Fatalf("PauseGeneration: %v", err)
	}
	err = ws.UpdateWeightsFromDisk(ctx, "/ckpt", "v1", false)
	if err == nil || !strings.Contains(err.Error(), "unsupported by backend") {
		t.Fatalf("expected unsupported-by-backend error, got %v", err)
	}
	if err := ws.ContinueGeneration(ctx); err != nil {
		t.Fatalf("ContinueGeneration: %v", err)
	}

	wantPaths := []string{"/pause", "/resume"}
	if !reflect.DeepEqual(rb.paths, wantPaths) {
		t.Fatalf("request paths = %v, want %v", rb.paths, wantPaths)
	}
	if rb.payloads[0]["mode"] != "keep" {
		t.Fatalf("pause mode = %v, want keep", rb.payloads[0]["mode"])
	}
}

func TestNewWeightSyncerValidation(t *testing.T) {
	if ws, err := NewWeightSyncer("", ""); ws != nil || err != nil {
		t.Fatalf("empty backend type should yield nil syncer, got %v, %v", ws, err)
	}
	if _, err := NewWeightSyncer("tgi", "http://localhost:8000"); err == nil {
		t.Fatal("expected error for unsupported backend type")
	}
	if _, err := NewWeightSyncer("sglang", ""); err == nil {
		t.Fatal("expected error for missing backend URL")
	}
}
