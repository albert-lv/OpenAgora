package server

import (
	"net/http/httptest"
	"strings"
	"testing"
)

func TestMetricsHandler(t *testing.T) {
	m := NewMetrics()
	m.Inc("arena_rollouts_total", 2, "success")
	m.Observe("arena_rollout_duration_seconds", 0.045)
	m.Add("arena_rollouts_active", 1)

	rec := httptest.NewRecorder()
	m.Handler().ServeHTTP(rec, nil)

	body := rec.Body.String()
	if !strings.Contains(body, "# HELP arena_rollouts_total") {
		t.Fatalf("missing HELP for counter:\n%s", body)
	}
	if !strings.Contains(body, `arena_rollouts_total{status="success"} 2`) {
		t.Fatalf("missing counter value:\n%s", body)
	}
	if !strings.Contains(body, `arena_rollout_duration_seconds_bucket{le="0.05"}`) {
		t.Fatalf("missing histogram bucket:\n%s", body)
	}
	if !strings.Contains(body, `arena_rollouts_active 1`) {
		t.Fatalf("missing gauge value:\n%s", body)
	}
	if !strings.Contains(body, "# EOF") {
		t.Fatalf("missing Prometheus EOF:\n%s", body)
	}
}

func TestHistogramBuckets(t *testing.T) {
	m := NewMetrics()
	m.Observe("arena_rollout_duration_seconds", 0.01)
	m.Observe("arena_rollout_duration_seconds", 0.1)
	m.Observe("arena_rollout_duration_seconds", 1.0)

	rec := httptest.NewRecorder()
	m.Handler().ServeHTTP(rec, nil)
	body := rec.Body.String()

	if !strings.Contains(body, "arena_rollout_duration_seconds_count 3") {
		t.Fatalf("unexpected count:\n%s", body)
	}
	if !strings.Contains(body, "arena_rollout_duration_seconds_sum 1.11") {
		t.Fatalf("unexpected sum:\n%s", body)
	}
}
