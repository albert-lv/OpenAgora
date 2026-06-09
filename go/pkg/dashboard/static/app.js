// Arena Dashboard Frontend
// Handles all Chart.js visualizations and API calls

const API_BASE = '/api/v1';
let charts = {};
let autoRefreshInterval = null;

// ========== Initialization ==========

document.addEventListener('DOMContentLoaded', () => {
    loadAll();
    setupAutoRefresh();
});

function setupAutoRefresh() {
    const checkbox = document.getElementById('auto-refresh');
    checkbox.addEventListener('change', () => {
        if (checkbox.checked) {
            startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    });
    if (checkbox.checked) {
        startAutoRefresh();
    }
}

function startAutoRefresh() {
    if (autoRefreshInterval) return;
    autoRefreshInterval = setInterval(loadAll, 5000);
}

function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
}

// ========== Main Load Function ==========

async function loadAll() {
    try {
        await Promise.all([
            loadMetrics(),
            loadTokenStats(),
            loadRollouts(),
            loadToolAnalysis(),
            loadVerifyAnalysis(),
        ]);
    } catch (e) {
        console.error('Error loading dashboard data:', e);
    }
}

// ========== Metrics API ==========

async function loadMetrics() {
    const data = await fetchJSON(`${API_BASE}/metrics`);
    if (!data) return;

    document.getElementById('total-rollouts').textContent = formatNumber(data.total_rollouts);
    document.getElementById('active-rollouts').textContent = formatNumber(data.active_rollouts);
    document.getElementById('success-rate').textContent = formatPercent(data.success_rate);
    document.getElementById('total-tokens').textContent = formatNumber(data.total_prompt_tokens + data.total_completion_tokens);
    document.getElementById('throughput').textContent = data.throughput_per_min?.toFixed(2) || '0.00';
    document.getElementById('avg-reward').textContent = data.avg_reward?.toFixed(3) || '0.000';

    updateStatusChart(data);
}

// ========== Token Stats API ==========

async function loadTokenStats() {
    const data = await fetchJSON(`${API_BASE}/tokens`);
    if (!data) return;

    updateTokenChart(data);
    updateTokenTimeline(data.timeline);
}

// ========== Rollouts API ==========

async function loadRollouts() {
    const data = await fetchJSON(`${API_BASE}/rollouts`);
    if (!data) return;

    const tbody = document.querySelector('#rollouts-table tbody');
    tbody.innerHTML = '';

    data.forEach(r => {
        const row = document.createElement('tr');
        const statusClass = r.status === 'success' ? 'status-success' : 
                           r.status === 'failed' ? 'status-failed' : 'status-running';
        row.innerHTML = `
            <td>${r.id.substring(0, 12)}...</td>
            <td>${r.task_id}</td>
            <td class="${statusClass}">${r.status}</td>
            <td>${r.reward?.toFixed(3) || '0.000'}</td>
            <td>${r.steps}</td>
            <td>${r.duration_sec?.toFixed(1) || '0.0'}s</td>
            <td>${r.created_at}</td>
        `;
        tbody.appendChild(row);
    });
}

// ========== Tool Analysis API ==========

async function loadToolAnalysis() {
    const data = await fetchJSON(`${API_BASE}/tools`);
    if (!data) return;

    updateToolFreqChart(data.tool_counts);
    updateToolSuccessChart(data.tool_counts);
    updateToolChains(data.tool_chains);
}

// ========== Verify Analysis API ==========

async function loadVerifyAnalysis() {
    const data = await fetchJSON(`${API_BASE}/verify`);
    if (!data) return;

    document.getElementById('verify-success-rate').textContent = formatPercent(data.success_rate);
    document.getElementById('verify-first-pass').textContent = formatPercent(data.first_pass_rate);
    document.getElementById('verify-total').textContent = formatNumber(data.total_rollouts);

    updateVerifyTrendChart(data.trend);
    updateFailureBreakdownChart(data.failure_breakdown);
    updateFailuresTable(data.recent_failures);
}

// ========== Chart Updates ==========

function updateStatusChart(metrics) {
    const ctx = document.getElementById('status-chart').getContext('2d');
    const data = [metrics.success_rate || 0, 1 - (metrics.success_rate || 0)];
    
    if (charts.status) charts.status.destroy();
    charts.status = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Success', 'Failed'],
            datasets: [{
                data: [data[0], data[1]],
                backgroundColor: ['#27ae60', '#e74c3c'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom' }
            }
        }
    });
}

function updateTokenChart(data) {
    const ctx = document.getElementById('token-chart').getContext('2d');
    
    if (charts.token) charts.token.destroy();
    charts.token = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['Prompt Tokens', 'Completion Tokens'],
            datasets: [{
                data: [data.total_prompt_tokens || 0, data.total_completion_tokens || 0],
                backgroundColor: ['#3498db', '#e74c3c'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            }
        }
    });
}

