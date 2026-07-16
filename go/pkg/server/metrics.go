package server

import (
	"fmt"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Metrics implements a lightweight, Prometheus-compatible metrics collector.
// It is intentionally dependency-free so it works in offline / air-gapped
// environments where pulling the Prometheus Go client is not possible.
type Metrics struct {
	mu         sync.RWMutex
	counters   map[string]*counter
	histograms map[string]*histogram
	gauges     map[string]*gauge
}

// NewMetrics creates an empty Metrics instance pre-registered with the
// counters, histograms and gauges used by the Arena server.
func NewMetrics() *Metrics {
	m := &Metrics{
		counters:   make(map[string]*counter),
		histograms: make(map[string]*histogram),
		gauges:     make(map[string]*gauge),
	}

	// Rollout lifecycle.
	m.NewCounter("arena_rollouts_total", "Total number of rollouts by status", []string{"status"})
	m.NewHistogram("arena_rollout_duration_seconds", "End-to-end rollout duration", []string{}, defaultDurationBuckets())
	m.NewHistogram("arena_rollout_reward", "Reward returned by verification", []string{}, defaultRewardBuckets())
	m.NewGauge("arena_rollouts_active", "Number of currently active rollouts", []string{})

	// Verification.
	m.NewCounter("arena_verify_total", "Total number of verification runs by result", []string{"result"})
	m.NewHistogram("arena_verify_duration_seconds", "Verification command duration", []string{}, defaultDurationBuckets())

	// LLM proxy.
	m.NewCounter("arena_proxy_requests_total", "Total LLM requests proxied", []string{"endpoint"})
	m.NewCounter("arena_proxy_backend_errors_total", "Total backend errors", []string{})
	m.NewHistogram("arena_proxy_request_duration_seconds", "LLM request latency", []string{"endpoint"}, defaultDurationBuckets())
	m.NewCounter("arena_tokens_total", "Total tokens processed", []string{"kind"})

	return m
}

// NewCounter registers a counter metric.
func (m *Metrics) NewCounter(name, help string, labels []string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.counters[name] = &counter{name: name, help: help, labels: labels, values: make(map[string]uint64)}
}

// NewHistogram registers a histogram metric.
func (m *Metrics) NewHistogram(name, help string, labels []string, buckets []float64) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.histograms[name] = newHistogram(name, help, labels, buckets)
}

// NewGauge registers a gauge metric.
func (m *Metrics) NewGauge(name, help string, labels []string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.gauges[name] = &gauge{name: name, help: help, labels: labels, values: make(map[string]float64)}
}

// Inc increments a counter by value for the given label values.
func (m *Metrics) Inc(name string, value uint64, labelValues ...string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	c, ok := m.counters[name]
	if !ok {
		return
	}
	key := labelKey(c.labels, labelValues)
	c.values[key] += value
}

// Observe records a histogram sample.
func (m *Metrics) Observe(name string, value float64, labelValues ...string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	h, ok := m.histograms[name]
	if !ok {
		return
	}
	h.observe(value, labelValues)
}

// Set sets a gauge value.
func (m *Metrics) Set(name string, value float64, labelValues ...string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	g, ok := m.gauges[name]
	if !ok {
		return
	}
	key := labelKey(g.labels, labelValues)
	g.values[key] = value
}

// Add adds a delta to a gauge value.
func (m *Metrics) Add(name string, delta float64, labelValues ...string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	g, ok := m.gauges[name]
	if !ok {
		return
	}
	key := labelKey(g.labels, labelValues)
	g.values[key] += delta
}