function updateTokenTimeline(timeline) {
    if (!timeline || timeline.length === 0) return;
    
    const ctx = document.getElementById('token-timeline-chart').getContext('2d');
    const labels = timeline.slice(-20).map(t => t.timestamp);
    const promptData = timeline.slice(-20).map(t => t.prompt_tokens);
    const completionData = timeline.slice(-20).map(t => t.completion_tokens);
    
    if (charts.tokenTimeline) charts.tokenTimeline.destroy();
    charts.tokenTimeline = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Prompt',
                    data: promptData,
                    borderColor: '#3498db',
                    fill: false
                },
                {
                    label: 'Completion',
                    data: completionData,
                    borderColor: '#e74c3c',
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom' } }
        }
    });
}

function updateToolFreqChart(toolCounts) {
    if (!toolCounts || toolCounts.length === 0) return;
    
    const ctx = document.getElementById('tool-freq-chart').getContext('2d');
    const labels = toolCounts.map(t => t.tool_name);
    const data = toolCounts.map(t => t.count);
    
    if (charts.toolFreq) charts.toolFreq.destroy();
    charts.toolFreq = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: generateColors(labels.length),
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } }
        }
    });
}

function updateToolSuccessChart(toolCounts) {
    if (!toolCounts || toolCounts.length === 0) return;
    
    const ctx = document.getElementById('tool-success-chart').getContext('2d');
    const labels = toolCounts.map(t => t.tool_name);
    const data = toolCounts.map(t => t.success_rate * 100);
    
    if (charts.toolSuccess) charts.toolSuccess.destroy();
    charts.toolSuccess = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: '#27ae60',
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true, max: 100 }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.raw.toFixed(1)}%`
                    }
                }
            }
        }
    });
}

function updateToolChains(toolChains) {
    const container = document.getElementById('tool-chains');
    container.innerHTML = '';
    
    if (!toolChains || toolChains.length === 0) {
        container.innerHTML = '<p>No data</p>';
        return;
    }
    
    toolChains.slice(0, 10).forEach(chain => {
        const div = document.createElement('div');
        div.className = 'chain-item';
        div.innerHTML = `
            <span class="chain-path">${chain.chain.join(' → ')}</span>
            <span class="chain-count">${chain.count} (${(chain.success_rate * 100).toFixed(1)}%)</span>
        `;
        container.appendChild(div);
    });
}

function updateVerifyTrendChart(trend) {
    if (!trend || trend.length === 0) return;
    
    const ctx = document.getElementById('verify-trend-chart').getContext('2d');
    const labels = trend.map(t => t.timestamp);
    const data = trend.map(t => t.rate * 100);
    
    if (charts.verifyTrend) charts.verifyTrend.destroy();
    charts.verifyTrend = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Success Rate (%)',
                data: data,
                borderColor: '#27ae60',
                fill: false,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true, max: 100 }
            }
        }
    });
}

function updateFailureBreakdownChart(failures) {
    if (!failures || failures.length === 0) return;
    
    const ctx = document.getElementById('failure-breakdown-chart').getContext('2d');
    const labels = failures.map(f => f.reason);
    const data = failures.map(f => f.count);
    
    if (charts.failureBreakdown) charts.failureBreakdown.destroy();
    charts.failureBreakdown = new Chart(ctx, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: generateColors(labels.length),
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom' },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.label}: ${ctx.raw} (${failures[ctx.dataIndex].percentage.toFixed(1)}%)`
                    }
                }
            }
        }
    });
}

function updateFailuresTable(failures) {
    const tbody = document.querySelector('#failures-table tbody');
    tbody.innerHTML = '';
    
    if (!failures || failures.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4">No failures</td></tr>';
        return;
    }
    
    failures.forEach(f => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${f.rollout_id?.substring(0, 12) || 'N/A'}...</td>
            <td>${f.task_id || 'N/A'}</td>
            <td>${f.reason || 'unknown'}</td>
            <td>${f.timestamp || 'N/A'}</td>
        `;
        tbody.appendChild(row);
    });
}

// ========== Utility Functions ==========

async function fetchJSON(url) {
    try {
        const response = await fetch(url);
        if (!response.ok) {
            console.error(`HTTP error ${response.status} for ${url}`);
            return null;
        }
        return await response.json();
    } catch (e) {
        console.error(`Fetch error for ${url}:`, e);
        return null;
    }
}

function formatNumber(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n?.toString() || '0';
}

function formatPercent(p) {
    return (p * 100).toFixed(1) + '%';
}

function generateColors(count) {
    const colors = [
        '#3498db', '#e74c3c', '#27ae60', '#f39c12', '#9b59b6',
        '#1abc9c', '#e67e22', '#34495e', '#16a085', '#c0392b'
    ];
    return Array.from({length: count}, (_, i) => colors[i % colors.length]);
}