// Handler returns an http.Handler that exposes metrics in Prometheus text format.
//
//nolint:errcheck
func (m *Metrics) Handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		m.mu.RLock()
		defer m.mu.RUnlock()

		for _, name := range sortedKeys(m.counters) {
			c := m.counters[name]
			fmt.Fprintf(w, "# HELP %s %s\n", c.name, c.help)
			fmt.Fprintf(w, "# TYPE %s counter\n", c.name)
			for _, key := range sortedKeys(c.values) {
				fmt.Fprintf(w, "%s%s %d\n", c.name, formatLabels(c.labels, key), c.values[key])
			}
		}

		for _, name := range sortedKeys(m.gauges) {
			g := m.gauges[name]
			fmt.Fprintf(w, "# HELP %s %s\n", g.name, g.help)
			fmt.Fprintf(w, "# TYPE %s gauge\n", g.name)
			for _, key := range sortedKeys(g.values) {
				fmt.Fprintf(w, "%s%s %s\n", g.name, formatLabels(g.labels, key), formatFloat(g.values[key]))
			}
		}

		for _, name := range sortedKeys(m.histograms) {
			h := m.histograms[name]
			fmt.Fprintf(w, "# HELP %s %s\n", h.name, h.help)
			fmt.Fprintf(w, "# TYPE %s histogram\n", h.name)
			for _, key := range sortedKeys(h.counts) {
				buckets := h.bucketsFor(key)
				keyValues := splitKey(key)
				for _, b := range buckets {
					boundStr := "+Inf"
					if f, ok := b.bound.(float64); ok {
						boundStr = formatFloat(f)
					}
					fmt.Fprintf(w, "%s_bucket%s %d\n", h.name, formatLabels(append(h.labels, "le"), append(keyValues, boundStr)...), b.count)
				}
				fmt.Fprintf(w, "%s_sum%s %s\n", h.name, formatLabels(h.labels, keyValues...), formatFloat(h.sums[key]))
				fmt.Fprintf(w, "%s_count%s %d\n", h.name, formatLabels(h.labels, keyValues...), h.counts[key])
			}
		}
		fmt.Fprintln(w, "# EOF")
	})
}

type counter struct {
	name   string
	help   string
	labels []string
	values map[string]uint64
}

type gauge struct {
	name   string
	help   string
	labels []string
	values map[string]float64
}

type histogram struct {
	name         string
	help         string
	labels       []string
	buckets      []float64
	counts       map[string]uint64
	sums         map[string]float64
	bucketCounts map[string][]uint64 // one count per bucket per label key
}

func newHistogram(name, help string, labels []string, buckets []float64) *histogram {
	return &histogram{
		name:         name,
		help:         help,
		labels:       labels,
		buckets:      buckets,
		counts:       make(map[string]uint64),
		sums:         make(map[string]float64),
		bucketCounts: make(map[string][]uint64),
	}
}

func (h *histogram) observe(value float64, labelValues []string) {
	key := labelKey(h.labels, labelValues)
	h.sums[key] += value
	h.counts[key]++
	if _, ok := h.bucketCounts[key]; !ok {
		h.bucketCounts[key] = make([]uint64, len(h.buckets))
	}
	for i, b := range h.buckets {
		if value <= b {
			h.bucketCounts[key][i]++
			break // raw bucket count; cumulative is computed on exposition
		}
	}
}

func (h *histogram) bucketsFor(key string) []bucketCount {
	var out []bucketCount
	var cumulative uint64
	counts := h.bucketCounts[key]
	for i, b := range h.buckets {
		if i < len(counts) {
			cumulative += counts[i]
		}
		out = append(out, bucketCount{bound: b, count: cumulative})
	}
	out = append(out, bucketCount{bound: "+Inf", count: h.counts[key]})
	return out
}

type bucketCount struct {
	bound interface{}
	count uint64
}

func defaultDurationBuckets() []float64 {
	return []float64{0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300}
}

func defaultRewardBuckets() []float64 {
	return []float64{0, 0.25, 0.5, 0.75, 1}
}

func labelKey(labels []string, values []string) string {
	if len(values) != len(labels) {
		return ""
	}
	return strings.Join(values, "\x00")
}

func splitKey(key string) []string {
	if key == "" {
		return nil
	}
	return strings.Split(key, "\x00")
}

func formatLabels(labels []string, values ...string) string {
	if len(labels) == 0 {
		return ""
	}
	pairs := make([]string, 0, len(labels))
	for i, l := range labels {
		v := ""
		if i < len(values) {
			v = values[i]
		}
		pairs = append(pairs, fmt.Sprintf(`%s="%s"`, l, strconv.Quote(v)))
		// strconv.Quote wraps with quotes and escapes; strip outer quotes for label value.
		pairs[i] = fmt.Sprintf(`%s=%s`, l, strconv.Quote(v))
	}
	return "{" + strings.Join(pairs, ",") + "}"
}

func formatFloat(v float64) string {
	return strconv.FormatFloat(v, 'f', -1, 64)
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// since is a helper for measuring elapsed time.
func since(t time.Time) float64 {
	return time.Since(t).Seconds()
}
